"""
The four Labour Codes, as they change a payroll check.

Two provisions move numbers the engine already checks:

* **The wage definition** — Code on Wages s.2(y), mirrored in the Social
  Security Code s.2(88). Wages are Basic, DA and retaining allowance; the
  listed exclusions (HRA, conveyance, overtime, commission, bonus and the rest)
  stay out only up to half of all remuneration. Whatever they pay above that
  half is deemed wages, and PF, gratuity and bonus follow the larger figure.
* **Fixed-term gratuity** — Social Security Code s.53. A fixed-term employee
  earns gratuity, pro rata, after one year of service rather than five.

Both are measured here, without a database, against the tenant's
``LabourCodeThresholds``. The rates are configuration: a notification that
moves the half to another per cent edits a setting, not this file.

What this module does not decide is policy. The engine's PF expectation still
follows the components the company marked PF-applicable; LC-001 reports what
the deemed wages would add, and a payroll expert decides at the D6 sign-off
whether the company computes on them.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def _norm(text: Any) -> str:
    return re.sub(r"[\s_\-]+", " ", str(text or "")).strip().casefold()


def in_force(lc: Any, period_month: date | None) -> bool:
    """A pay period is under the Codes if it ends on or after the effective date."""
    if period_month is None:
        return False
    month_end = period_month.replace(day=calendar.monthrange(period_month.year, period_month.month)[1])
    return month_end >= lc.effective_from


def in_force_on(lc: Any, day: date | None) -> bool:
    return day is not None and day >= lc.effective_from


def is_fixed_term(employment_type: Any, lc: Any) -> bool:
    value = _norm(employment_type)
    return bool(value) and value in {_norm(m) for m in lc.fixed_term_markers}


def fixed_term_eligible(doj: date, dol: date, lc: Any) -> bool:
    """At least the minimum service, counted in days: seven months is not a year."""
    return Decimal((dol - doj).days) >= Decimal("365") * lc.fixed_term_gratuity_min_years


@dataclass(frozen=True)
class WageTest:
    """One employee's month under the s.2(y) definition."""

    basis: str                 # which components were taken as wages
    basis_known: bool          # False: no component is marked as wages, so no test is possible
    wages: Decimal             # Basic + DA (+ retaining allowance), as paid
    remuneration: Decimal      # all remuneration in the test
    excluded: Decimal          # remuneration − wages
    allowed: Decimal           # the cap: exclusions up to this stay out of wages
    deemed_addition: Decimal   # exclusions above the cap, added back to wages

    @property
    def code_wages(self) -> Decimal:
        return self.wages + self.deemed_addition

    @property
    def wage_pct(self) -> Decimal:
        if self.remuneration <= 0:
            return Decimal("0")
        return self.wages / self.remuneration * 100


def wage_test(regular: dict[str, Decimal], comp_by_key: dict[str, Any], lc: Any) -> WageTest:
    """
    ``regular`` is the month's earning components; ``comp_by_key`` their
    configuration. Remuneration is all of them — the Code says "all
    remuneration", so it does not wait on a company having flagged each
    allowance — less one-off payments (``one_off_component_keys``): a gratuity
    paid in the leaving month or a year's bonus paid in October is not the
    salary structure, and testing it would deem the payment itself to be wages.
    """
    configured = [k for k in (lc.wage_component_keys or []) if str(k).strip()]
    if configured:
        wage_keys = {str(k).strip() for k in configured}
        basis = "components set as wages: " + ", ".join(sorted(wage_keys))
    else:
        wage_keys = {k for k, c in comp_by_key.items() if c is not None and getattr(c, "pf_applicable", False)}
        basis = "PF-applicable components"
    one_off = {str(k).strip() for k in (lc.one_off_component_keys or [])}

    remuneration = Decimal("0")
    wages = Decimal("0")
    for key, amount in regular.items():
        if key in one_off:
            continue
        remuneration += amount
        if key in wage_keys:
            wages += amount

    excluded = max(remuneration - wages, Decimal("0"))
    allowed = _q(remuneration * lc.wage_exclusion_cap_pct / Decimal("100"))
    deemed = _q(max(excluded - allowed, Decimal("0")))
    return WageTest(basis=basis, basis_known=bool(wage_keys), wages=_q(wages), remuneration=_q(remuneration),
                    excluded=_q(excluded), allowed=allowed, deemed_addition=deemed)


def pf_effect(pf_calc: dict[str, Any], deemed: Decimal) -> tuple[Decimal, str]:
    """
    The employee PF a month that the deemed wages would add, and a sentence
    saying why. Follows the employee's own PF basis: at the ceiling and
    restricted, the deemed wages change nothing.
    """
    if deemed <= 0:
        return Decimal("0"), ""
    if Decimal(str(pf_calc.get("pf_employee") or 0)) <= 0:
        return Decimal("0"), "No PF is computed for this employee, so PF does not change."
    full = Decimal(str(pf_calc.get("_pf_wage_full") or 0))
    ceiling = Decimal(str(pf_calc.get("_ceiling") or 15000))
    rate = Decimal(str(pf_calc.get("_emp_rate") or "0.12"))
    if pf_calc.get("_restrict") and pf_calc.get("pf_type") != "voluntary_full":
        before, after = min(full, ceiling), min(full + deemed, ceiling)
    else:
        before, after = full, full + deemed
    rise = after - before
    if rise <= 0:
        return Decimal("0"), f"PF does not change: the PF wage is already restricted to the ₹{ceiling:,.0f} ceiling."
    more = _q(rise * rate)
    return more, (f"On the deemed wages the PF wage rises by ₹{_q(rise):,.2f}, so employee PF rises by "
                  f"₹{more:,.2f} a month and the employer's by about the same. The PF check above still "
                  "uses the components marked PF-applicable.")
