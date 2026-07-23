"""
Pydantic schemas for the configurable income-tax engine.

Nothing statutory is hardcoded in the engine: slabs, rebates, surcharge
brackets, cess, standard deductions, and Chapter VI-A caps all live here and
are stored per tenant as JSON (statutory_config.income_tax_config).

Financial years are first-class: a tenant keeps one `TaxYearConfig` per FY
("2025-26", "2026-27", …) and picks a default. Seed values for known years
come from `app.services.tax_year_defaults` — they are only *defaults* and can
be edited through the API/UI at any time.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


def _dec(v) -> Decimal:
    return Decimal(str(v))


class TaxSlab(BaseModel):
    """One progressive slab. `up_to=None` means "no upper bound"."""
    up_to: Decimal | None = Field(None, description="Upper bound of the slab in ₹; null = infinity")
    rate: Decimal = Field(..., description="Tax rate as a fraction, e.g. 0.05 for 5%")

    @field_validator("up_to", "rate", mode="before")
    @classmethod
    def _parse_decimal(cls, v):
        return None if v is None else _dec(v)


class RebateConfig(BaseModel):
    """Section 87A style rebate."""
    taxable_income_limit: Decimal = Field(Decimal("0"), description="Rebate applies up to this taxable income")
    max_rebate: Decimal = Field(Decimal("0"), description="Maximum rebate amount in ₹")
    marginal_relief: bool = Field(False, description="Apply marginal relief just above the limit")

    @field_validator("taxable_income_limit", "max_rebate", mode="before")
    @classmethod
    def _parse_decimal(cls, v):
        return _dec(v)


class SurchargeBracket(BaseModel):
    up_to: Decimal | None = Field(None, description="Taxable income upper bound in ₹; null = infinity")
    rate: Decimal = Field(Decimal("0"), description="Surcharge rate as fraction of tax, e.g. 0.10")

    @field_validator("up_to", "rate", mode="before")
    @classmethod
    def _parse_decimal(cls, v):
        return None if v is None else _dec(v)


class RegimeConfig(BaseModel):
    """Everything needed to compute tax under one regime."""
    label: str = Field("", description="Display label, e.g. 'New Regime'")
    slabs: list[TaxSlab] = Field(default_factory=list)
    standard_deduction: Decimal = Field(Decimal("0"), description="Standard deduction for salaried, ₹")
    rebate: RebateConfig = Field(default_factory=RebateConfig)
    surcharge_brackets: list[SurchargeBracket] = Field(default_factory=list)
    allow_chapter_via: bool = Field(False, description="Whether Chapter VI-A deductions apply")

    @field_validator("standard_deduction", mode="before")
    @classmethod
    def _parse_decimal(cls, v):
        return _dec(v)


class DeductionCapsConfig(BaseModel):
    """Chapter VI-A caps (old regime)."""
    section_80c: Decimal = Field(Decimal("150000"))
    section_80d: Decimal = Field(Decimal("100000"), description="Combined self + parents cap used by the validator")
    section_80ccd_1b: Decimal = Field(Decimal("50000"))
    home_loan_interest: Decimal = Field(Decimal("200000"), description="Section 24(b), self-occupied")

    @field_validator("section_80c", "section_80d", "section_80ccd_1b", "home_loan_interest", mode="before")
    @classmethod
    def _parse_decimal(cls, v):
        return _dec(v)


class TaxYearConfig(BaseModel):
    """Complete income-tax parameters for one financial year."""
    financial_year: str = Field(..., description="e.g. '2026-27' (April–March)")
    cess_rate: Decimal = Field(Decimal("0.04"), description="Health & education cess on tax + surcharge")
    old_regime: RegimeConfig = Field(default_factory=RegimeConfig)
    new_regime: RegimeConfig = Field(default_factory=RegimeConfig)
    deduction_caps: DeductionCapsConfig = Field(default_factory=DeductionCapsConfig)
    notes: str = Field("", description="Free-text provenance, e.g. 'Budget 2026 — no rate changes'")

    @field_validator("cess_rate", mode="before")
    @classmethod
    def _parse_decimal(cls, v):
        return _dec(v)


class IncomeTaxConfig(BaseModel):
    """Tenant-level income tax configuration: one entry per financial year."""
    default_year: str = Field("", description="FY used when a request doesn't specify one")
    years: dict[str, TaxYearConfig] = Field(default_factory=dict)

    def resolve_year(self, financial_year: str | None = None) -> TaxYearConfig | None:
        fy = financial_year or self.default_year
        if fy and fy in self.years:
            return self.years[fy]
        if self.years:
            # Fall back to the lexically newest year (labels sort correctly)
            return self.years[sorted(self.years)[-1]]
        return None


# ── API request/response helpers ─────────────────────────────────────────────

class TaxYearUpsert(BaseModel):
    year: TaxYearConfig
    make_default: bool = False
