"""
Disbursement validation: is this salary payment file safe to release?

The product reads the bank payment file another system produced, checks it
against the register and the bank master, and hands back a verdict, a clean
copy without the lines that must not be paid, and an approval pack. **It
never sends the file anywhere and never pays anyone**: a person approves here,
then a person uploads the clean file to the bank.

Who may do what:

* any member of the company sees the history and the headline figures, which
  carry no bank details;
* running a check, and reading its findings or downloading anything — which
  show account numbers in full, by the company's decision — needs an analyst,
  manager or owner of that company. Support access does not reach them;
* approving a release needs an owner or manager; when the organisation turns
  on ``disbursement_release_requires_independent_approver`` the person who
  ran the check cannot approve it;
* changing the thresholds, severities and layouts needs an owner or manager.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_admin, require_entity_write
from app.envelope import ok
from app.models import DisbursementApproval, DisbursementRun, DisbursementSettings, Entity, User
from app.services import approvals, audit, tenancy
from app.services.disbursement import config, inputs, outputs
from app.services.disbursement import template as templates
from app.services.disbursement.check import previous_from_paid, run_check

router = APIRouter()

MAX_FILE_MB = 20
SLOTS = ("bank_file", "register", "bank_master", "change_log", "previous", "hold_list", "offcycle")
POLICY = "disbursement_release_requires_independent_approver"
MEDIA = {
    ".csv": "text/csv", ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(UTC)


def _period(value: str) -> date:
    try:
        year, month = (int(x) for x in value.split("-"))
        return date(year, month, 1)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="The period must be a month as YYYY-MM.")


def _settings_row(db: Session, entity: Entity) -> DisbursementSettings | None:
    return db.query(DisbursementSettings).filter(DisbursementSettings.entity_id == entity.id).first()


def _profiles(row: DisbursementSettings | None) -> dict[str, dict[str, Any]]:
    return {**inputs.builtin_profiles(), **((row.custom_profiles if row else None) or {})}


def _templates(row: DisbursementSettings | None) -> dict[str, dict[str, Any]]:
    return {**templates.builtin_templates(), **((row.custom_templates if row else None) or {})}


def _gz(data: Any) -> bytes:
    # mtime=0: the same report compresses to the same bytes.
    return gzip.compress(json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"), mtime=0)


def _ungz(blob: bytes | None) -> Any:
    return json.loads(gzip.decompress(blob).decode("utf-8")) if blob else None


def clear_expired_files(db: Session, entity_id: uuid.UUID | None = None) -> int:
    """Clear the clean file and paid list of runs past their retention. The report and fingerprints stay."""
    query = db.query(DisbursementRun).filter(DisbursementRun.files_expire_at <= _now(),
                                             DisbursementRun.files_cleared_at.is_(None))
    if entity_id is not None:
        query = query.filter(DisbursementRun.entity_id == entity_id)
    runs = query.limit(200).all()
    for run in runs:
        run.clean_file = None
        run.paid_gz = None
        run.files_cleared_at = _now()
    if runs:
        db.flush()
    return len(runs)


def _load_run(db: Session, entity: Entity, run_id: uuid.UUID) -> DisbursementRun:
    run = db.get(DisbursementRun, run_id)
    if run is None or run.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Check not found")
    return run


def _approval(db: Session, run: DisbursementRun) -> DisbursementApproval | None:
    return db.query(DisbursementApproval).filter(DisbursementApproval.run_id == run.id).first()


def _approval_out(a: DisbursementApproval | None) -> dict[str, Any] | None:
    if a is None:
        return None
    return {"approver": a.approver_name, "approver_email": a.approver_email, "approver_role": a.approver_role,
            "approved_at": a.approved_at.isoformat() if a.approved_at else None, "fingerprint": a.fingerprint,
            "acknowledged": a.acknowledged, "independent": a.independent,
            "independence_required": a.independence_required, "comment": a.comment,
            "release_amount": a.release_amount, "release_employees": a.release_employees}


def _unchecked(run: DisbursementRun) -> list[str]:
    return sorted(k for k, v in (run.rule_status or {}).items() if v in (config.NOT_RUN, config.DISABLED))


def _newer_run(db: Session, run: DisbursementRun) -> DisbursementRun | None:
    return (db.query(DisbursementRun)
            .filter(DisbursementRun.entity_id == run.entity_id, DisbursementRun.period_month == run.period_month,
                    DisbursementRun.created_at > run.created_at)
            .order_by(DisbursementRun.created_at.desc()).first())


def _run_out(db: Session, run: DisbursementRun, approval: DisbursementApproval | None = None) -> dict[str, Any]:
    return {
        "id": str(run.id), "period": run.period_month.strftime("%Y-%m"),
        "value_date": run.value_date.isoformat() if run.value_date else None,
        "verdict": run.verdict, "status": run.status, "profile_key": run.profile_key,
        "template_key": run.template_key, "bank_filename": run.bank_filename, "totals": run.totals,
        "rule_status": run.rule_status, "unchecked": _unchecked(run),
        "clean_filename": run.clean_filename, "clean_sha256": run.clean_sha256,
        "clean_available": run.clean_file is not None,
        "files_expire_at": run.files_expire_at.isoformat() if run.files_expire_at else None,
        "files_cleared_at": run.files_cleared_at.isoformat() if run.files_cleared_at else None,
        "previous_run_id": str(run.previous_run_id) if run.previous_run_id else None,
        "run_by": run.run_by_email, "created_at": run.created_at.isoformat() if run.created_at else None,
        "approval": _approval_out(approval),
    }


def _file(content: bytes, filename: str, media: str) -> StreamingResponse:
    safe = filename.replace('"', "").replace("\r", "").replace("\n", "")
    return StreamingResponse(io.BytesIO(content), media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{safe}"', "Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# What exists: the checks, the layouts, and this company's settings
# ---------------------------------------------------------------------------
@router.get("/catalogue")
def catalogue(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    row = _settings_row(db, entity)
    return ok({
        "rules": [{"rule_id": r.rule_id, "title": r.title, "level": r.level,
                   "default_severity": r.default_severity, "allowed": list(r.allowed), "needs": list(r.needs)}
                  for r in config.RULES],
        "defaults": {k: v for k, v in config.DEFAULTS.items() if k not in ("severities", "enabled")},
        "profiles": [{"key": k, "name": p.get("name", k), "note": p.get("note", ""),
                      "bank_template": p.get("bank_template"), "builtin": k in inputs.builtin_profiles()}
                     for k, p in _profiles(row).items()],
        "templates": [{"key": k, "name": t.get("name", k), "note": t.get("note", ""),
                       "layout": t.get("layout", "delimited"), "builtin": k in templates.builtin_templates()}
                      for k, t in _templates(row).items()],
        "inputs": [{"slot": s, "label": inputs.LABEL[s].capitalize(), "required": s in ("bank_file", "register")}
                   for s in SLOTS],
        "retention_days": app_settings.disbursement_file_retention_days,
    })


def _settings_out(db: Session, entity: Entity, row: DisbursementSettings | None) -> dict[str, Any]:
    return {
        "profile_key": row.profile_key if row else "generic",
        "template_key": row.template_key if row else None,
        "overrides": (row.overrides if row else None) or {},
        "custom_profiles": (row.custom_profiles if row else None) or {},
        "custom_templates": (row.custom_templates if row else None) or {},
        "updated_by": row.updated_by_email if row else None,
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        "independence_required": approvals.policy_for(db, entity.org_id).get(POLICY, False),
    }


@router.get("/settings")
def get_settings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    return ok(_settings_out(db, entity, _settings_row(db, entity)))


class SettingsBody(BaseModel):
    profile_key: str = Field(default="generic", max_length=64)
    template_key: str | None = Field(default=None, max_length=64)
    overrides: dict[str, Any] = Field(default_factory=dict)
    custom_profiles: dict[str, Any] = Field(default_factory=dict)
    custom_templates: dict[str, Any] = Field(default_factory=dict)


@router.put("/settings")
def put_settings(
    body: SettingsBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    """Owners and managers: these decide which payments are held."""
    builtin_p, builtin_t = inputs.builtin_profiles(), templates.builtin_templates()
    try:
        custom_t = {}
        for key, t in body.custom_templates.items():
            if not isinstance(t, dict):
                raise ValueError(f"Layout '{key}' must be an object.")
            if key in builtin_t:
                raise ValueError(f"'{key}' is a built-in layout; give your own a different key.")
            custom_t[key] = templates.check_template({**t, "key": key})
        custom_p = {}
        for key, p in body.custom_profiles.items():
            if not isinstance(p, dict):
                raise ValueError(f"Profile '{key}' must be an object.")
            if key in builtin_p:
                raise ValueError(f"'{key}' is a built-in profile; give your own a different key.")
            custom_p[key] = inputs.check_profile({**p, "key": key})
        all_p, all_t = {**builtin_p, **custom_p}, {**builtin_t, **custom_t}
        if body.profile_key not in all_p:
            raise ValueError(f"There is no profile '{body.profile_key}'.")
        if body.template_key and body.template_key not in all_t:
            raise ValueError(f"There is no bank file layout '{body.template_key}'.")
        for p in custom_p.values():
            if p.get("bank_template") and p["bank_template"] not in all_t:
                raise ValueError(f"Profile '{p['key']}' names a bank file layout that does not exist.")
        config.build_settings("2026-01", body.overrides)     # refuses anything unknown or out of range
    except (ValueError, templates.TemplateError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    row = _settings_row(db, entity)
    before = _settings_out(db, entity, row) if row else None
    if row is None:
        row = DisbursementSettings(org_id=entity.org_id, entity_id=entity.id)
        db.add(row)
    row.profile_key, row.template_key = body.profile_key, body.template_key
    row.overrides, row.custom_profiles, row.custom_templates = body.overrides, custom_p, custom_t
    row.updated_by_email = user.email
    changed = [k for k in ("profile_key", "template_key", "overrides", "custom_profiles", "custom_templates")
               if before is None or before[k] != getattr(row, k)]
    audit.record(db, entity_id=entity.id, user=user, action="disbursement.settings_saved",
                 object_type="disbursement_settings", object_id=str(entity.id),
                 summary="Changed the salary payment file checks: " + (", ".join(changed) or "no change"),
                 detail={"changed": changed, "overrides": body.overrides, "profile_key": body.profile_key,
                         "template_key": body.template_key})
    db.commit()
    db.refresh(row)
    return ok(_settings_out(db, entity, row))


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
@router.post("/runs")
async def create_run(
    period: str = Form(...),
    value_date: str | None = Form(default=None),
    profile_key: str | None = Form(default=None),
    template_key: str | None = Form(default=None),
    use_previous_approved: bool = Form(default=True),
    bank_file: UploadFile = File(...),
    register_file: UploadFile = File(..., alias="register"),
    bank_master: UploadFile | None = File(default=None),
    change_log: UploadFile | None = File(default=None),
    previous: UploadFile | None = File(default=None),
    hold_list: UploadFile | None = File(default=None),
    offcycle: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """Check a payment file. Nothing is sent anywhere: the result and the clean file stay here."""
    month = _period(period)
    row = _settings_row(db, entity)
    profiles, tmpls = _profiles(row), _templates(row)
    profile_key = profile_key or (row.profile_key if row else "generic")
    if profile_key not in profiles:
        raise HTTPException(status_code=400, detail=f"There is no profile '{profile_key}'.")
    profile = profiles[profile_key]
    template_key = template_key or (row.template_key if row else None) or profile.get("bank_template")
    if template_key not in tmpls:
        raise HTTPException(status_code=400, detail=f"There is no bank file layout '{template_key}'.")
    when = None
    if value_date:
        try:
            when = date.fromisoformat(value_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="The value date must be a date as YYYY-MM-DD.")

    uploads = {"bank_file": bank_file, "register": register_file, "bank_master": bank_master,
               "change_log": change_log, "previous": previous, "hold_list": hold_list, "offcycle": offcycle}
    files: dict[str, tuple[str, bytes]] = {}
    for slot, up in uploads.items():
        if up is None or not (up.filename or "").strip():
            continue
        content = await up.read()
        if len(content) > MAX_FILE_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"The {inputs.LABEL[slot]} is larger than {MAX_FILE_MB} MB.")
        if not content:
            raise HTTPException(status_code=400, detail=f"The {inputs.LABEL[slot]} is empty.")
        files[slot] = (up.filename or f"{slot}.csv", content)

    clear_expired_files(db, entity.id)
    prior = prior_label = None
    prior_source = None
    if "previous" not in files and use_previous_approved:
        last = (month.replace(day=1) - timedelta(days=1)).replace(day=1)
        found = (db.query(DisbursementRun)
                 .filter(DisbursementRun.entity_id == entity.id, DisbursementRun.period_month == last,
                         DisbursementRun.status == "approved", DisbursementRun.paid_gz.isnot(None))
                 .order_by(DisbursementRun.created_at.desc()).first())
        if found is not None:
            prior = found
            prior_label = f"the approved check for {last:%b %Y}"
            paid_blob = found.paid_gz
            prior_source = {"filename": f"Approved check for {last:%b %Y}",
                            "sha256": hashlib.sha256(paid_blob).hexdigest(), "run_id": str(found.id)}

    try:
        settings = config.build_settings(month.strftime("%Y-%m"), (row.overrides if row else None) or {}, when)
        checked = run_check(
            files, profile, tmpls[template_key], settings,
            {"period": month.strftime("%Y-%m"), "entity_name": entity.name, "run_by": user.email,
             "generated_at": _now().replace(microsecond=0).isoformat()},
            previous=previous_from_paid(_ungz(prior.paid_gz), prior_label) if prior else None,
            previous_source=prior_source,
        )
    except (ValueError, templates.TemplateError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    report = checked.report
    report_gz = _gz(report)
    run = DisbursementRun(
        org_id=entity.org_id, entity_id=entity.id, period_month=month, value_date=when,
        verdict=checked.result.verdict, status="checked", profile_key=profile_key, template_key=template_key,
        bank_filename=files["bank_file"][0], totals=report["totals"],
        rule_status={r.rule_id: r.status for r in checked.result.rules},
        report_gz=report_gz, report_sha256=hashlib.sha256(report_gz).hexdigest(),
        clean_file=checked.clean, clean_filename=checked.clean_filename,
        clean_sha256=report["clean_sha256"], clean_bytes=len(checked.clean) if checked.clean is not None else None,
        paid_gz=_gz(checked.paid) if checked.clean is not None else None,
        files_expire_at=_now() + timedelta(days=app_settings.disbursement_file_retention_days),
        previous_run_id=prior.id if prior else None,
        run_by_user_id=user.id, run_by_email=user.email,
    )
    db.add(run)
    db.flush()
    totals = report["totals"]
    audit.record(
        db, entity_id=entity.id, user=user, action="disbursement.checked", object_type="disbursement_run",
        object_id=str(run.id),
        summary=f"Checked salary payment file {run.bank_filename} for {month:%b %Y}: {run.verdict} — "
                f"{totals['release_employees']} to pay, {totals['held_employees']} held",
        detail={"verdict": run.verdict, "clean_sha256": run.clean_sha256,
                "inputs": [{k: i.get(k) for k in ("slot", "filename", "sha256", "rows")} for i in report["inputs"]],
                "unchecked": _unchecked(run)},
    )
    db.commit()
    db.refresh(run)
    return ok(_run_out(db, run))


@router.get("/runs")
def list_runs(
    period: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """History. The headline figures only — no bank details."""
    query = db.query(DisbursementRun).filter(DisbursementRun.entity_id == entity.id)
    if period:
        query = query.filter(DisbursementRun.period_month == _period(period))
    runs = query.order_by(DisbursementRun.created_at.desc()).limit(limit).all()
    approved = {a.run_id: a for a in db.query(DisbursementApproval)
                .filter(DisbursementApproval.run_id.in_([r.id for r in runs]))} if runs else {}
    return ok({"runs": [_run_out(db, r, approved.get(r.id)) for r in runs]})


@router.get("/runs/{run_id}")
def get_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """The full report: findings, bridge, notes, settings. Shows bank details in full."""
    run = _load_run(db, entity, run_id)
    report = _ungz(run.report_gz)
    out = _run_out(db, run, _approval(db, run))
    out["report"] = report
    out["held"] = [{**h, "amount": str(h["amount"])} for h in outputs.held_employees(report)]
    newer = _newer_run(db, run)
    out["superseded_by"] = str(newer.id) if newer else None
    policy = approvals.policy_for(db, entity.org_id)
    out["independence_required"] = bool(policy.get(POLICY))
    out["can_approve"] = tenancy.role_at_least(db, user, "manager", entity)
    return ok(out)


DOWNLOADS = ("clean", "exceptions.csv", "exceptions.xlsx", "summary.pdf")


@router.get("/runs/{run_id}/download/{kind}")
def download(
    run_id: uuid.UUID,
    kind: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    if kind not in DOWNLOADS:
        raise HTTPException(status_code=404, detail="No such download")
    run = _load_run(db, entity, run_id)
    stem = f"payment_check_{run.period_month:%Y-%m}"
    if kind == "clean":
        if run.verdict == config.DO_NOT_RELEASE:
            raise HTTPException(status_code=409, detail="This file must not be released, so there is no clean file.")
        if run.clean_file is None:
            raise HTTPException(status_code=410, detail="The clean file has been cleared after "
                                f"{app_settings.disbursement_file_retention_days} days. Check the file again.")
        if hashlib.sha256(run.clean_file).hexdigest() != run.clean_sha256:
            raise HTTPException(status_code=500, detail="The stored clean file does not match its fingerprint. "
                                                        "Do not release it; check the file again.")
        content, filename = run.clean_file, run.clean_filename or f"{stem}_clean.csv"
        media = MEDIA.get("." + filename.rsplit(".", 1)[-1].lower(), "application/octet-stream")
    else:
        report = _ungz(run.report_gz)
        if kind == "exceptions.csv":
            content, filename, media = outputs.exception_csv(report), f"{stem}_exceptions.csv", "text/csv"
        elif kind == "exceptions.xlsx":
            content, filename, media = outputs.exception_xlsx(report), f"{stem}_exceptions.xlsx", MEDIA[".xlsx"]
        else:
            approval = _approval_out(_approval(db, run))
            try:
                content = outputs.approver_pdf(report, approval)
            except ValueError as exc:
                raise HTTPException(status_code=503, detail=str(exc))
            filename, media = f"{stem}_approver_summary.pdf", "application/pdf"
    audit.record(db, entity_id=entity.id, user=user, action="disbursement.downloaded",
                 object_type="disbursement_run", object_id=str(run.id),
                 summary=f"Downloaded {filename} ({run.period_month:%b %Y})",
                 detail={"kind": kind, "sha256": hashlib.sha256(content).hexdigest()})
    db.commit()
    return _file(content, filename, media)


class ApproveBody(BaseModel):
    approver_name: str = Field(min_length=2, max_length=120)
    fingerprint: str = Field(min_length=64, max_length=64)
    acknowledged: list[str] = Field(default_factory=list)
    comment: str | None = Field(default=None, max_length=2000)


@router.post("/runs/{run_id}/approve")
def approve(
    run_id: uuid.UUID,
    body: ApproveBody,
    db: Session = Depends(get_db),
    user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    """
    Record a person's approval to release this clean file. It sends nothing:
    someone still uploads the file to the bank.
    """
    run = _load_run(db, entity, run_id)
    if _approval(db, run) is not None or run.status == "approved":
        raise HTTPException(status_code=409, detail="This check is already approved.")
    if run.verdict == config.DO_NOT_RELEASE:
        raise HTTPException(status_code=409, detail="This file must not be released. Fix the cause and check again.")
    if _newer_run(db, run) is not None:
        raise HTTPException(status_code=409, detail="A newer check of this month exists. Approve that one.")
    if run.clean_file is None:
        raise HTTPException(status_code=410, detail="The clean file has been cleared. Check the file again.")
    if body.fingerprint.lower() != (run.clean_sha256 or ""):
        raise HTTPException(status_code=409, detail="The fingerprint does not match this check's clean file. "
                                                    "Reload the page: you may be looking at a different file.")
    unchecked = _unchecked(run)
    missing = sorted(set(unchecked) - set(body.acknowledged))
    if missing:
        raise HTTPException(status_code=400, detail="These checks did not run and must be acknowledged before "
                                                    "approving: " + ", ".join(missing))
    required = bool(approvals.policy_for(db, entity.org_id).get(POLICY))
    try:
        approvals.require_independent(db, entity.org_id, POLICY, preparer_id=run.run_by_user_id,
                                      approver_id=user.id, what="a salary payment file")
    except approvals.ApprovalRefused as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    approval = DisbursementApproval(
        run_id=run.id, org_id=entity.org_id, entity_id=entity.id, approver_user_id=user.id,
        approver_email=user.email, approver_name=body.approver_name.strip(),
        approver_role=tenancy.effective_entity_role(db, user, entity),
        fingerprint=run.clean_sha256, verdict=run.verdict,
        release_amount=str(run.totals.get("release_amount")), release_employees=int(run.totals.get("release_employees") or 0),
        acknowledged=sorted(set(body.acknowledged) & set(unchecked)),
        independent=run.run_by_user_id != user.id, independence_required=required,
        comment=(body.comment or "").strip() or None, approved_at=_now(),
    )
    run.status = "approved"
    db.add(approval)
    amount = Decimal(str(run.totals.get("release_amount") or "0"))
    audit.record(
        db, entity_id=entity.id, user=user, action="disbursement.approved", object_type="disbursement_run",
        object_id=str(run.id),
        summary=f"Approved release of {run.clean_filename} for {run.period_month:%b %Y}: "
                f"₹{amount:,.2f} to {approval.release_employees} employees",
        detail={"fingerprint": run.clean_sha256, "acknowledged": approval.acknowledged,
                "independent": approval.independent, "independence_required": required,
                "approver_name": approval.approver_name},
    )
    db.commit()
    return ok(_run_out(db, run, approval))
