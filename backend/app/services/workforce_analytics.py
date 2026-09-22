"""
Who was on the payroll, and what they are paid.

Two questions that sit next to cost but are not cost:

* **headcount movement** — opening, joiners, exits, closing. A payroll that rose
  6% because twelve people joined is a different conversation from one that rose
  6% because everyone got an increment, and a cost report that cannot separate
  them starts an argument rather than settling one;
* **how pay is distributed** — the average, the median, the spread. An average
  salary on its own is the least informative statistic in compensation: one
  founder's package moves it and nothing else does. The median and the quartiles
  are what a C&B team actually reasons with.

Both are derived from the stored registers, which is the only population this
product can vouch for. Where the employee master carries joining and exit dates
they are reported alongside as corroboration — never instead, because a master
that is three months stale would silently rewrite the movement. Where the two
disagree, both numbers are shown and the disagreement is the finding.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models import EmployeeRecord, SalaryRegister, SalaryRegisterRow

CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Headcount movement
# ---------------------------------------------------------------------------
def headcount_movement(
    db: Session,
    entity_id: uuid.UUID,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    filters: dict[str, list[str]] | None = None,
) -> dict:
    """
    Opening, joiners, exits and closing headcount for each stored month.

    Movement is measured by presence on the register: someone paid this month
    who was not paid last month is a joiner. That is a *verified* statement —
    the money moved — where a joining date on a master is an assertion that may
    not have reached payroll yet.

    The first month in the window has no prior register to open against, so its
    opening is reported as null rather than zero. Zero would say the company had
    nobody, which is a different and false claim.
    """
    from app.services.analytics import _register_rows, _Costing
    from app.services.dimensions import UNASSIGNED

    rows, by_register = _register_rows(db, entity_id, date_from, date_to)
    if not rows:
        return {"periods": [], "totals": {}}

    active = {k: set(v) for k, v in (filters or {}).items() if v}
    costing = _Costing(db, entity_id)

    # period -> employees, and period -> cost
    people: dict[date, set[str]] = {}
    cost: dict[date, Decimal] = {}
    for row in rows:
        dims = row.dimensions or {}
        if any(dims.get(key, UNASSIGNED) not in wanted for key, wanted in active.items()):
            continue
        period = by_register[row.register_id].period_month
        people.setdefault(period, set()).add(row.employee_id)
        measures = costing.cost(row).measures
        cost[period] = cost.get(period, Decimal("0")) + sum(
            (measures[k] for k in _ctc_keys()), Decimal("0")
        )

    periods = sorted(people)
    masters = _master_dates(db, entity_id)

    points = []
    for index, period in enumerate(periods):
        current = people[period]
        prior_period = periods[index - 1] if index else None
        prior = people.get(prior_period, set()) if prior_period else None

        joiners = sorted(current - prior) if prior is not None else []
        exits = sorted(prior - current) if prior is not None else []
        opening = len(prior) if prior is not None else None
        closing = len(current)

        # The master's own view, reported beside the register's rather than
        # instead of it. A master that has not been re-uploaded since March
        # would otherwise quietly rewrite every month after it.
        master_joiners = sum(
            1 for eid in current
            if (d := masters.get(eid, (None, None))[0]) and d.year == period.year and d.month == period.month
        )
        master_exits = sum(
            1 for eid, (_, exit_date) in masters.items()
            if exit_date and exit_date.year == period.year and exit_date.month == period.month
        )

        total_cost = cost.get(period, Decimal("0"))
        # Average headcount over the month, on the opening/closing convention.
        # Documented rather than assumed: it is the denominator every per-head
        # figure on this page divides by.
        average = (
            Decimal(opening + closing) / Decimal("2") if opening is not None else Decimal(closing)
        )

        points.append({
            "period": period.isoformat(),
            "label": period.strftime("%b %Y"),
            "opening": opening,
            "joiners": len(joiners),
            "exits": len(exits),
            "closing": closing,
            "net_change": (closing - opening) if opening is not None else None,
            "average_headcount": float(_q(average)),
            "total_ctc": float(_q(total_cost)),
            "cost_per_head_closing": float(_q(total_cost / closing)) if closing else 0.0,
            "cost_per_head_average": float(_q(total_cost / average)) if average else 0.0,
            "joiner_ids": joiners[:50],
            "exit_ids": exits[:50],
            "master_says": {"joiners": master_joiners, "exits": master_exits},
            "master_agrees": (
                prior is not None
                and master_joiners == len(joiners)
                and master_exits == len(exits)
            ),
        })

    first, last = points[0], points[-1]
    return {
        "periods": points,
        "totals": {
            "opening": first["opening"],
            "closing": last["closing"],
            "joiners": sum(p["joiners"] for p in points),
            "exits": sum(p["exits"] for p in points),
            "periods_counted": len(points),
        },
        # Said once, here, because every per-head number downstream depends on it.
        "denominator_note": (
            "Average headcount is (opening + closing) / 2 for each month. Cost per "
            "head is reported on both that and the closing count, because they "
            "differ materially in a month with heavy joining."
        ),
    }


def _ctc_keys() -> tuple[str, ...]:
    from app.services.cost_model import DERIVED_PARTS

    return DERIVED_PARTS["ctc"]


def _master_dates(db: Session, entity_id: uuid.UUID) -> dict[str, tuple[date | None, date | None]]:
    """The latest joining and exit date the master holds for each employee."""
    records = (
        db.query(
            EmployeeRecord.employee_id,
            EmployeeRecord.date_of_joining,
            EmployeeRecord.date_of_exit,
            EmployeeRecord.effective_from,
        )
        .filter(EmployeeRecord.entity_id == entity_id)
        .order_by(EmployeeRecord.employee_id, EmployeeRecord.effective_from)
        .all()
    )
    out: dict[str, tuple[date | None, date | None]] = {}
    for employee_id, joining, exit_date, _ in records:
        out[employee_id] = (joining, exit_date)
    return out


# ---------------------------------------------------------------------------
# Compensation distribution
# ---------------------------------------------------------------------------
def _percentile(sorted_values: list[Decimal], fraction: float) -> Decimal:
    """Linear-interpolated percentile of an already-sorted list."""
    if not sorted_values:
        return Decimal("0")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    weight = Decimal(str(position - low))
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * weight


def _stats(values: list[Decimal]) -> dict:
    values = sorted(values)
    count = len(values)
    if not count:
        return {"count": 0, "mean": 0.0, "median": 0.0, "p25": 0.0, "p75": 0.0,
                "p90": 0.0, "min": 0.0, "max": 0.0, "range_ratio": None, "total": 0.0}
    total = sum(values, Decimal("0"))
    low, high = values[0], values[-1]
    return {
        "count": count,
        "mean": float(_q(total / Decimal(count))),
        "median": float(_q(_percentile(values, 0.5))),
        "p25": float(_q(_percentile(values, 0.25))),
        "p75": float(_q(_percentile(values, 0.75))),
        "p90": float(_q(_percentile(values, 0.90))),
        "min": float(_q(low)),
        "max": float(_q(high)),
        # How wide the band is, which is the number a grade structure is judged
        # on. Undefined rather than infinite when the floor is zero.
        "range_ratio": float(_q(high / low)) if low > 0 else None,
        "total": float(_q(total)),
    }


def compensation_analysis(
    db: Session,
    entity_id: uuid.UUID,
    *,
    period: date | None = None,
    group_by: str = "grade",
    filters: dict[str, list[str]] | None = None,
    bucket_count: int = 8,
) -> dict:
    """
    How pay is distributed across the population, for one month.

    One month, not a range: averaging an employee's pay across months and then
    taking a median of those averages answers a question nobody asked. A
    compensation review is a snapshot of the establishment as it stands.

    Reported per employee on **annualised CTC** — the monthly cost times twelve —
    because that is the unit every salary band, offer and benchmark is quoted
    in. Arrears are excluded from the annualisation: a catch-up payment is not
    twelve times a year.
    """
    from app.services.analytics import _Costing
    from app.services.dimensions import DIMENSION_KEYS, DIMENSION_LABELS, UNASSIGNED

    if group_by not in DIMENSION_KEYS:
        raise ValueError(f"group_by must be one of: {', '.join(DIMENSION_KEYS)}")

    register = db.query(SalaryRegister).filter(SalaryRegister.entity_id == entity_id)
    if period:
        register = register.filter(SalaryRegister.period_month == period.replace(day=1))
    register = register.order_by(SalaryRegister.period_month.desc()).first()

    if register is None:
        return {
            "period": None, "period_label": None,
            "group_by": group_by, "group_by_label": DIMENSION_LABELS[group_by],
            "overall": _stats([]), "groups": [], "distribution": [],
            "mix": {"fixed": 0.0, "variable": 0.0, "fixed_pct": 0.0, "variable_pct": 0.0},
            # Present and empty, not absent. The router masks this list on the
            # way out, so a missing key is a 500 on every workspace that has not
            # uploaded a register yet — which is every new one.
            "employees": [],
        }

    rows = (
        db.query(SalaryRegisterRow)
        .filter(SalaryRegisterRow.register_id == register.id)
        .all()
    )
    active = {k: set(v) for k, v in (filters or {}).items() if v}
    costing = _Costing(db, entity_id)

    annual: list[Decimal] = []
    by_group: dict[str, list[Decimal]] = {}
    fixed_total = variable_total = Decimal("0")
    per_employee: list[dict] = []

    for row in rows:
        dims = row.dimensions or {}
        if any(dims.get(key, UNASSIGNED) not in wanted for key, wanted in active.items()):
            continue
        measures = costing.cost(row).measures
        # Annualised on the recurring cost only — arrears are this month's
        # catch-up, not a twelfth of a year's pay.
        monthly = sum((measures[k] for k in _ctc_keys()), Decimal("0")) - measures["arrears"]
        annualised = monthly * Decimal("12")

        fixed = measures["basic_da"] + measures["hra"] + measures["allowances"]
        variable = measures["variable_pay"]
        fixed_total += fixed
        variable_total += variable

        annual.append(annualised)
        by_group.setdefault(dims.get(group_by) or UNASSIGNED, []).append(annualised)
        per_employee.append({
            "employee_id": row.employee_id,
            "employee_name": row.employee_name,
            "group": dims.get(group_by) or UNASSIGNED,
            "annual_ctc": float(_q(annualised)),
            "fixed": float(_q(fixed)),
            "variable": float(_q(variable)),
        })

    overall = _stats(annual)
    mix_total = fixed_total + variable_total

    groups = [
        {"group": name, "label": name, **_stats(values)}
        for name, values in sorted(by_group.items())
    ]
    groups.sort(key=lambda g: g["median"], reverse=True)

    return {
        "period": register.period_month.isoformat(),
        "period_label": register.period_month.strftime("%b %Y"),
        "group_by": group_by,
        "group_by_label": DIMENSION_LABELS[group_by],
        "basis": "Annualised CTC (monthly cost to company × 12, excluding arrears)",
        "overall": overall,
        "groups": groups,
        "distribution": _histogram(annual, bucket_count),
        "mix": {
            "fixed": float(_q(fixed_total)),
            "variable": float(_q(variable_total)),
            "fixed_pct": float(_q(fixed_total / mix_total * 100)) if mix_total else 0.0,
            "variable_pct": float(_q(variable_total / mix_total * 100)) if mix_total else 0.0,
        },
        "employees": sorted(per_employee, key=lambda e: e["annual_ctc"], reverse=True),
    }


def _histogram(values: list[Decimal], buckets: int) -> list[dict]:
    """Equal-width salary bands across the observed range."""
    if not values:
        return []
    low, high = min(values), max(values)
    if high == low:
        return [{"from": float(_q(low)), "to": float(_q(high)), "count": len(values)}]

    width = (high - low) / Decimal(buckets)
    out = []
    for index in range(buckets):
        start = low + width * index
        end = start + width
        # The top band is closed so the highest-paid employee is counted once
        # rather than falling off the end of a half-open interval.
        if index == buckets - 1:
            count = sum(1 for v in values if start <= v <= end)
        else:
            count = sum(1 for v in values if start <= v < end)
        out.append({"from": float(_q(start)), "to": float(_q(end)), "count": count})
    return out
