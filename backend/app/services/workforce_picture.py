"""
The employee master, one month's attendance and the audit trail, counted for drawing.

Same rule as the run picture: every figure is a count over all the rows, made
here, so a chart cannot disagree with the list under it. A value nobody
recorded is counted as "not recorded" — never folded into another group and
never left out, because a master with no department for half its people must
not look like a company with one department.
"""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import AttendanceRegister, AttendanceRow, AuditEvent
from app.services.clock import india_today
from app.services.workforce import master_as_of

GROUP_ROWS = 12
# What validation reads from the master, and so what an empty field switches off.
MASTER_FIELDS: tuple[tuple[str, str], ...] = (
    ("date_of_joining", "Date of joining"),
    ("gender", "Gender"),
    ("work_state", "Work state"),
    ("department", "Department"),
    ("employment_type", "Employment type"),
    ("pan", "PAN"),
    ("uan", "UAN"),
    ("bank_account", "Bank account"),
)
LOP_BANDS: tuple[tuple[str, Decimal, Decimal | None], ...] = (
    ("None", Decimal("0"), Decimal("0")),
    ("Up to 1 day", Decimal("0"), Decimal("1")),
    ("1 to 3 days", Decimal("1"), Decimal("3")),
    ("3 to 5 days", Decimal("3"), Decimal("5")),
    ("More than 5", Decimal("5"), None),
)


def _grouped(values: list[str | None]) -> dict[str, Any]:
    named = Counter(v.strip() for v in values if v and v.strip())
    ordered = sorted(named.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "items": [{"name": name, "employees": n} for name, n in ordered[:GROUP_ROWS]],
        "not_shown": max(0, len(ordered) - GROUP_ROWS),
        "not_shown_employees": sum(n for _, n in ordered[GROUP_ROWS:]),
        "not_recorded": len(values) - sum(named.values()),
    }


def master_picture(db: Session, entity_id: uuid.UUID, as_of: date | None = None) -> dict[str, Any]:
    today = as_of or india_today()
    records = list(master_as_of(db, entity_id, today).values())
    left = [r for r in records if r.date_of_exit is not None and r.date_of_exit < today]
    by_year = Counter(r.date_of_joining.year for r in records if r.date_of_joining)
    return {
        "as_of": today.isoformat(),
        "employees": len(records),
        "active": len(records) - len(left),
        "left": len(left),
        "by_state": _grouped([r.work_state for r in records]),
        "by_department": _grouped([r.department for r in records]),
        "by_gender": _grouped([r.gender for r in records]),
        "by_employment_type": _grouped([r.employment_type for r in records]),
        "joined_by_year": {
            "items": [{"year": y, "employees": by_year[y]} for y in sorted(by_year)],
            "not_recorded": sum(1 for r in records if not r.date_of_joining),
        },
        "fields": [
            {"field": key, "label": label,
             "recorded": sum(1 for r in records if getattr(r, key) not in (None, ""))}
            for key, label in MASTER_FIELDS
        ],
    }


def _band(lop: Decimal) -> str:
    if lop == 0:
        return LOP_BANDS[0][0]
    for label, low, high in LOP_BANDS[1:]:
        if lop > low and (high is None or lop <= high):
            return label
    return LOP_BANDS[-1][0]


def attendance_picture(db: Session, register: AttendanceRegister) -> dict[str, Any]:
    rows = db.query(AttendanceRow).filter(AttendanceRow.register_id == register.id).all()

    def total(column: str) -> dict[str, Any]:
        stated = [getattr(r, column) for r in rows if getattr(r, column) is not None]
        # A column the file never carried is "not recorded", not a total of zero.
        return {"total": float(sum(stated, Decimal("0"))) if stated else None, "employees_stated": len(stated)}

    lop_stated = [r.lop_days for r in rows if r.lop_days is not None]
    bands = Counter(_band(Decimal(v)) for v in lop_stated)
    return {
        "register_id": str(register.id),
        "period_month": register.period_month.isoformat(),
        "employees": len(rows),
        "days": {key: total(key) for key in ("present_days", "paid_days", "lop_days", "paid_leave_days",
                                             "weekly_off_days", "holiday_days")},
        "overtime_hours": total("overtime_hours"),
        "with_overtime": sum(1 for r in rows if r.overtime_hours is not None and r.overtime_hours > 0),
        "lop_bands": {
            "items": [{"label": label, "employees": bands.get(label, 0)} for label, _, _ in LOP_BANDS],
            "not_recorded": len(rows) - len(lop_stated),
        },
    }


def audit_picture(db: Session, entity_id: uuid.UUID, org_id: uuid.UUID | None, days: int = 30) -> dict[str, Any]:
    """Entries per India calendar day and per action, over the last ``days`` days — same scope as the trail."""
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")
    today = india_today()
    first = today - timedelta(days=days - 1)
    scope = AuditEvent.entity_id == entity_id
    if org_id is not None:
        scope = or_(scope, AuditEvent.org_id == org_id)
    total = db.query(func.count(AuditEvent.id)).filter(scope).scalar() or 0
    # Bucketed in Python: "which day" is a question about India's calendar, and
    # the two databases this runs on disagree about time zones in SQL.
    from datetime import UTC, datetime, time

    since = datetime.combine(first, time.min, tzinfo=ist).astimezone(UTC)
    recent = db.query(AuditEvent.action, AuditEvent.created_at).filter(scope, AuditEvent.created_at >= since).all()
    per_day: Counter[date] = Counter()
    per_action: Counter[str] = Counter()
    for action, created in recent:
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        day = created.astimezone(ist).date()
        if day < first or day > today:
            continue
        per_day[day] += 1
        per_action[action] += 1
    actions = sorted(per_action.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "days": days,
        "from": first.isoformat(),
        "to": today.isoformat(),
        "entries": sum(per_day.values()),
        "all_time": int(total),
        "by_day": [{"date": (first + timedelta(days=i)).isoformat(), "entries": per_day.get(first + timedelta(days=i), 0)}
                   for i in range(days)],
        "by_action": {
            "items": [{"action": a, "entries": n} for a, n in actions[:GROUP_ROWS]],
            "not_shown": max(0, len(actions) - GROUP_ROWS),
            "not_shown_entries": sum(n for _, n in actions[GROUP_ROWS:]),
        },
    }
