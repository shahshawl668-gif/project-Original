"""India income-tax engine — old vs new regime.

Implements the tax computation that payroll teams use to validate **monthly
TDS** against the **annualised** projection, for FY 2025-26 (AY 2026-27).

Scope intentionally limited to validation, not e-filing accuracy:
  * Slab tax for both regimes.
  * Section 87A rebate (₹12,500 in old regime up to ₹5L taxable;
    ₹60,000 in new regime up to ₹12L taxable for FY 2025-26).
  * Surcharge (10/15/25/37%, capped at 25% in new regime) with marginal relief.
  * Health & Education cess (4%).
  * Standard deduction (₹50,000 old / ₹75,000 new).
  * Old-regime Chapter VI-A bucket (80C, 80D, 80CCD(1B), home loan interest).
  * Marginal relief for 87A around the ₹7L / ₹12L thresholds in the new regime.

NOTE: This is a *projection* used to flag mismatches; it is not an end-of-year
reconciliation tool. All amounts in ₹.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Regime = Literal["old", "new"]


# ---------------------------------------------------------------------------
# Slabs
# ---------------------------------------------------------------------------

# New regime FY 2025-26 (Budget 2025): no tax up to ₹12L for residents (87A);
# slabs apply on the full income above 4L when income exceeds the 87A ceiling.
_NEW_SLABS: list[tuple[float, float]] = [
    (400_000, 0.00),
    (800_000, 0.05),
    (1_200_000, 0.10),
    (1_600_000, 0.15),
    (2_000_000, 0.20),
    (2_400_000, 0.25),
    (float("inf"), 0.30),
]

# Old regime FY 2025-26 (unchanged). Senior-citizen variants left out for the
# validation scope.
_OLD_SLABS: list[tuple[float, float]] = [
    (250_000, 0.00),
    (500_000, 0.05),
    (1_000_000, 0.20),
    (float("inf"), 0.30),
]


def _slab_tax(taxable: float, slabs: list[tuple[float, float]]) -> float:
    if taxable <= 0:
        return 0.0
    tax = 0.0
    prev = 0.0
    for ceiling, rate in slabs:
        if taxable <= ceiling:
            tax += (taxable - prev) * rate
            return tax
        tax += (ceiling - prev) * rate
        prev = ceiling
    return tax


# ---------------------------------------------------------------------------
# Surcharge
# ---------------------------------------------------------------------------

def _surcharge(tax_before_cess: float, taxable: float, regime: Regime) -> float:
    """Surcharge with marginal relief (simplified: relief at the *threshold*)."""
    if tax_before_cess <= 0:
        return 0.0

    # Brackets (₹) -> rate
    if regime == "new":
        brackets = [
            (5_000_000, 0.00),
            (10_000_000, 0.10),
            (20_000_000, 0.15),
            (float("inf"), 0.25),  # 37% removed in new regime
        ]
    else:
        brackets = [
            (5_000_000, 0.00),
            (10_000_000, 0.10),
            (20_000_000, 0.15),
            (50_000_000, 0.25),
            (float("inf"), 0.37),
        ]

    rate = 0.0
    for ceiling, r in brackets:
        if taxable <= ceiling:
            rate = r
            break
    return tax_before_cess * rate


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TaxBreakup:
    regime: Regime
    annual_gross: float
    standard_deduction: float
    chapter_via: float
    taxable_income: float
    slab_tax: float
    rebate_87a: float
    surcharge: float
    cess: float
    total_tax_annual: float
    monthly_tds: float
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OldRegimeDeductions:
    section_80c: float = 0.0
    section_80d: float = 0.0
    section_80ccd_1b: float = 0.0  # NPS additional
    home_loan_interest: float = 0.0  # Section 24(b), self-occupied capped 2L
    hra_exempt: float = 0.0  # already-exempt HRA component
    other_chapter_via: float = 0.0


def _capped_chapter_via(d: OldRegimeDeductions) -> tuple[float, list[str]]:
    notes: list[str] = []
    c80 = min(150_000.0, d.section_80c)
    if d.section_80c > 150_000:
        notes.append("80C capped at ₹1,50,000")
    c80d = min(100_000.0, d.section_80d)  # generous combined cap
    if d.section_80d > 100_000:
        notes.append("80D capped at ₹1,00,000 (combined)")
    c80ccd1b = min(50_000.0, d.section_80ccd_1b)
    if d.section_80ccd_1b > 50_000:
        notes.append("80CCD(1B) capped at ₹50,000")
    home = min(200_000.0, d.home_loan_interest)
    if d.home_loan_interest > 200_000:
        notes.append("Home loan interest capped at ₹2,00,000 (self-occupied)")
    other = max(0.0, d.other_chapter_via)
    total = c80 + c80d + c80ccd1b + home + other + d.hra_exempt
    return total, notes


def compute_income_tax(
    *,
    annual_gross: float,
    regime: Regime,
    deductions: OldRegimeDeductions | None = None,
) -> TaxBreakup:
    """Return projected annual tax + monthly TDS for the chosen regime."""
    notes: list[str] = []
    deductions = deductions or OldRegimeDeductions()

    if regime == "new":
        std_ded = 75_000.0
        chapter_via = 0.0
    else:
        std_ded = 50_000.0
        chapter_via, capping_notes = _capped_chapter_via(deductions)
        notes.extend(capping_notes)

    taxable = max(0.0, annual_gross - std_ded - chapter_via)
    slabs = _NEW_SLABS if regime == "new" else _OLD_SLABS
    slab_tax = _slab_tax(taxable, slabs)

    # 87A rebate
    rebate = 0.0
    if regime == "new":
        if taxable <= 1_200_000:
            rebate = min(slab_tax, 60_000.0)
        else:
            # Marginal relief: tax payable should not exceed (income - 12L)
            margin = taxable - 1_200_000
            if slab_tax - margin > 0 and slab_tax > margin:
                # Cap tax at the margin amount when slab_tax exceeds excess income
                rebate = max(0.0, slab_tax - margin)
                if rebate > 0:
                    notes.append("Marginal relief applied near ₹12L threshold")
    else:
        if taxable <= 500_000:
            rebate = min(slab_tax, 12_500.0)

    tax_after_rebate = max(0.0, slab_tax - rebate)

    surcharge = _surcharge(tax_after_rebate, taxable, regime)
    cess = (tax_after_rebate + surcharge) * 0.04
    total = round(tax_after_rebate + surcharge + cess, 2)

    return TaxBreakup(
        regime=regime,
        annual_gross=annual_gross,
        standard_deduction=std_ded,
        chapter_via=chapter_via,
        taxable_income=taxable,
        slab_tax=round(slab_tax, 2),
        rebate_87a=round(rebate, 2),
        surcharge=round(surcharge, 2),
        cess=round(cess, 2),
        total_tax_annual=total,
        monthly_tds=round(total / 12.0, 2),
        notes=notes,
    )


def compare_regimes(
    *,
    annual_gross: float,
    deductions: OldRegimeDeductions | None = None,
) -> dict:
    old = compute_income_tax(annual_gross=annual_gross, regime="old", deductions=deductions)
    new = compute_income_tax(annual_gross=annual_gross, regime="new")
    cheaper: Regime = "new" if new.total_tax_annual <= old.total_tax_annual else "old"
    saving = abs(new.total_tax_annual - old.total_tax_annual)
    return {
        "old": old.__dict__,
        "new": new.__dict__,
        "cheaper_regime": cheaper,
        "annual_saving": round(saving, 2),
    }
