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


class IdentityThresholds(BaseModel):
    """ID-* rules — working-age limits and no-PAN TDS."""
    min_working_age_years: Decimal = Field(Decimal("14"), description="Below this age: child labour, ERROR")
    adult_age_years: Decimal = Field(Decimal("18"), description="14-18 flagged unless adolescent permit column set")
    no_pan_tds_rate: Decimal = Field(Decimal("0.20"), description="Sec 206AA flat TDS rate when PAN is missing")

    @field_validator("min_working_age_years", "adult_age_years", "no_pan_tds_rate", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class PFDeepThresholds(BaseModel):
    """PF-* rules — EPS split and international workers (EPF & MP Act / EPS-95)."""
    eps_wage_cap: Decimal = Field(Decimal("15000"), description="EPS contribution base cap")
    eps_rate: Decimal = Field(Decimal("0.0833"), description="EPS share of employer contribution")
    eps_join_cutoff: str = Field("2014-09-01", description="Joiners on/after this date with wages above cap get EPS 0")
    eps_max_age_years: Decimal = Field(Decimal("58"), description="EPS stops at this age; full 12% to EPF")

    @field_validator("eps_wage_cap", "eps_rate", "eps_max_age_years", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class ESIDeepThresholds(BaseModel):
    """ESI-* rules beyond the base engine."""
    disability_wage_ceiling: Decimal = Field(Decimal("25000"), description="Coverage ceiling for employees with disability")
    daily_wage_exemption_limit: Decimal = Field(Decimal("176"), description="Avg daily wage at/below which employee share is exempt")

    @field_validator("disability_wage_ceiling", "daily_wage_exemption_limit", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class PTCapThresholds(BaseModel):
    """PT-* rules — constitutional cap and no-PT states."""
    annual_cap: Decimal = Field(Decimal("2500"), description="Article 276 annual PT cap per employee")
    no_pt_states: list[str] = Field(
        default_factory=lambda: [
            "Delhi", "Haryana", "Uttar Pradesh", "Rajasthan", "Uttarakhand",
            "Himachal Pradesh", "Jammu & Kashmir", "Ladakh", "Goa",
            "Arunachal Pradesh", "Chandigarh",
        ],
        description="States/UTs with no Professional Tax — any PT deducted there is an error",
    )

    @field_validator("annual_cap", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class BonusThresholds(BaseModel):
    """BON-* rules — Payment of Bonus Act, 1965."""
    eligibility_wage_ceiling: Decimal = Field(Decimal("21000"), description="Basic+DA at/below this: statutory-bonus eligible")
    calc_base_floor: Decimal = Field(Decimal("7000"), description="Calculation base: min(Basic+DA, this floor or state min wage)")
    min_rate: Decimal = Field(Decimal("0.0833"), description="Minimum statutory bonus rate")
    max_rate: Decimal = Field(Decimal("0.20"), description="Maximum statutory bonus rate")

    @field_validator("eligibility_wage_ceiling", "calc_base_floor", "min_rate", "max_rate", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class GratuityFormulaThresholds(BaseModel):
    """GRAT-* rules — Payment of Gratuity Act, 1972 formula check."""
    factor_numerator: Decimal = Field(Decimal("15"), description="Days of wages per completed year")
    factor_denominator: Decimal = Field(Decimal("26"), description="Working days divisor")
    min_service_years: Decimal = Field(Decimal("5"), description="Continuous service required (waived on death/disablement)")
    amount_tolerance_pct: Decimal = Field(Decimal("2"), description="Allowed % deviation from formula amount")

    @field_validator("factor_numerator", "factor_denominator", "min_service_years", "amount_tolerance_pct", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class TDSDeepThresholds(BaseModel):
    """TDS-* rules — Sec 192 monthly deduction vs annual projection."""
    projection_tolerance_abs: Decimal = Field(Decimal("100"), description="₹ tolerance vs projected monthly TDS")
    projection_tolerance_pct: Decimal = Field(Decimal("5"), description="% tolerance vs projected monthly TDS")

    @field_validator("projection_tolerance_abs", "projection_tolerance_pct", mode="before")
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
    identity: IdentityThresholds = Field(default_factory=IdentityThresholds)
    pf_deep: PFDeepThresholds = Field(default_factory=PFDeepThresholds)
    esi_deep: ESIDeepThresholds = Field(default_factory=ESIDeepThresholds)
    pt_caps: PTCapThresholds = Field(default_factory=PTCapThresholds)
    bonus: BonusThresholds = Field(default_factory=BonusThresholds)
    gratuity_formula: GratuityFormulaThresholds = Field(default_factory=GratuityFormulaThresholds)
    tds_deep: TDSDeepThresholds = Field(default_factory=TDSDeepThresholds)
