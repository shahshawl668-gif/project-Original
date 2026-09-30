import io
import csv
import json
import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write
from app.envelope import ok
from app.models import (
    ComponentConfig,
    Entity,
    ImportProfile,
    PayrollRun,
    SalaryRegister,
    SalaryRegisterRow,
    TenantRulePreference,
    User,
)
from app.schemas.payroll import UploadParseResponse, ValidateRequest
from app.services import (
    audit,
    coverage,
    export_safety,
    finding_store,
    register_ingest,
    register_uploads,
    run_inputs,
    validation_jobs,
)
from app.services.payroll_parse import (
    allowed_destinations,
    check_mapping,
    parse_payroll_file,
    required_fields,
    suggested_mapping,
    suggestion_basis,
    normalize_col,
)
from app.services.validation import (
    apply_suppressed_rules,
    validate_employees,
)

router = APIRouter()


@router.get("/template.csv")
def download_register_template(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """A header-only template that follows this entity's configured components."""
    comps = db.query(ComponentConfig).filter(ComponentConfig.entity_id == entity.id).order_by(ComponentConfig.component_name).all()
    output = io.StringIO()
    csv.writer(output).writerow([
        "Employee ID", "Employee Name", "State", "Location", "Total Days", "LOP Days",
        *[c.component_name for c in comps if normalize_col(c.component_name) not in allowed_destinations(set())],
        "Gross", "Total Deductions", "Net", "PF Employee", "ESIC Employee",
        "PT", "LWF Employee", "TDS",
    ])
    return Response(
        content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="salary-register-template.csv"'},
    )


@router.get("/import-profiles")
def list_import_profiles(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    profiles = db.query(ImportProfile).filter(ImportProfile.entity_id == entity.id).order_by(ImportProfile.name).all()
    return ok([{"id": str(p.id), "name": p.name, "column_mapping": p.column_mapping} for p in profiles])


@router.post("/import-profiles")
def save_import_profile(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    name = str(body.get("name", "")).strip()
    mapping = body.get("column_mapping")
    if not name or len(name) > 100 or not isinstance(mapping, dict):
        raise HTTPException(status_code=400, detail="Provide a profile name and column mapping.")
    comps = db.query(ComponentConfig).filter(ComponentConfig.entity_id == entity.id).all()
    try:
        check_mapping(list(mapping), mapping, {c.component_name for c in comps})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    profile = db.query(ImportProfile).filter(ImportProfile.entity_id == entity.id, ImportProfile.name == name).first()
    if profile:
        profile.column_mapping = dict(mapping)
    else:
        profile = ImportProfile(entity_id=entity.id, user_id=user.id, name=name, column_mapping=dict(mapping))
        db.add(profile)
    db.commit()
    db.refresh(profile)
    return ok({"id": str(profile.id), "name": profile.name, "column_mapping": profile.column_mapping})


@router.post("/preview")
async def preview_register(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    try:
        df = parse_payroll_file(await file.read(), file.filename or "upload.csv")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    columns = list(df.columns)
    if any(not normalize_col(col) for col in columns):
        raise HTTPException(status_code=400, detail="Every register column needs a header.")
    comps = db.query(ComponentConfig).filter(ComponentConfig.entity_id == entity.id).all()
    names = {c.component_name for c in comps}
    return ok({
        "columns": columns,
        "mapping": suggested_mapping(columns, names),
        "match": suggestion_basis(columns, names),
        "destinations": sorted(allowed_destinations(names)),
        # Required under the strict header check; with it off only Employee ID is.
        "required": required_fields(names, strict=True),
        "components": sorted({normalize_col(n) for n in names}),
        "preview": df.head(5).fillna("").astype(str).to_dict(orient="records"),
        "employee_count": len(df),
    })


def _to_first_of_month(d: date | None) -> date | None:
    if d is None:
        return None
    return d.replace(day=1)


def _suppressed_rule_ids(db: Session, entity_id: uuid.UUID) -> set[str]:
    rows = (
        db.query(TenantRulePreference.rule_id)
        .filter(
            TenantRulePreference.entity_id == entity_id,
            TenantRulePreference.suppressed.is_(True),
        )
        .all()
    )
    return {r[0] for r in rows}


_persist_salary_register = register_ingest.persist_salary_register


def _payload_after_validation(rows: list, findings_summary: dict) -> dict:
    all_findings: list = []
    for r in rows:
        all_findings.extend(r.get("findings", []))
    # People the register does not contain are still part of the month.
    all_findings.extend(findings_summary.get("unmatched_findings", []))
    risk_list = [
        {
            "employee_id": r["employee_id"],
            "employee_name": r.get("employee_name"),
            "risk_score": r["risk_score"],
            "risk_level": r["risk_level"],
            "score_breakdown": r.get("score_breakdown", {}),
        }
        for r in rows
    ]
    return {
        "results": rows,
        "findings": all_findings,
        "findings_summary": findings_summary,
        "risk_scores": risk_list,
    }


@router.post("/upload")
async def upload_payroll(
    file: UploadFile = File(...),
    meta: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    try:
        payload = json.loads(meta)
        run_type = payload.get("run_type", "regular")
        eff_from = payload.get("effective_month_from")
        eff_to = payload.get("effective_month_to")
        period_month = payload.get("period_month")
        strict = payload.get("strict_header_check", True)
        column_mapping = payload.get("column_mapping")
        # The product's own screens ask for a summary: a 20,000-row register
        # echoed back to a phone is megabytes nobody reads. API callers that
        # validate synchronously still get the rows by default.
        return_employees = payload.get("return_employees", True) is not False
        eff_from_d = date.fromisoformat(eff_from) if eff_from else None
        eff_to_d = date.fromisoformat(eff_to) if eff_to else None
        period_month_d = date.fromisoformat(period_month) if period_month else None
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid meta JSON")

    raw = await file.read()
    try:
        df = parse_payroll_file(raw, file.filename or "upload.csv")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        result = register_ingest.ingest_register(
            db, entity=entity, user=user, df=df, filename=file.filename, content=raw,
            run_type=run_type, period_month=period_month_d, effective_month_from=eff_from_d,
            effective_month_to=eff_to_d, strict=strict, column_mapping=column_mapping,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    columns, employees = result["columns"], result["employees"]
    missing, warnings, upload = result["missing"], result["warnings"], result["upload"]
    preview = employees[:5]

    out = UploadParseResponse(
        columns=columns,
        preview=preview,
        employees=employees if return_employees else [],
        missing_required=missing,
        warnings=warnings,
    )
    data = out.model_dump()
    data["employee_count"] = len(employees)
    data["upload"] = register_uploads.describe(upload)
    return ok(data)


@router.post("/validate")
def validate_payroll(
    body: ValidateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    comps = db.query(ComponentConfig).filter(ComponentConfig.entity_id == entity.id).all()
    if not comps:
        raise HTTPException(status_code=400, detail="Configure salary components before validation.")
    period_month = _to_first_of_month(body.period_month or body.effective_month_to)
    if len(body.employees) > settings.sync_validate_max_employees:
        return _queue_instead(db, body, user, entity, period_month)
    started = datetime.now(UTC)
    # Fingerprinted before validation reads anything, like the worker does.
    config = run_inputs.configuration_snapshot(db, entity, period_month) if period_month else None
    rows, findings_summary = validate_employees(
        db,
        entity,
        comps,
        body.employees,
        body.run_type,
        body.effective_month_from,
        body.effective_month_to,
        body.as_of_date,
        period_month=period_month,
    )
    suppressed = _suppressed_rule_ids(db, entity.id)
    findings_summary = apply_suppressed_rules(
        rows, suppressed, findings_summary.get("unmatched_findings"),
    )

    lifecycle: dict = {}
    if period_month:
        findings_summary["coverage"] = coverage.annotate_run(
            db, entity, period_month, rows, body.employees,
            findings_summary.get("unmatched_findings"), suppressed,
        )
        # Persisting the run is what turns validation from a one-off report into
        # a record: waivers carry forward, recurrence becomes countable, and the
        # exposure history survives the browser tab.
        all_findings = [f for row in rows for f in row.get("findings", [])]
        all_findings.extend(findings_summary.get("unmatched_findings", []))
        _, rows_digest = register_uploads.encode_rows(body.employees)
        digests = run_inputs.input_digests(
            db, entity, period_month, rows_sha256=rows_digest, config=config,
        )
        run = finding_store.record_run(
            db,
            entity_id=entity.id,
            user_id=user.id,
            period_month=period_month,
            findings=all_findings,
            employee_count=len(rows),
            summary=findings_summary,
            results=rows,
            source_rows=body.employees,
            source="api",
            run_type=body.run_type,
            params={
                "effective_month_from": body.effective_month_from.isoformat() if body.effective_month_from else None,
                "effective_month_to": body.effective_month_to.isoformat() if body.effective_month_to else None,
                "as_of_date": body.as_of_date.isoformat() if body.as_of_date else None,
            },
            input_digests=digests,
            config_snapshot=config,
            started_at=started,
        )
        db.commit()
        lifecycle = {
            "run_id": str(run.id),
            "run_number": run.run_number,
            "period_month": period_month.isoformat(),
            "gross_financial_impact": float(run.total_financial_impact),
            "open_financial_impact": float(run.open_financial_impact),
        }

    payload = _payload_after_validation(rows, findings_summary)
    payload["lifecycle"] = lifecycle
    return ok(payload)


@router.get("/runs")
def list_payroll_runs(
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    runs = (
        db.query(PayrollRun)
        .filter(PayrollRun.entity_id == entity.id)
        .order_by(PayrollRun.created_at.desc())
        .limit(limit)
        .all()
    )
    data = [
        {
            "id": str(r.id),
            "run_type": r.run_type,
            "filename": r.filename,
            "employee_count": r.employee_count,
            "effective_month_from": r.effective_month_from.isoformat() if r.effective_month_from else None,
            "effective_month_to": r.effective_month_to.isoformat() if r.effective_month_to else None,
            "created_at": r.created_at.isoformat(),
        }
        for r in runs
    ]
    return ok(data)


@router.get("/registers")
def list_salary_registers(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    regs = (
        db.query(SalaryRegister)
        .filter(SalaryRegister.entity_id == entity.id)
        .order_by(SalaryRegister.period_month.desc())
        .all()
    )
    data = [
        {
            "id": str(r.id),
            "period_month": r.period_month.isoformat(),
            "filename": r.filename,
            "employee_count": r.employee_count,
            "created_at": r.created_at.isoformat(),
        }
        for r in regs
    ]
    return ok(data)


@router.get("/registers/{register_id}")
def get_salary_register(
    register_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    try:
        rid = uuid.UUID(register_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Register not found")
    reg = (
        db.query(SalaryRegister).filter(SalaryRegister.id == rid, SalaryRegister.entity_id == entity.id).first()
    )
    if not reg:
        raise HTTPException(status_code=404, detail="Register not found")
    rows = (
        db.query(SalaryRegisterRow)
        .filter(SalaryRegisterRow.register_id == reg.id)
        .order_by(SalaryRegisterRow.employee_id)
        .all()
    )
    payload = {
        "id": str(reg.id),
        "period_month": reg.period_month.isoformat(),
        "filename": reg.filename,
        "employee_count": reg.employee_count,
        "created_at": reg.created_at.isoformat(),
        "rows": [
            {
                "employee_id": r.employee_id,
                "employee_name": r.employee_name,
                "paid_days": float(r.paid_days) if r.paid_days is not None else None,
                "lop_days": float(r.lop_days) if r.lop_days is not None else None,
                "components": r.components,
                "arrears": r.arrears,
                "increment_arrear_total": float(r.increment_arrear_total) if r.increment_arrear_total else 0,
            }
            for r in rows
        ],
    }
    return ok(payload)


def _too_large(count: int, *, what: str) -> str:
    return (
        f"{count:,} employees is more than {what} handles inside one request "
        f"(the limit is {settings.sync_validate_max_employees:,}). Queue it instead: "
        "POST /api/validation/jobs validates the month's upload in the background."
    )


def _queue_instead(db: Session, body: ValidateRequest, user: User, entity: Entity, period_month):
    """Store a large request's rows as an upload and queue their validation.

    The rows are kept exactly as posted, like any upload, so the run is as
    reproducible as one started from the screen. The response is 202 with the
    job; its run appears under /api/validation/runs when the job succeeds.
    """
    if period_month is None:
        raise HTTPException(
            status_code=413,
            detail=_too_large(len(body.employees), what="validation")
            + " A queued validation needs period_month.",
        )
    content = json.dumps(body.employees, default=str, sort_keys=True).encode("utf-8")
    columns = sorted({str(k) for row in body.employees for k in row})
    upload = register_uploads.record(
        db, entity_id=entity.id, user_id=user.id, period_month=period_month,
        run_type=body.run_type, filename="api-validate-request.json", content=content,
        rows=body.employees, source_columns=columns, column_mapping=None,
        missing_required=None, warnings=None,
    )
    params = {
        "effective_month_from": body.effective_month_from.isoformat() if body.effective_month_from else None,
        "effective_month_to": body.effective_month_to.isoformat() if body.effective_month_to else None,
        "as_of_date": body.as_of_date.isoformat() if body.as_of_date else None,
    }
    try:
        job, already = validation_jobs.submit_for_period(
            db, entity_id=entity.id, user_id=user.id, period_month=period_month,
            upload_id=upload.id, run_type=body.run_type, params=params,
        )
    except validation_jobs.SubmitError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail)
    if already:
        # Another validation of this month is live; the request's rows were not
        # queued behind it, so nothing is kept and the caller is told why.
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A validation of {period_month:%b %Y} is already running (job {job.id}). "
            "Wait for it to finish, then send this register again.",
        )
    db.commit()
    return JSONResponse(status_code=202, content=ok({
        "queued": True,
        "reason": _too_large(len(body.employees), what="validation"),
        "job": {"id": str(job.id), "state": job.state, "period_month": period_month.isoformat()},
        "upload_id": str(upload.id),
        "follow": f"/api/validation/jobs/{job.id}",
        "results": "/api/validation/runs?period_month=" + period_month.isoformat(),
    }))


@router.post("/validate/export-excel")
def export_findings_excel(
    body: ValidateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """Run validation and return findings as an Excel workbook (binary stream, not JSON envelope)."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl not installed.")

    comps = db.query(ComponentConfig).filter(ComponentConfig.entity_id == entity.id).all()
    if not comps:
        raise HTTPException(status_code=400, detail="Configure salary components before export.")
    if len(body.employees) > settings.sync_validate_max_employees:
        raise HTTPException(
            status_code=413,
            detail=_too_large(len(body.employees), what="the Excel export")
            + " The finished run downloads from /api/validation/runs/{run_id}/export.xlsx.",
        )
    period_month = _to_first_of_month(body.period_month or body.effective_month_to)
    rows, findings_summary = validate_employees(
        db,
        entity,
        comps,
        body.employees,
        body.run_type,
        body.effective_month_from,
        body.effective_month_to,
        body.as_of_date,
        period_month=period_month,
    )
    suppressed = _suppressed_rule_ids(db, entity.id)
    findings_summary = apply_suppressed_rules(
        rows, suppressed, findings_summary.get("unmatched_findings"),
    )

    wb = openpyxl.Workbook()

    ws_sum = wb.active
    ws_sum.title = "Summary"
    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="1E293B")

    ws_sum.append(["Metric", "Value"])
    for cell in ws_sum[1]:
        cell.font = hdr_font
        cell.fill = hdr_fill

    ws_sum.append(["Total Employees", len(rows)])
    ws_sum.append(["Total Findings", findings_summary.get("total_findings", 0)])
    ws_sum.append(["Critical", findings_summary.get("critical", 0)])
    ws_sum.append(["Warning", findings_summary.get("warning", 0)])
    ws_sum.append(["Info", findings_summary.get("info", 0)])
    ws_sum.append(["Passed", findings_summary.get("pass", 0)])
    ws_sum.append(["Total Financial Impact (₹)", findings_summary.get("total_financial_impact", 0)])
    ws_sum.column_dimensions["A"].width = 30
    ws_sum.column_dimensions["B"].width = 20

    ws_f = wb.create_sheet("Findings")
    f_headers = [
        "Employee ID",
        "Employee Name",
        "Rule ID",
        "Rule Name",
        "Component",
        "Expected",
        "Actual",
        "Difference",
        "Severity",
        "Status",
        "Reason",
        "Suggested Fix",
        "Financial Impact (₹)",
    ]
    ws_f.append(f_headers)
    for cell in ws_f[1]:
        cell.font = hdr_font
        cell.fill = hdr_fill

    severity_fills = {
        "CRITICAL": PatternFill("solid", fgColor="FEE2E2"),
        "WARNING": PatternFill("solid", fgColor="FEF9C3"),
        "INFO": PatternFill("solid", fgColor="EFF6FF"),
    }
    all_findings = [f for emp in rows for f in emp.get("findings", [])]
    all_findings.extend(findings_summary.get("unmatched_findings", []))
    for f in all_findings:
        row_data = [
            f.get("employee_id", ""),
            f.get("employee_name", ""),
            f.get("rule_id", ""),
            f.get("rule_name", ""),
            f.get("component", ""),
            f.get("expected_value", ""),
            f.get("actual_value", ""),
            f.get("difference", ""),
            f.get("severity", ""),
            f.get("status", ""),
            f.get("reason", ""),
            f.get("suggested_fix", ""),
            f.get("financial_impact", 0),
        ]
        ws_f.append(row_data)
        if f.get("status") == "FAIL":
            sev = f.get("severity", "")
            fill = severity_fills.get(sev)
            if fill:
                for cell in ws_f[ws_f.max_row]:
                    cell.fill = fill

    for col in ws_f.columns:
        ws_f.column_dimensions[col[0].column_letter].width = 22
    ws_f.column_dimensions["K"].width = 60
    ws_f.column_dimensions["L"].width = 60

    ws_r = wb.create_sheet("Risk Scores")
    ws_r.append(["Employee ID", "Employee Name", "Risk Score", "Risk Level"])
    for cell in ws_r[1]:
        cell.font = hdr_font
        cell.fill = hdr_fill

    level_fills = {
        "HIGH": PatternFill("solid", fgColor="FEE2E2"),
        "MEDIUM": PatternFill("solid", fgColor="FEF9C3"),
        "LOW": PatternFill("solid", fgColor="F0FDF4"),
    }
    for emp in rows:
        ws_r.append(
            [
                emp.get("employee_id", ""),
                emp.get("employee_name", ""),
                emp.get("risk_score", 0),
                emp.get("risk_level", "LOW"),
            ]
        )
        lvl = emp.get("risk_level", "LOW")
        if lvl in level_fills:
            for cell in ws_r[ws_r.max_row]:
                cell.fill = level_fills[lvl]

    for col in ["A", "B", "C", "D"]:
        ws_r.column_dimensions[col].width = 25

    export_safety.neutralise_workbook(wb)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    audit.record(db, entity_id=entity.id, user=user, action="export.downloaded", object_type="validation_export",
                 summary=f"Downloaded findings for {len(body.employees)} employees",
                 detail={"format": "xlsx", "employees": len(body.employees)})
    db.commit()

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=payroll-audit-report.xlsx"},
    )


@router.get("/dashboard-stats")
def dashboard_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    n_comp = db.query(ComponentConfig).filter(ComponentConfig.entity_id == entity.id).count()
    last_run = (
        db.query(PayrollRun)
        .filter(PayrollRun.entity_id == entity.id)
        .order_by(PayrollRun.created_at.desc())
        .first()
    )
    last_register = (
        db.query(SalaryRegister)
        .filter(SalaryRegister.entity_id == entity.id)
        .order_by(SalaryRegister.period_month.desc())
        .first()
    )
    payload = {
        "components_configured": n_comp,
        "last_run_employee_count": last_run.employee_count if last_run else 0,
        "last_run_at": last_run.created_at.isoformat() if last_run else None,
        "last_register_period": last_register.period_month.isoformat() if last_register else None,
        "message": "Upload and validate payroll to populate PF/ESIC stats.",
    }
    return ok(payload)
