"""
Point-in-time access to employee master and attendance.

Validation of an old month must read that month's version of the truth. If
someone exits in June, a re-run of April's register must not suddenly report
everyone as paid-after-exit, so lookups here take an ``as_of`` date and resolve
each employee to the latest master version effective on or before it.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models import AttendanceRow, EmployeeRecord


def master_as_of(
    db: Session, entity_id: uuid.UUID, as_of: date
) -> dict[str, EmployeeRecord]:
    """
    The master as it stood on ``as_of``, keyed by employee id.

    Rows arrive oldest-first so that later versions overwrite earlier ones,
    leaving the newest version effective on or before the cutoff.
    """
    rows = (
        db.query(EmployeeRecord)
        .filter(
            EmployeeRecord.entity_id == entity_id,
            EmployeeRecord.effective_from <= as_of,
        )
        .order_by(EmployeeRecord.employee_id, EmployeeRecord.effective_from)
        .all()
    )
    resolved: dict[str, EmployeeRecord] = {}
    for row in rows:
        resolved[row.employee_id] = row
    return resolved


def attendance_for_period(
    db: Session, entity_id: uuid.UUID, period_month: date
) -> dict[str, AttendanceRow]:
    """Attendance rows for one month, keyed by employee id."""
    rows = (
        db.query(AttendanceRow)
        .filter(
            AttendanceRow.entity_id == entity_id,
            AttendanceRow.period_month == period_month.replace(day=1),
        )
        .all()
    )
    return {row.employee_id: row for row in rows}


def service_years(joined: date | None, as_of: date) -> float | None:
    """
    Completed years of service, for gratuity eligibility.

    Returns None when the joining date is unknown, so callers can tell "not
    eligible" apart from "cannot say" — a distinction that matters when the
    answer drives a payment.
    """
    if joined is None or joined > as_of:
        return None
    years = as_of.year - joined.year
    if (as_of.month, as_of.day) < (joined.month, joined.day):
        years -= 1
    # Retain the part-year, which the 4-years-240-days line of cases turns on.
    anniversary = date(joined.year + years, joined.month, min(joined.day, 28))
    fraction = (as_of - anniversary).days / 365.25
    return round(years + fraction, 3)
