"""
What a figure rests on.

Every BI answer is a sum over stored registers, and a sum hides three things a
reader needs before trusting it:

* **Which months are in it** — and which months in the range have no register
  at all. A missing month is not a cheap month; a chart that draws it as zero,
  or skips it silently, tells the reader something false.
* **How fresh it is** — when the newest register in it was uploaded.
* **Whether it was checked** — for each month, whether the register was
  validated, whether it changed after its validation, and whether the month
  was signed off. Unvalidated figures are figures nobody has looked at.

And one data-quality measure that changes how a breakdown reads: the share of
people whose dimension is not recorded (reported as "Unassigned").
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import PeriodSignOff, RegisterUpload, SalaryRegister, ValidationRun


def month_range(start: date, end: date) -> list[date]:
    out, cur = [], start.replace(day=1)
    end = end.replace(day=1)
    while cur <= end:
        out.append(cur)
        cur = cur.replace(year=cur.year + 1, month=1) if cur.month == 12 else cur.replace(month=cur.month + 1)
    return out


def data_basis(
    db: Session,
    entity_id: uuid.UUID,
    *,
    date_from: date | None,
    date_to: date | None,
    rows: list[Any] | None = None,
    group_by: str | None = None,
) -> dict[str, Any]:
    registers = db.query(SalaryRegister.period_month).filter(SalaryRegister.entity_id == entity_id)
    if date_from:
        registers = registers.filter(SalaryRegister.period_month >= date_from.replace(day=1))
    if date_to:
        registers = registers.filter(SalaryRegister.period_month <= date_to.replace(day=1))
    present = sorted({p for (p,) in registers.all()})

    missing: list[str] = []
    if present or (date_from and date_to):
        start = date_from.replace(day=1) if date_from else present[0]
        end = date_to.replace(day=1) if date_to else present[-1]
        have = set(present)
        missing = [m.isoformat() for m in month_range(start, end) if m not in have]

    uploads = {
        p: (uid, ts) for p, uid, ts in db.query(
            RegisterUpload.period_month, RegisterUpload.id, RegisterUpload.created_at,
        ).filter(
            RegisterUpload.entity_id == entity_id,
            RegisterUpload.period_month.in_(present),
            func.coalesce(RegisterUpload.run_type, "regular") == "regular",
        ).order_by(RegisterUpload.revision)
    } if present else {}
    runs = {
        r.period_month: r for r in db.query(ValidationRun).filter(
            ValidationRun.entity_id == entity_id, ValidationRun.status == "current",
            ValidationRun.period_month.in_(present),
        )
    } if present else {}
    signed = {
        s.period_month: s.state for s in db.query(PeriodSignOff).filter(
            PeriodSignOff.entity_id == entity_id, PeriodSignOff.period_month.in_(present),
        )
    } if present else {}

    months = []
    for p in present:
        run = runs.get(p)
        upload = uploads.get(p)
        if run is None:
            status, label = "not_validated", "Not validated"
        elif upload and run.upload_id and run.upload_id != upload[0]:
            status, label = "changed_since_validation", "Register changed since validation"
        else:
            status, label = "validated", f"Validated (run #{run.run_number})"
        if signed.get(p) == "signed":
            label += " · signed off"
        months.append({
            "period": p.isoformat(),
            "validation": status,
            "label": label,
            "signed_off": signed.get(p) == "signed",
            "open_findings": (run.critical_count + run.warning_count) if run else None,
            "uploaded_at": upload[1].isoformat() if upload and upload[1] else None,
        })

    last = max((m["uploaded_at"] for m in months if m["uploaded_at"]), default=None)
    unassigned = None
    if rows is not None and group_by:
        from app.services.dimensions import UNASSIGNED

        people = {}
        for row in rows:
            people[row.employee_id] = (row.dimensions or {}).get(group_by) or UNASSIGNED
        if people:
            n = sum(1 for v in people.values() if v == UNASSIGNED)
            unassigned = {"dimension": group_by, "employees": n, "pct": round(n * 100 / len(people), 1)}

    return {
        "periods_with_register": [p.isoformat() for p in present],
        "missing_months": missing,
        "last_uploaded_at": last,
        "months": months,
        "validated_months": sum(1 for m in months if m["validation"] == "validated"),
        "unvalidated_months": sum(1 for m in months if m["validation"] != "validated"),
        "signed_off_months": sum(1 for m in months if m["signed_off"]),
        "unassigned": unassigned,
        "source": "Stored salary registers (regular runs), costed through the component configuration",
    }
