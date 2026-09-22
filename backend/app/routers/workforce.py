"""
Employee master and attendance ingestion.

Both follow the same two-step shape as the existing CTC flow: upload to preview
how the headers were read, then commit. The preview matters more here than
elsewhere — a master file whose "Date of Leaving" column went unrecognised would
silently disable every exit-related check.
"""
from __future__ import annotations

import calendar
import json
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write
from app.envelope import ok
from app.models import (
    AttendanceRegister,
    AttendanceRow,
    EmployeeMasterUpload,
    EmployeeRecord,
    Entity,
    User,
)
from app.schemas.workforce import (
    AttendanceRegisterOut,
    AttendanceRowOut,
    EmployeeMasterUploadOut,
    EmployeeRecordOut,
    ParsePreview,
)
from app.services import attendance_rules
from app.services.config_service import ConfigService
from app.services.payroll_parse import parse_payroll_file
from app.services.workforce_parse import (
    derive_attendance_gaps,
    parse_attendance,
    parse_employee_master,
)

router = APIRouter()

# Fields copied straight from a parsed record onto an EmployeeRecord.
MASTER_FIELDS = (
    "employee_name", "date_of_joining", "date_of_exit", "date_of_birth",
    "gender", "work_state", "work_location", "department", "designation",
    "grade", "business_unit", "cost_center", "employment_type", "skill_category", "pf_restricted",
    "pan", "aadhaar", "uan", "pf_number", "esic_ip_number", "bank_account", "ifsc",
)

ATTENDANCE_FIELDS = (
    "employee_name", "calendar_days", "present_days", "paid_days", "lop_days",
    "paid_leave_days", "weekly_off_days", "holiday_days", "overtime_hours",
)


def _month_start(value: str | None, field: str) -> date:
    if not value:
        raise HTTPException(status_code=400, detail=f"'{field}' is required")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"'{field}' must be an ISO date (YYYY-MM-DD)")
    return parsed.replace(day=1)


def _meta(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid meta JSON")


def _preview(records: list[dict], header_map: dict, unmapped: list[str], warnings: list[str]) -> dict:
    return ParsePreview(
        row_count=len(records),
        header_map={str(k): v for k, v in header_map.items()},
        unmapped_columns=[str(c) for c in unmapped],
        warnings=warnings,
        sample=[
            {k: (str(v) if isinstance(v, (date, Decimal)) else v) for k, v in r.items()}
            for r in records[:5]
        ],
    ).model_dump()


# ---------------------------------------------------------------------------
# Employee master
# ---------------------------------------------------------------------------
@router.post("/master/upload")
async def upload_master(
    file: UploadFile = File(...),
    meta: str = Form("{}"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """Parse a master file and report how it was read, without storing anything."""
    raw = await file.read()
    try:
        df = parse_payroll_file(raw, file.filename or "master.csv")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    records, header_map, unmapped = parse_employee_master(df)

    warnings: list[str] = []
    if not records:
        warnings.append("No rows with an employee id were found.")
    if "date_of_joining" not in header_map.values():
        warnings.append(
            "No joining-date column recognised — joined/exited checks and gratuity "
            "service years cannot be validated without it."
        )
    if "work_state" not in header_map.values():
        warnings.append(
            "No work-state column recognised — PT and LWF will fall back to the entity's state."
        )
    return ok(_preview(records, header_map, unmapped, warnings))


@router.post("/master/commit")
async def commit_master(
    file: UploadFile = File(...),
    meta: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    effective_from = _month_start(_meta(meta).get("effective_from"), "effective_from")

    raw = await file.read()
    try:
        df = parse_payroll_file(raw, file.filename or "master.csv")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    records, _, _ = parse_employee_master(df)
    if not records:
        raise HTTPException(status_code=400, detail="No rows with an employee id were found.")

    # Re-uploading the same effective date replaces that version rather than
    # colliding with it, so a corrected file can simply be sent again.
    existing = (
        db.query(EmployeeMasterUpload)
        .filter(
            EmployeeMasterUpload.entity_id == entity.id,
            EmployeeMasterUpload.effective_from == effective_from,
        )
        .all()
    )
    for stale in existing:
        db.delete(stale)
    db.flush()

    upload = EmployeeMasterUpload(
        user_id=user.id,
        entity_id=entity.id,
        effective_from=effective_from,
        filename=file.filename,
        employee_count=len(records),
    )
    db.add(upload)
    db.flush()

    seen: set[str] = set()
    for record in records:
        employee_id = record["employee_id"]
        if employee_id in seen:
            continue  # first row wins; duplicates are reported by validation
        seen.add(employee_id)
        db.add(
            EmployeeRecord(
                upload_id=upload.id,
                user_id=user.id,
                entity_id=entity.id,
                employee_id=employee_id,
                effective_from=effective_from,
                extra=record.get("extra", {}),
                **{f: record.get(f) for f in MASTER_FIELDS},
            )
        )

    db.commit()
    db.refresh(upload)
    return ok(EmployeeMasterUploadOut.model_validate(upload).model_dump(mode="json"))


@router.get("/master/uploads")
def list_master_uploads(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    rows = (
        db.query(EmployeeMasterUpload)
        .filter(EmployeeMasterUpload.entity_id == entity.id)
        .order_by(EmployeeMasterUpload.effective_from.desc())
        .all()
    )
    return ok([EmployeeMasterUploadOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.get("/master")
def list_master_records(
    as_of: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """The master as it stood on ``as_of`` (default: today)."""
    from app.services.workforce import master_as_of

    cutoff = date.fromisoformat(as_of) if as_of else date.today()
    records = master_as_of(db, entity.id, cutoff)
    return ok(
        [EmployeeRecordOut.model_validate(r).model_dump(mode="json") for r in records.values()]
    )


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------
@router.post("/attendance/upload")
async def upload_attendance(
    file: UploadFile = File(...),
    meta: str = Form("{}"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    raw = await file.read()
    try:
        df = parse_payroll_file(raw, file.filename or "attendance.csv")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    records, header_map, unmapped = parse_attendance(df)

    warnings: list[str] = []
    if not records:
        warnings.append("No rows with an employee id were found.")
    recognised = set(header_map.values())
    if not recognised & {"paid_days", "lop_days", "present_days"}:
        warnings.append(
            "No paid-days, LOP or present-days column recognised — attendance "
            "cannot be compared against the salary register."
        )
    return ok(_preview(records, header_map, unmapped, warnings))


@router.post("/attendance/validate")
async def validate_attendance(
    file: UploadFile = File(...),
    meta: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """
    Check an attendance file against itself, storing nothing.

    Run before committing, because an attendance file that does not add up is
    not a file anyone can reconcile payroll against — and finding that out
    first costs nothing, while finding it out after a payroll run costs a
    correction cycle.

    Deliberately reads the file as uploaded rather than after the gaps are
    filled in. Once paid days have been derived from loss of pay the two can
    never disagree, so a check run afterwards would pass every file including
    the ones that stated both figures and contradicted themselves.
    """
    period_month = _month_start(_meta(meta).get("period_month"), "period_month")

    raw = await file.read()
    try:
        df = parse_payroll_file(raw, file.filename or "attendance.csv")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    records, header_map, unmapped = parse_attendance(df)
    if not records:
        raise HTTPException(status_code=400, detail="No rows with an employee id were found.")

    thresholds = ConfigService(db).get_rule_thresholds(entity.id)
    cfg = getattr(thresholds, "attendance", None)
    findings = attendance_rules.check_self_consistency(
        records, period_month,
        day_tolerance=getattr(cfg, "day_tolerance", Decimal("0.05")),
        require_days_reconcile=bool(getattr(cfg, "require_days_reconcile", True)),
    )

    by_severity: dict[str, int] = {}
    for finding in findings:
        by_severity[finding["severity"]] = by_severity.get(finding["severity"], 0) + 1

    return ok({
        "period_month": period_month.isoformat(),
        "filename": file.filename,
        "row_count": len(records),
        "employees": len({str(r.get("employee_id") or "").strip() for r in records if r.get("employee_id")}),
        "recognised_columns": sorted(set(header_map.values())),
        "unmapped_columns": unmapped,
        "paid_days_basis": getattr(cfg, "paid_days_basis", "calendar"),
        "counts": {"total": len(findings), "by_severity": by_severity},
        "findings": findings,
        "clean": not findings,
    })


@router.get("/attendance/bases")
def attendance_bases():
    """
    The bases a monthly wage can be divided by to get a daily rate.

    The choice changes money: the same two days of loss of pay deduct three
    different amounts under the three options, so it is configuration rather
    than a constant.
    """
    return ok({"bases": attendance_rules.basis_catalogue()})


@router.post("/attendance/commit")
async def commit_attendance(
    file: UploadFile = File(...),
    meta: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    period_month = _month_start(_meta(meta).get("period_month"), "period_month")
    calendar_days = Decimal(calendar.monthrange(period_month.year, period_month.month)[1])

    raw = await file.read()
    try:
        df = parse_payroll_file(raw, file.filename or "attendance.csv")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    records, _, _ = parse_attendance(df)
    if not records:
        raise HTTPException(status_code=400, detail="No rows with an employee id were found.")

    register = (
        db.query(AttendanceRegister)
        .filter(
            AttendanceRegister.entity_id == entity.id,
            AttendanceRegister.period_month == period_month,
        )
        .first()
    )
    if register is not None:
        db.delete(register)
        db.flush()

    register = AttendanceRegister(
        user_id=user.id,
        entity_id=entity.id,
        period_month=period_month,
        filename=file.filename,
        employee_count=len(records),
    )
    db.add(register)
    db.flush()

    thresholds = ConfigService(db).get_rule_thresholds(entity.id)
    cfg = getattr(thresholds, "attendance", None)
    # Checked on the records as uploaded. Only the first row per employee is
    # stored below, and an operator who is not told which rows were dropped
    # cannot know whether the days that got paid were the days worked.
    problems = attendance_rules.check_self_consistency(
        records, period_month,
        day_tolerance=getattr(cfg, "day_tolerance", Decimal("0.05")),
        require_days_reconcile=bool(getattr(cfg, "require_days_reconcile", True)),
    )

    seen: set[str] = set()
    for record in records:
        employee_id = record["employee_id"]
        if employee_id in seen:
            continue
        seen.add(employee_id)
        filled = derive_attendance_gaps(record, calendar_days)
        db.add(
            AttendanceRow(
                register_id=register.id,
                user_id=user.id,
                entity_id=entity.id,
                period_month=period_month,
                employee_id=employee_id,
                extra=record.get("extra", {}),
                **{f: filled.get(f) for f in ATTENDANCE_FIELDS},
            )
        )

    db.commit()
    db.refresh(register)
    payload = AttendanceRegisterOut.model_validate(register).model_dump(mode="json")
    payload["problems"] = problems
    payload["rows_read"] = len(records)
    payload["rows_stored"] = len(seen)
    return ok(payload)


@router.get("/attendance")
def list_attendance_registers(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    rows = (
        db.query(AttendanceRegister)
        .filter(AttendanceRegister.entity_id == entity.id)
        .order_by(AttendanceRegister.period_month.desc())
        .all()
    )
    return ok([AttendanceRegisterOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.get("/attendance/{register_id}")
def get_attendance_register(
    register_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    register = db.get(AttendanceRegister, register_id)
    if register is None or register.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Attendance register not found")
    rows = (
        db.query(AttendanceRow)
        .filter(AttendanceRow.register_id == register.id)
        .order_by(AttendanceRow.employee_id)
        .all()
    )
    return ok(
        {
            "register": AttendanceRegisterOut.model_validate(register).model_dump(mode="json"),
            "rows": [AttendanceRowOut.model_validate(r).model_dump(mode="json") for r in rows],
        }
    )
