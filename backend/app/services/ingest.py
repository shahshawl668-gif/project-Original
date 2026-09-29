"""
Committing parsed employee-master, attendance and CTC records.

One implementation for every way data arrives: the upload screens, the
integration API and, later, a connector's sync. Before this lived in three
routers, each with its own idea of what a duplicate was, and an API written
beside them would have been a fourth.

Two modes:

* **replace** — the version at that date (the master effective date, the
  attendance month) becomes exactly this batch. What the upload screens always
  did: a corrected file simply replaces the one before it.
* **upsert** — records are matched on employee id and updated or added; people
  the batch does not mention are left alone. What an integration sends: a
  retry of the rejected rows must not delete everyone who was accepted the
  first time.

Every call returns counts — created, updated, unchanged, removed — so the
caller can reconcile what it sent against what was stored. A duplicate employee
id in one batch is never silently dropped: it is returned in ``duplicates`` and
the caller decides how to report it.

``lineage`` is written on every stored record: the run, source system and
object, the source record id and the import time. It is provenance, not data,
so it is excluded from the input digests a validation run is fingerprinted on.
"""
from __future__ import annotations

import calendar
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    AttendanceRegister,
    AttendanceRow,
    CtcRecord,
    CtcUpload,
    EmployeeMasterUpload,
    EmployeeRecord,
    Entity,
    User,
)
from app.services.workforce_parse import derive_attendance_gaps

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

MODES = ("replace", "upsert")


def _counts() -> dict[str, int]:
    return {"created": 0, "updated": 0, "unchanged": 0, "removed": 0}


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        try:
            return Decimal(str(a)) == Decimal(str(b)) if a is not None and b is not None else a is b
        except Exception:  # noqa: BLE001
            return False
    return a == b


def _lineage(base: dict[str, Any] | None, record: dict[str, Any]) -> dict[str, Any] | None:
    if base is None:
        return None
    out = dict(base)
    ref = record.get("_source_ref") or {}
    if ref.get("record_id") is not None:
        out["record_id"] = str(ref["record_id"])
    if record.get("_row") is not None:
        out["row"] = record["_row"]
    return out


def _first_wins(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = str(record["employee_id"])
        if key in seen:
            duplicates.append(record)
            continue
        seen.add(key)
        kept.append(record)
    return kept, duplicates


def month_start(value: date) -> date:
    return value.replace(day=1)


# ---------------------------------------------------------------------------
# Employee master
# ---------------------------------------------------------------------------
def commit_master(
    db: Session,
    *,
    entity: Entity,
    user: User,
    effective_from: date,
    records: list[dict[str, Any]],
    filename: str | None,
    mode: str = "replace",
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store one version of the master. Does not commit."""
    effective_from = month_start(effective_from)
    kept, duplicates = _first_wins(records)
    counts = _counts()

    existing = (
        db.query(EmployeeMasterUpload)
        .filter(EmployeeMasterUpload.entity_id == entity.id,
                EmployeeMasterUpload.effective_from == effective_from)
        .order_by(EmployeeMasterUpload.created_at.desc())
        .all()
    )

    if mode == "replace" or not existing:
        previous = {
            r.employee_id
            for u in existing
            for r in db.query(EmployeeRecord.employee_id).filter(EmployeeRecord.upload_id == u.id)
        }
        for stale in existing:
            db.delete(stale)
        db.flush()
        upload = EmployeeMasterUpload(
            user_id=user.id, entity_id=entity.id, effective_from=effective_from,
            filename=filename, employee_count=len(kept),
        )
        db.add(upload)
        db.flush()
        for record in kept:
            db.add(EmployeeRecord(
                upload_id=upload.id, user_id=user.id, entity_id=entity.id,
                employee_id=record["employee_id"], effective_from=effective_from,
                extra=record.get("extra", {}), lineage=_lineage(lineage, record),
                **{f: record.get(f) for f in MASTER_FIELDS},
            ))
            if record["employee_id"] in previous:
                counts["updated"] += 1
            else:
                counts["created"] += 1
        counts["removed"] = len(previous - {r["employee_id"] for r in kept})
        return {"upload": upload, "counts": counts, "duplicates": duplicates}

    upload = existing[0]
    for extra_upload in existing[1:]:
        db.delete(extra_upload)
    stored = {
        r.employee_id: r
        for r in db.query(EmployeeRecord).filter(EmployeeRecord.upload_id == upload.id)
    }
    for record in kept:
        row = stored.get(record["employee_id"])
        values = {f: record.get(f) for f in MASTER_FIELDS}
        if row is None:
            db.add(EmployeeRecord(
                upload_id=upload.id, user_id=user.id, entity_id=entity.id,
                employee_id=record["employee_id"], effective_from=effective_from,
                extra=record.get("extra", {}), lineage=_lineage(lineage, record), **values,
            ))
            counts["created"] += 1
            continue
        changed = any(not _same(getattr(row, f), v) for f, v in values.items()) or (
            (row.extra or {}) != (record.get("extra") or {})
        )
        if not changed:
            counts["unchanged"] += 1
            continue
        for f, v in values.items():
            setattr(row, f, v)
        row.extra = record.get("extra", {})
        row.lineage = _lineage(lineage, record)
        row.user_id = user.id
        counts["updated"] += 1
    upload.employee_count = len(stored) + counts["created"]
    upload.filename = filename or upload.filename
    return {"upload": upload, "counts": counts, "duplicates": duplicates}


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------
def commit_attendance(
    db: Session,
    *,
    entity: Entity,
    user: User,
    period_month: date,
    records: list[dict[str, Any]],
    filename: str | None,
    mode: str = "replace",
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store a month's attendance. Does not commit."""
    period_month = month_start(period_month)
    calendar_days = Decimal(calendar.monthrange(period_month.year, period_month.month)[1])
    kept, duplicates = _first_wins(records)
    counts = _counts()

    register = (
        db.query(AttendanceRegister)
        .filter(AttendanceRegister.entity_id == entity.id,
                AttendanceRegister.period_month == period_month)
        .first()
    )
    if mode == "replace" or register is None:
        previous: set[str] = set()
        if register is not None:
            previous = {
                eid for (eid,) in
                db.query(AttendanceRow.employee_id).filter(AttendanceRow.register_id == register.id)
            }
            db.delete(register)
            db.flush()
        register = AttendanceRegister(
            user_id=user.id, entity_id=entity.id, period_month=period_month,
            filename=filename, employee_count=len(kept),
        )
        db.add(register)
        db.flush()
        for record in kept:
            filled = derive_attendance_gaps(record, calendar_days)
            db.add(AttendanceRow(
                register_id=register.id, user_id=user.id, entity_id=entity.id,
                period_month=period_month, employee_id=record["employee_id"],
                extra=record.get("extra", {}), lineage=_lineage(lineage, record),
                **{f: filled.get(f) for f in ATTENDANCE_FIELDS},
            ))
            counts["updated" if record["employee_id"] in previous else "created"] += 1
        counts["removed"] = len(previous - {r["employee_id"] for r in kept})
        return {"register": register, "counts": counts, "duplicates": duplicates}

    stored = {
        r.employee_id: r
        for r in db.query(AttendanceRow).filter(AttendanceRow.register_id == register.id)
    }
    for record in kept:
        filled = derive_attendance_gaps(record, calendar_days)
        values = {f: filled.get(f) for f in ATTENDANCE_FIELDS}
        row = stored.get(record["employee_id"])
        if row is None:
            db.add(AttendanceRow(
                register_id=register.id, user_id=user.id, entity_id=entity.id,
                period_month=period_month, employee_id=record["employee_id"],
                extra=record.get("extra", {}), lineage=_lineage(lineage, record), **values,
            ))
            counts["created"] += 1
            continue
        if all(_same(getattr(row, f), v) for f, v in values.items()) and (row.extra or {}) == (record.get("extra") or {}):
            counts["unchanged"] += 1
            continue
        for f, v in values.items():
            setattr(row, f, v)
        row.extra = record.get("extra", {})
        row.lineage = _lineage(lineage, record)
        counts["updated"] += 1
    register.employee_count = len(stored) + counts["created"]
    return {"register": register, "counts": counts, "duplicates": duplicates}


# ---------------------------------------------------------------------------
# CTC
# ---------------------------------------------------------------------------
def commit_ctc(
    db: Session,
    *,
    entity: Entity,
    user: User,
    records: list[dict[str, Any]],
    filename: str | None,
    default_effective_from: date | None = None,
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Store CTC records, each at its own effective date. Does not commit.

    Always an upsert on (employee, effective date): a revision is a new dated
    record, history is never overwritten by a later effective date, and
    re-sending the same dated record updates it in place.
    """
    counts = _counts()
    seen: set[tuple[str, date]] = set()
    duplicates: list[dict[str, Any]] = []
    eff = default_effective_from or min(_as_date(r["effective_from"]) for r in records)
    upload = CtcUpload(
        user_id=user.id, entity_id=entity.id, effective_from=eff,
        filename=filename, employee_count=len(records),
    )
    db.add(upload)
    db.flush()
    # Everything already stored for these people, read once — not one query
    # per record, which at 16,000 records was most of the import's time.
    ids = sorted({str(r["employee_id"]) for r in records})
    stored: dict[tuple[str, date], CtcRecord] = {}
    for start in range(0, len(ids), 1000):
        for row in db.query(CtcRecord).filter(CtcRecord.entity_id == entity.id,
                                              CtcRecord.employee_id.in_(ids[start:start + 1000])):
            stored[(row.employee_id, row.effective_from)] = row
    for record in records:
        effective = _as_date(record["effective_from"])
        key = (str(record["employee_id"]), effective)
        if key in seen:
            duplicates.append(record)
            continue
        seen.add(key)
        existing = stored.get(key)
        components = {k: float(v) for k, v in (record.get("annual_components") or {}).items()}
        annual = record.get("annual_ctc")
        if existing is not None:
            if (existing.annual_components or {}) == components and _same(existing.annual_ctc, annual) \
                    and existing.employee_name == record.get("employee_name"):
                counts["unchanged"] += 1
                continue
            existing.upload_id = upload.id
            existing.employee_name = record.get("employee_name")
            existing.annual_components = components
            existing.annual_ctc = annual
            existing.lineage = _lineage(lineage, record)
            counts["updated"] += 1
            continue
        db.add(CtcRecord(
            upload_id=upload.id, user_id=user.id, entity_id=entity.id,
            employee_id=record["employee_id"], employee_name=record.get("employee_name"),
            effective_from=effective, annual_components=components, annual_ctc=annual,
            lineage=_lineage(lineage, record),
        ))
        counts["created"] += 1
    upload.employee_count = len(seen)
    return {"upload": upload, "counts": counts, "duplicates": duplicates}


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def file_lineage(filename: str | None, *, actor: str) -> dict[str, Any]:
    """Lineage for a file uploaded on screen."""
    return {
        "channel": "upload",
        "source_object": filename,
        "imported_by": actor,
        "imported_at": datetime.now(UTC).isoformat(),
    }


def new_batch_id() -> str:
    return uuid.uuid4().hex[:16]
