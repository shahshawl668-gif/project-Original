"""
Filing readiness against the statutory calendar.

What this is, and what it deliberately is not
---------------------------------------------
This product never runs payroll and never touches the EPFO, ESIC, state PT or
TRACES portals. It therefore **cannot know whether a return was filed**, and a
panel that showed a green tick against "EPF ECR" would be asserting something it
has no evidence for — the worst kind of compliance dashboard, because the tick
is exactly what stops someone checking.

So what is reported is *readiness*: for each obligation arising from a wage
month, the due date, how long is left, and whether anything this product can see
would stop the filing being correct — a missing register, unresolved statutory
findings, an unsigned period. A green row means "nothing here is blocking you",
never "this has been filed". The distinction is stated in the payload so an API
consumer cannot miss it either.

The calendar
------------
Due dates are the central ones and hold for most employers:

* **EPF ECR** — 15th of the month after the wage month;
* **ESIC contribution** — 15th of the month after the wage month;
* **TDS deposit (salary)** — 7th of the month after deduction, except March,
  which is 30 April;
* **Form 24Q** — the quarterly TDS return: 31 Jul, 31 Oct, 31 Jan and 31 May for
  Q1 to Q4 of the financial year;
* **Professional tax** — state law, not central, so the date genuinely varies.
  The 20th is used as the common case and the row says it varies, rather than
  quoting a single date as though PT were uniform across India.

Where a due date falls is a fact about the statute, not about the client, so it
is computed rather than configured. Anything a particular employer files on a
different cycle is a reason to say so on the row, not to invent a date.
"""
from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import FindingState, PeriodSignOff, SalaryRegister

# Rule families whose shortfalls would make a filing wrong, per obligation.
_RULE_HEADS: dict[str, tuple[str, ...]] = {
    "epf_ecr": ("PF-", "STAT-001", "STAT-002", "STAT-003"),
    "esic": ("ESIC-", "ESI-"),
    "pt": ("PT-",),
    "tds_deposit": ("TDS-", "IT-"),
    "form_24q": ("TDS-", "IT-"),
}


def _end_of(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _add_months(period: date, months: int) -> date:
    total = (period.year * 12 + period.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def _day_in(period: date, day: int) -> date:
    """``day`` of ``period``'s month, clamped to a short month."""
    last = calendar.monthrange(period.year, period.month)[1]
    return date(period.year, period.month, min(day, last))


def fy_quarter(period: date) -> tuple[int, int]:
    """(financial year start year, quarter 1-4) for a wage month."""
    fy_start = period.year if period.month >= 4 else period.year - 1
    return fy_start, ((period.month - 4) % 12) // 3 + 1


@dataclass(frozen=True)
class Obligation:
    key: str
    label: str
    authority: str
    cadence: str  # "monthly" | "quarterly"
    note: str


OBLIGATIONS: tuple[Obligation, ...] = (
    Obligation("epf_ecr", "EPF — ECR & challan", "EPFO", "monthly",
               "Electronic challan-cum-return for the wage month."),
    Obligation("esic", "ESI — contribution", "ESIC", "monthly",
               "Employee and employer contribution for the wage month."),
    Obligation("pt", "Professional tax", "State", "monthly",
               "Due date is set by state law and varies; the 20th is the common case."),
    Obligation("tds_deposit", "TDS — deposit", "Income Tax", "monthly",
               "Tax deducted on salary, deposited by challan."),
    Obligation("form_24q", "TDS — Form 24Q", "Income Tax", "quarterly",
               "Quarterly salary TDS return; Form 16 follows from it."),
)


def due_date(key: str, period: date) -> tuple[date, str]:
    """When an obligation arising from wage month ``period`` falls due."""
    following = _add_months(period, 1)

    if key in ("epf_ecr", "esic"):
        return _day_in(following, 15), "15th of the following month"
    if key == "pt":
        return _day_in(following, 20), "varies by state — 20th assumed"
    if key == "tds_deposit":
        # March's deduction gets until 30 April, unlike every other month.
        if period.month == 3:
            return date(period.year, 4, 30), "30 April for March deductions"
        return _day_in(following, 7), "7th of the following month"
    if key == "form_24q":
        fy_start, quarter = fy_quarter(period)
        ends = {
            1: date(fy_start, 7, 31),
            2: date(fy_start, 10, 31),
            3: date(fy_start + 1, 1, 31),
            4: date(fy_start + 1, 5, 31),
        }
        return ends[quarter], f"FY{str(fy_start + 1)[-2:]} Q{quarter} return"
    raise ValueError(f"unknown obligation: {key}")


def _blockers(
    key: str,
    open_by_family: dict[str, tuple[int, Decimal]],
) -> tuple[int, Decimal]:
    prefixes = _RULE_HEADS.get(key, ())
    count = 0
    amount = Decimal("0")
    for rule_id, (n, impact) in open_by_family.items():
        if any(rule_id.startswith(prefix) for prefix in prefixes):
            count += n
            amount += impact
    return count, amount


def filing_readiness(
    db: Session,
    entity_id: uuid.UUID,
    period: date,
    as_of: date | None = None,
) -> dict:
    """
    Every obligation arising from one wage month, with what is blocking it.

    Status is the worst thing true of the row:

    * ``no_register`` — nothing has been uploaded for the month, so there is
      nothing to file from;
    * ``blocked`` — validation left an unresolved shortfall under this head.
      Filing on these figures files a known error;
    * ``overdue`` — the date has passed and the period was never signed off;
    * ``due_soon`` — inside seven days;
    * ``ready`` — nothing visible is blocking, and the period is signed off;
    * ``open`` — nothing blocking, not yet signed, not yet near the date.
    """
    as_of = as_of or date.today()
    period = period.replace(day=1)

    register = (
        db.query(SalaryRegister)
        .filter(SalaryRegister.entity_id == entity_id, SalaryRegister.period_month == period)
        .first()
    )
    signoff = (
        db.query(PeriodSignOff)
        .filter(PeriodSignOff.entity_id == entity_id, PeriodSignOff.period_month == period)
        .first()
    )
    signed = bool(signoff and signoff.state == "signed")

    states = (
        db.query(FindingState)
        .filter(
            FindingState.entity_id == entity_id,
            FindingState.state.in_(("open", "acknowledged")),
            FindingState.last_seen_period == period,
        )
        .all()
    )
    open_by_family: dict[str, tuple[int, Decimal]] = {}
    for state in states:
        count, impact = open_by_family.get(state.rule_id, (0, Decimal("0")))
        raw = state.last_financial_impact
        open_by_family[state.rule_id] = (
            count + 1,
            impact + (Decimal(str(raw)) if raw not in (None, "") else Decimal("0")),
        )

    rows = []
    for obligation in OBLIGATIONS:
        due, basis = due_date(obligation.key, period)
        days_left = (due - as_of).days
        blocking_count, blocking_amount = _blockers(obligation.key, open_by_family)

        if register is None:
            status = "no_register"
        elif blocking_count:
            status = "blocked"
        elif days_left < 0 and not signed:
            status = "overdue"
        elif signed:
            status = "ready"
        elif days_left <= 7:
            status = "due_soon"
        else:
            status = "open"

        rows.append({
            "key": obligation.key,
            "label": obligation.label,
            "authority": obligation.authority,
            "cadence": obligation.cadence,
            "note": obligation.note,
            "due_date": due.isoformat(),
            "due_basis": basis,
            "days_left": days_left,
            "status": status,
            "open_findings": blocking_count,
            "at_risk_amount": float(blocking_amount.quantize(Decimal("0.01"))),
        })

    return {
        "period": period.isoformat(),
        "period_label": period.strftime("%b %Y"),
        "as_of": as_of.isoformat(),
        "register_uploaded": register is not None,
        "signed_off": signed,
        "signoff_state": signoff.state if signoff else None,
        "obligations": rows,
        # Said in the payload, not only in the UI: a consumer of this API must
        # not read a status as confirmation that anything was filed.
        "disclaimer": (
            "Readiness only. This product does not connect to EPFO, ESIC, state "
            "PT portals or TRACES and cannot confirm that any return was filed."
        ),
    }


def filing_calendar(
    db: Session,
    entity_id: uuid.UUID,
    months: int = 6,
    as_of: date | None = None,
) -> dict:
    """Readiness for the most recent periods, newest first."""
    as_of = as_of or date.today()
    periods = (
        db.query(SalaryRegister.period_month)
        .filter(SalaryRegister.entity_id == entity_id)
        .order_by(SalaryRegister.period_month.desc())
        .limit(months)
        .all()
    )
    return {
        "as_of": as_of.isoformat(),
        "periods": [filing_readiness(db, entity_id, p, as_of) for (p,) in periods],
    }
