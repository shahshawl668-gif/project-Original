"""
Seed catalog of income-tax parameters per financial year.

These are DEFAULTS, not law baked into code: they initialise a tenant's
IncomeTaxConfig (and back the reset endpoint) and are fully editable through
/api/config/income-tax afterwards. Add a new FY here when a Budget changes
rates, or let tenants add it themselves via the API/UI.

Provenance
----------
FY 2025-26: Finance Act 2025 (Budget of Feb 2025).
FY 2026-27: Budget 2026 announced no changes to slabs, 87A rebate, standard
deduction, surcharge or cess — values carried forward from FY 2025-26.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.schemas.income_tax_config import (
    DeductionCapsConfig,
    IncomeTaxConfig,
    RebateConfig,
    RegimeConfig,
    SurchargeBracket,
    TaxSlab,
    TaxYearConfig,
)

D = Decimal


def _new_regime() -> RegimeConfig:
    return RegimeConfig(
        label="New Regime",
        slabs=[
            TaxSlab(up_to=D("400000"), rate=D("0")),
            TaxSlab(up_to=D("800000"), rate=D("0.05")),
            TaxSlab(up_to=D("1200000"), rate=D("0.10")),
            TaxSlab(up_to=D("1600000"), rate=D("0.15")),
            TaxSlab(up_to=D("2000000"), rate=D("0.20")),
            TaxSlab(up_to=D("2400000"), rate=D("0.25")),
            TaxSlab(up_to=None, rate=D("0.30")),
        ],
        standard_deduction=D("75000"),
        rebate=RebateConfig(
            taxable_income_limit=D("1200000"),
            max_rebate=D("60000"),
            marginal_relief=True,
        ),
        surcharge_brackets=[
            SurchargeBracket(up_to=D("5000000"), rate=D("0")),
            SurchargeBracket(up_to=D("10000000"), rate=D("0.10")),
            SurchargeBracket(up_to=D("20000000"), rate=D("0.15")),
            SurchargeBracket(up_to=None, rate=D("0.25")),  # 37% band removed in new regime
        ],
        allow_chapter_via=False,
    )


def _old_regime() -> RegimeConfig:
    return RegimeConfig(
        label="Old Regime",
        slabs=[
            TaxSlab(up_to=D("250000"), rate=D("0")),
            TaxSlab(up_to=D("500000"), rate=D("0.05")),
            TaxSlab(up_to=D("1000000"), rate=D("0.20")),
            TaxSlab(up_to=None, rate=D("0.30")),
        ],
        standard_deduction=D("50000"),
        rebate=RebateConfig(
            taxable_income_limit=D("500000"),
            max_rebate=D("12500"),
            marginal_relief=False,
        ),
        surcharge_brackets=[
            SurchargeBracket(up_to=D("5000000"), rate=D("0")),
            SurchargeBracket(up_to=D("10000000"), rate=D("0.10")),
            SurchargeBracket(up_to=D("20000000"), rate=D("0.15")),
            SurchargeBracket(up_to=D("50000000"), rate=D("0.25")),
            SurchargeBracket(up_to=None, rate=D("0.37")),
        ],
        allow_chapter_via=True,
    )


def _year(fy: str, notes: str) -> TaxYearConfig:
    return TaxYearConfig(
        financial_year=fy,
        cess_rate=D("0.04"),
        old_regime=_old_regime(),
        new_regime=_new_regime(),
        deduction_caps=DeductionCapsConfig(),
        notes=notes,
    )


def default_tax_years() -> dict[str, TaxYearConfig]:
    return {
        "2025-26": _year("2025-26", "Finance Act 2025 defaults."),
        "2026-27": _year(
            "2026-27",
            "Budget 2026 carried forward FY 2025-26 slabs, 87A rebate, standard deduction, "
            "surcharge and cess unchanged.",
        ),
    }


DEFAULT_TAX_YEAR = "2026-27"


def default_income_tax_config() -> IncomeTaxConfig:
    return IncomeTaxConfig(default_year=DEFAULT_TAX_YEAR, years=default_tax_years())


def fy_label_for_date(d: date) -> str:
    """Indian financial year label (April–March) for a calendar date."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"
