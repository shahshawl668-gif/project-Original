"""India income-tax engine — old vs new regime, fully config-driven.

Implements the tax computation that payroll teams use to validate **monthly
TDS** against the **annualised** projection.

No statutory value is hardcoded here: slabs, Section 87A rebate, surcharge
brackets, cess, standard deduction and Chapter VI-A caps all come from a
`TaxYearConfig` (per tenant, per financial year, editable via
/api/config/income-tax). When no config is passed, the seed catalog's
default financial year is used.

NOTE: This is a *projection* used to flag mismatches; it is not an
end-of-year reconciliation tool. All amounts in ₹.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from app.schemas.income_tax_config import RegimeConfig, TaxYearConfig

Regime = Literal["old", "new"]


# ---------------------------------------------------------------------------
# Slab / surcharge math (pure, config-driven)
# ---------------------------------------------------------------------------

def _slab_tax(taxable: float, regime_cfg: RegimeConfig) -> float:
    if taxable <= 0:
        return 0.0
    tax = 0.0
    prev = 0.0
    for slab in regime_cfg.slabs:
        ceiling = float(slab.up_to) if slab.up_to is not None else float("inf")
        rate = float(slab.rate)
        if taxable <= ceiling:
            tax += (taxable - prev) * rate
            return tax
        tax += (ceiling - prev) * rate
        prev = ceiling
    return tax


def _surcharge(tax_before_cess: float, taxable: float, regime_cfg: RegimeConfig) -> float:
    """Surcharge with marginal relief (simplified: relief at the *threshold*)."""
    if tax_before_cess <= 0 or not regime_cfg.surcharge_brackets:
        return 0.0
    rate = 0.0
    for bracket in regime_cfg.surcharge_brackets:
        ceiling = float(bracket.up_to) if bracket.up_to is not None else float("inf")
        if taxable <= ceiling:
            rate = float(bracket.rate)
            break
    return tax_before_cess * rate


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TaxBreakup:
    regime: Regime
    financial_year: str
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
    home_loan_interest: float = 0.0  # Section 24(b), self-occupied
    hra_exempt: float = 0.0  # already-exempt HRA component
    other_chapter_via: float = 0.0


def _capped_chapter_via(
    d: OldRegimeDeductions, year_cfg: TaxYearConfig
) -> tuple[float, list[str]]:
    caps = year_cfg.deduction_caps
    notes: list[str] = []
    cap_80c = float(caps.section_80c)
    cap_80d = float(caps.section_80d)
    cap_80ccd_1b = float(caps.section_80ccd_1b)
    cap_home = float(caps.home_loan_interest)

    c80 = min(cap_80c, d.section_80c)
    if d.section_80c > cap_80c:
        notes.append(f"80C capped at ₹{cap_80c:,.0f}")
    c80d = min(cap_80d, d.section_80d)
    if d.section_80d > cap_80d:
        notes.append(f"80D capped at ₹{cap_80d:,.0f} (combined)")
    c80ccd1b = min(cap_80ccd_1b, d.section_80ccd_1b)
    if d.section_80ccd_1b > cap_80ccd_1b:
        notes.append(f"80CCD(1B) capped at ₹{cap_80ccd_1b:,.0f}")
    home = min(cap_home, d.home_loan_interest)
    if d.home_loan_interest > cap_home:
        notes.append(f"Home loan interest capped at ₹{cap_home:,.0f} (self-occupied)")
    other = max(0.0, d.other_chapter_via)
    total = c80 + c80d + c80ccd1b + home + other + d.hra_exempt
    return total, notes


def _rebate(slab_tax: float, taxable: float, regime_cfg: RegimeConfig, notes: list[str]) -> float:
    reb = regime_cfg.rebate
    limit = float(reb.taxable_income_limit)
    max_rebate = float(reb.max_rebate)
    if limit <= 0 or max_rebate <= 0:
        return 0.0
    if taxable <= limit:
        return min(slab_tax, max_rebate)
    if reb.marginal_relief:
        # Marginal relief: tax payable should not exceed (income - limit)
        margin = taxable - limit
        if slab_tax > margin:
            rebate = max(0.0, slab_tax - margin)
            if rebate > 0:
                notes.append(f"Marginal relief applied near ₹{limit:,.0f} threshold")
            return rebate
    return 0.0


def compute_income_tax(
    *,
    annual_gross: float,
    regime: Regime,
    deductions: OldRegimeDeductions | None = None,
    year_cfg: TaxYearConfig | None = None,
) -> TaxBreakup:
    """Return projected annual tax + monthly TDS for the chosen regime.

    `year_cfg` carries every statutory parameter; omitting it falls back to
    the seed catalog's default financial year.
    """
    if year_cfg is None:
        from app.services.tax_year_defaults import default_income_tax_config

        year_cfg = default_income_tax_config().resolve_year()
    notes: list[str] = []
    deductions = deductions or OldRegimeDeductions()

    regime_cfg = year_cfg.new_regime if regime == "new" else year_cfg.old_regime
    std_ded = float(regime_cfg.standard_deduction)
    if regime_cfg.allow_chapter_via:
        chapter_via, capping_notes = _capped_chapter_via(deductions, year_cfg)
        notes.extend(capping_notes)
    else:
        chapter_via = 0.0

    taxable = max(0.0, annual_gross - std_ded - chapter_via)
    slab_tax = _slab_tax(taxable, regime_cfg)

    rebate = _rebate(slab_tax, taxable, regime_cfg, notes)
    tax_after_rebate = max(0.0, slab_tax - rebate)

    surcharge = _surcharge(tax_after_rebate, taxable, regime_cfg)
    cess = (tax_after_rebate + surcharge) * float(year_cfg.cess_rate)
    total = round(tax_after_rebate + surcharge + cess, 2)

    return TaxBreakup(
        regime=regime,
        financial_year=year_cfg.financial_year,
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
    year_cfg: TaxYearConfig | None = None,
) -> dict:
    old = compute_income_tax(
        annual_gross=annual_gross, regime="old", deductions=deductions, year_cfg=year_cfg
    )
    new = compute_income_tax(annual_gross=annual_gross, regime="new", year_cfg=year_cfg)
    cheaper: Regime = "new" if new.total_tax_annual <= old.total_tax_annual else "old"
    saving = abs(new.total_tax_annual - old.total_tax_annual)
    return {
        "old": asdict(old),
        "new": asdict(new),
        "cheaper_regime": cheaper,
        "annual_saving": round(saving, 2),
        "financial_year": old.financial_year,
    }
