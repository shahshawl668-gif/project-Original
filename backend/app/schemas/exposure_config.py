"""
Configurable parameters for statutory exposure.

Under-deduction does not stay the size it was. PF attracts interest under
section 7Q and damages under section 14B, both accruing with delay, and ESIC
carries its own interest — so an old shortfall is worth materially more than a
new one of the same amount. Sizing that is the difference between "we missed
₹40,000" and "we are exposed to roughly ₹62,000".

Everything here is configurable and carries no legal force of its own. The
defaults follow the rates and the graded damages slabs in common use; a tenant
whose advisers read them differently, or for whom the law has since moved,
edits them rather than waiting for a release. That is the same principle the
rest of this codebase applies to statutory values.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


def _dec(v) -> Decimal:
    return Decimal(str(v))


class DamagesSlab(BaseModel):
    """Damages rate for arrears delayed within a band of months."""

    up_to_months: int | None = Field(
        None, description="Upper bound of the delay band in months; null means no upper bound"
    )
    annual_rate_pct: Decimal = Field(Decimal("5"), description="Damages rate, %% per annum")

    @field_validator("annual_rate_pct", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class PFExposureConfig(BaseModel):
    interest_annual_pct: Decimal = Field(
        Decimal("12"), description="Simple interest on delayed PF dues (s.7Q), %% per annum"
    )
    damages_slabs: list[DamagesSlab] = Field(
        default_factory=lambda: [
            DamagesSlab(up_to_months=2, annual_rate_pct=Decimal("5")),
            DamagesSlab(up_to_months=4, annual_rate_pct=Decimal("10")),
            DamagesSlab(up_to_months=6, annual_rate_pct=Decimal("15")),
            DamagesSlab(up_to_months=None, annual_rate_pct=Decimal("25")),
        ],
        description="Graded damages by length of delay (s.14B)",
    )
    damages_cap_pct_of_arrears: Decimal = Field(
        Decimal("100"), description="Damages ceiling as a %% of the arrear amount"
    )

    @field_validator("interest_annual_pct", "damages_cap_pct_of_arrears", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class ESICExposureConfig(BaseModel):
    interest_annual_pct: Decimal = Field(
        Decimal("12"), description="Simple interest on delayed ESIC contributions, %% per annum"
    )

    @field_validator("interest_annual_pct", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class ExposureConfig(BaseModel):
    pf: PFExposureConfig = Field(default_factory=PFExposureConfig)
    esic: ESICExposureConfig = Field(default_factory=ESICExposureConfig)
    # Rule ids whose financial impact is treated as a PF / ESIC shortfall. Held
    # as configuration because tenants add their own rules through the rule
    # engine and need those to count towards exposure too.
    pf_rule_prefixes: list[str] = Field(default_factory=lambda: ["PF-", "STAT-001", "STAT-002", "STAT-003"])
    esic_rule_prefixes: list[str] = Field(default_factory=lambda: ["ESI-", "STAT-004", "STAT-005"])
    pt_rule_prefixes: list[str] = Field(default_factory=lambda: ["PT-", "STAT-006", "STAT-007"])
    tds_rule_prefixes: list[str] = Field(default_factory=lambda: ["TDS-", "STAT-011"])
