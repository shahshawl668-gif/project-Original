"""What a CTC revision means for the month being paid and for the months before it.

A register carries everything in one pass, so an increment can show up three ways
in the same file and each has a different expectation:

* **Effective part-way through the month being paid.** The month is paid at the old
  structure for the days before the revision and the new structure for the days
  from it. Expected pay is that blend, then reduced for any loss of pay.
* **Effective in an earlier month.** The month being paid is at the new structure,
  and the months from the effective date up to the month before this one owe an
  arrear of (new - old) for each, the first of them only for the days from the
  effective date.
* **Not yet effective.** Nothing changes.

Days are calendar days of each month, which is how the register's own total days
default; a company on a fixed 26/30-day month states that on the row and the
proration check already uses it.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")
TWELVE = Decimal(12)


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def days_in(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def monthly(record: Any) -> dict[str, Decimal]:
    """A CTC record's components as monthly amounts."""
    return {k: Decimal(str(v)) / TWELVE for k, v in (getattr(record, "annual_components", None) or {}).items()}


@dataclass(frozen=True)
class MonthStructure:
    """The structure the month being paid should follow."""

    expected: dict[str, Decimal]          # blended for a part-month revision, else the structure in force
    new: dict[str, Decimal]
    old: dict[str, Decimal] | None
    effective_from: date | None           # the latest revision
    mid_month: bool
    days_old: int
    days_new: int


def structure_for_month(latest: Any, previous: Any | None, period_month: date) -> MonthStructure:
    """``latest`` and ``previous`` are the two newest CTC records effective by the end of the month."""
    new = monthly(latest)
    old = monthly(previous) if previous is not None else None
    eff = latest.effective_from
    start, total = month_start(period_month), days_in(period_month)

    if previous is None or eff <= start:
        return MonthStructure(new, new, old, eff, False, 0, total)
    if eff > month_end(period_month):          # not yet in force: the earlier structure stands
        return MonthStructure(old or new, new, old, eff, False, total, 0)

    days_old = (eff - start).days
    days_new = total - days_old
    keys = set(new) | set(old or {})
    blended = {
        k: (Decimal(old.get(k, 0) if old else 0) * days_old + new.get(k, Decimal(0)) * days_new) / Decimal(total)
        for k in keys
    }
    return MonthStructure(blended, new, old, eff, True, days_old, days_new)


def expected_arrears(
    latest: Any,
    previous: Any | None,
    period_month: date,
    window_from: date | None = None,
    window_to: date | None = None,
) -> tuple[dict[str, Decimal], Decimal]:
    """
    Arrear owed for the months before ``period_month``, per component, and the
    months it spans (a part-month counts as a fraction). Empty when there is no
    earlier revision to settle.
    """
    if previous is None:
        return {}, Decimal(0)
    new, old = monthly(latest), monthly(previous)
    start = max(window_from or latest.effective_from, latest.effective_from)
    last_month_end = month_start(period_month) - timedelta(days=1)
    end = min(window_to, last_month_end) if window_to else last_month_end
    if start > end:
        return {}, Decimal(0)

    totals: dict[str, Decimal] = {}
    months = Decimal(0)
    cursor = month_start(start)
    while cursor <= end:
        first = max(start, cursor)
        last = min(end, month_end(cursor))
        fraction = Decimal((last - first).days + 1) / Decimal(days_in(cursor))
        months += fraction
        for key in set(new) | set(old):
            delta = new.get(key, Decimal(0)) - old.get(key, Decimal(0))
            if delta:
                totals[key] = totals.get(key, Decimal(0)) + delta * fraction
        cursor = month_start(month_end(cursor) + timedelta(days=1))
    return {k: _q(v) for k, v in totals.items() if _q(v) != 0}, months


def classify_pay_mismatches(
    diffs: list[dict[str, Any]],
    structure: MonthStructure,
    factor: Decimal,
    tolerance: Decimal,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Split proration mismatches into those that are really about an increment and the rest.

    A component paid at the pre-increment amount, or at the full new amount in the
    month the revision lands, is not a generic proration slip — the fix is different,
    so it gets its own finding.
    """
    if structure.old is None:
        return diffs, []
    rest: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for d in diffs:
        key = d["component"]
        actual = Decimal(str(d["actual"]))
        old = structure.old.get(key, Decimal(0)) * factor
        new = structure.new.get(key, Decimal(0)) * factor
        if old == new:
            rest.append(d)
            continue
        close_old = (actual - old).copy_abs() <= tolerance
        close_new = (actual - new).copy_abs() <= tolerance
        if structure.mid_month and (close_old or close_new):
            issues.append({**d, "rule": "INC-002", "paid_at": "new" if close_new else "old",
                           "old": float(_q(old)), "new": float(_q(new)), "effective_from": structure.effective_from.isoformat(),
                           "days_old": structure.days_old, "days_new": structure.days_new})
        elif not structure.mid_month and close_old:
            issues.append({**d, "rule": "INC-001", "paid_at": "old", "old": float(_q(old)), "new": float(_q(new)),
                           "effective_from": structure.effective_from.isoformat()})
        else:
            rest.append(d)
    return rest, issues
