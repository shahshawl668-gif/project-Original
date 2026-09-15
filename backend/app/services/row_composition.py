"""
What one register row actually contains.

A real salary register is not one kind of run. The same file carries people paid
normally, people receiving arrears for earlier months, and people whose increment
was effective some months back and is being settled now — often the same person
carrying two of the three. Forcing the operator to declare "this is an arrear
run" up front makes them either split the file or accept wrong checks on most of
it: an arrear run suppresses spike detection for *everyone*, including the
twenty-three employees whose pay simply jumped.

So the nature of each row is read from the row, not declared for the file. Every
register is validated in one pass and each employee is checked against the rules
that apply to them.

The declared ``run_type`` survives as a hint for the whole file — useful when a
register genuinely is all-arrears and carries no per-row dates — but it no longer
decides what gets checked.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.services.payroll_parse import normalize_col
from app.services.workforce_parse import parse_date, parse_decimal

# Column spellings that state the period an arrear covers.
ARREAR_FROM_KEYS = ("arrear_from", "arrear_effective_from", "arrear_period_from",
                    "effective_from", "revision_effective_from", "increment_effective_from",
                    "arrear_start", "from_month")
ARREAR_TO_KEYS = ("arrear_to", "arrear_effective_to", "arrear_period_to",
                  "effective_to", "arrear_end", "to_month")
ARREAR_MONTHS_KEYS = ("arrear_months", "arrear_month_count", "no_of_months",
                      "number_of_months", "months")


@dataclass(frozen=True)
class RowComposition:
    """The kinds of pay present in one row, and the window any arrears cover."""

    has_regular: bool
    has_arrear: bool
    has_increment_arrear: bool

    arrear_total: Decimal
    increment_arrear_total: Decimal

    # The arrear window for *this* employee. Different people can be settling
    # different periods in the same register, so this is never taken from the
    # file-level parameters when the row states its own.
    arrear_from: date | None
    arrear_to: date | None
    arrear_months: int | None
    window_source: str  # "row" | "ctc" | "run parameters" | "unknown"

    @property
    def kinds(self) -> list[str]:
        out = []
        if self.has_regular:
            out.append("regular")
        if self.has_arrear:
            out.append("arrear")
        if self.has_increment_arrear:
            out.append("increment arrear")
        return out

    @property
    def label(self) -> str:
        return " + ".join(self.kinds) if self.kinds else "empty"

    @property
    def is_mixed(self) -> bool:
        return len(self.kinds) > 1

    @property
    def any_arrear(self) -> bool:
        return self.has_arrear or self.has_increment_arrear


def _first_present(row_norm: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row_norm and row_norm[key] not in (None, ""):
            return row_norm[key]
    return None


def months_between(start: date, end: date) -> int:
    """Whole calendar months covered by an inclusive month range."""
    return max((end.year - start.year) * 12 + (end.month - start.month) + 1, 0)


def describe(
    row: dict[str, Any],
    regular: dict[str, Decimal],
    arrear_by_base: dict[str, Decimal],
    increment_arrear_total: Decimal,
    *,
    ctc_effective_from: date | None = None,
    period_month: date | None = None,
    run_effective_from: date | None = None,
    run_effective_to: date | None = None,
) -> RowComposition:
    """
    Classify one row and resolve the arrear window that applies to it.

    The window is taken from the most specific source available: dates stated on
    the row, then the effective date of the employee's own CTC revision, then the
    file-level run parameters. An arrear with no window from any source is
    reported rather than assumed — the month count is what every arrear
    expectation is multiplied by, so guessing it would quietly fabricate an
    expected figure.
    """
    row_norm = {normalize_col(str(k)): v for k, v in row.items() if k is not None}

    arrear_total = sum(arrear_by_base.values(), start=Decimal("0"))
    has_regular = any(v != 0 for v in regular.values())
    has_arrear = arrear_total != 0
    has_increment = increment_arrear_total != 0

    arrear_from = parse_date(_first_present(row_norm, ARREAR_FROM_KEYS))
    arrear_to = parse_date(_first_present(row_norm, ARREAR_TO_KEYS))
    stated_months = parse_decimal(_first_present(row_norm, ARREAR_MONTHS_KEYS))

    source = "unknown"
    if arrear_from or stated_months is not None:
        source = "row"
    elif ctc_effective_from is not None:
        arrear_from = ctc_effective_from
        source = "ctc"
    elif run_effective_from is not None:
        arrear_from = run_effective_from
        arrear_to = arrear_to or run_effective_to
        source = "run parameters"

    # The window ends at the period being paid unless the row says otherwise.
    if arrear_from and not arrear_to and period_month:
        arrear_to = period_month

    months: int | None = None
    if stated_months is not None and stated_months > 0:
        months = int(stated_months)
    elif arrear_from and arrear_to:
        months = months_between(arrear_from.replace(day=1), arrear_to.replace(day=1))

    if not (has_arrear or has_increment):
        # No arrears: the window is meaningless, so do not imply one.
        return RowComposition(
            has_regular=has_regular, has_arrear=False, has_increment_arrear=False,
            arrear_total=Decimal("0"), increment_arrear_total=Decimal("0"),
            arrear_from=None, arrear_to=None, arrear_months=None, window_source="unknown",
        )

    return RowComposition(
        has_regular=has_regular,
        has_arrear=has_arrear,
        has_increment_arrear=has_increment,
        arrear_total=arrear_total,
        increment_arrear_total=increment_arrear_total,
        arrear_from=arrear_from,
        arrear_to=arrear_to,
        arrear_months=months,
        window_source=source if months is not None else "unknown",
    )
