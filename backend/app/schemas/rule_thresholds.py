"""
Configurable thresholds used by the validation rule engine.

Previously these were literals inside rule_engine_v2.py / validation.py.
They are stored per tenant as JSON (statutory_config.rule_thresholds_config)
and every value can be edited via /api/config/rule-thresholds.

The Field defaults below are the seed values a new tenant starts with — they
mirror common India payroll audit practice but carry no legal force of their
own; tenants tune them to their policy.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


def _dec(v) -> Decimal:
    return Decimal(str(v))


class StructuralThresholds(BaseModel):
    """STRUCT-001 / STRUCT-002 — salary structure risk."""
    min_pf_wage_pct_of_gross: Decimal = Field(
        Decimal("30"), description="Below this PF-wage %% of gross, flag possible PF avoidance")
    recommended_pf_wage_pct: Decimal = Field(
        Decimal("40"), description="Recommended PF-wage %% of gross used in the suggested fix / impact estimate")
    allowance_heavy_pct: Decimal = Field(
        Decimal("70"), description="Above this allowance %% of gross, flag allowance-heavy structure")

    @field_validator("min_pf_wage_pct_of_gross", "recommended_pf_wage_pct", "allowance_heavy_pct", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class ToleranceThresholds(BaseModel):
    """Rupee tolerances before a mismatch is raised."""
    gross_mismatch: Decimal = Field(Decimal("2"), description="AGG-001 gross vs computed gross, ₹")
    net_mismatch: Decimal = Field(Decimal("5"), description="AGG-002 net vs computed net, ₹")
    statutory_mismatch: Decimal = Field(Decimal("1"), description="PF/ESIC/PT/LWF expected vs actual, ₹")

    @field_validator("gross_mismatch", "net_mismatch", "statutory_mismatch", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class TrendThresholds(BaseModel):
    """MOM-002/003 and ADV-002/003 — month-on-month movement."""
    component_change_pct: Decimal = Field(
        Decimal("30"), description="Component spike/drop %% vs prior month before MOM-002/003 fires")
    salary_spike_ratio: Decimal = Field(
        Decimal("3"), description="ADV-002: gross > this multiple of prior month")
    salary_drop_ratio: Decimal = Field(
        Decimal("0.25"), description="ADV-003: gross < this fraction of prior month")

    @field_validator("component_change_pct", "salary_spike_ratio", "salary_drop_ratio", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class TDSRiskThresholds(BaseModel):
    """STAT-011 — high-income month heuristic."""
    annual_income_threshold: Decimal = Field(
        Decimal("500000"),
        description="Annualised taxable income above which a high-income month is flagged, ₹")
    arrear_annualisation_factor: Decimal = Field(
        Decimal("0.3"), description="Fraction of the arrear total added to the month's taxable exposure")

    @field_validator("annual_income_threshold", "arrear_annualisation_factor", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class GratuityThresholds(BaseModel):
    """STAT-014 — Payment of Gratuity Act tax-exemption cap."""
    exemption_cap: Decimal = Field(Decimal("2000000"), description="₹20 lakh statutory tax-exempt cap")

    @field_validator("exemption_cap", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class RuleThresholdsConfig(BaseModel):
    """All tunable rule-engine thresholds for one tenant."""
    structural: StructuralThresholds = Field(default_factory=StructuralThresholds)
    tolerances: ToleranceThresholds = Field(default_factory=ToleranceThresholds)
    trends: TrendThresholds = Field(default_factory=TrendThresholds)
    tds: TDSRiskThresholds = Field(default_factory=TDSRiskThresholds)
    gratuity: GratuityThresholds = Field(default_factory=GratuityThresholds)
