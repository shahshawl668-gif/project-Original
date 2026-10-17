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

from datetime import date
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
    max_arrear_months: Decimal = Field(
        Decimal("12"),
        description="ARR-003: arrears spanning more than this many months are flagged for review")

    @field_validator("component_change_pct", "salary_spike_ratio", "salary_drop_ratio",
                     "max_arrear_months", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)


class TDSRiskThresholds(BaseModel):
    """STAT-011 — high-income month heuristic."""
    annual_income_threshold: Decimal = Field(
        Decimal("1275000"),
        description=("Annualised taxable income above which a month with no TDS is flagged, ₹. Default: "
                     "the new regime's nil-tax limit for FY 2026-27 (₹12 lakh after the 87A rebate, plus the "
                     "₹75,000 standard deduction). Lower it for an old-regime workforce."))
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
    no_pan_min_annual_income: Decimal = Field(
        Decimal("1275000"),
        description=("Annualised taxable pay at or below which no tax is due, so the no-PAN rate does not "
                     "apply (CBDT salary-TDS circular). Default: the new regime's nil-tax limit for FY 2026-27. "
                     "Used only when the month has no TDS projection."))

    @field_validator("min_working_age_years", "adult_age_years", "no_pan_tds_rate", "no_pan_min_annual_income",
                     mode="before")
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


class AttendanceThresholds(BaseModel):
    """
    ATT-* — attendance, and the pay that should follow from it.

    ``paid_days_basis`` is the one setting here that changes money. A month's
    loss-of-pay deduction is the daily rate times the days lost, and the daily
    rate is the monthly wage divided by this basis. Companies divide by the
    calendar days, by a fixed 26 (the six-day week the Payment of Wages Act and
    the gratuity formula both assume), or by a flat 30. The same employee, the
    same two days of LOP, gives three different deductions — so this is asked
    rather than assumed, and the finding says which basis it used.
    """

    paid_days_basis: str = Field(
        "calendar",
        description="How a daily rate is derived: 'calendar' (days in the month), "
                    "'fixed_26' or 'fixed_30'.",
    )
    day_tolerance: Decimal = Field(
        Decimal("0.05"),
        description="Attendance is quoted to half-days; a smaller gap is rounding, not a difference.")
    lop_pay_tolerance_pct: Decimal = Field(
        Decimal("2"),
        description="ATT-020: how far actual pay may sit from the LOP-adjusted figure, %% of a "
                    "full month, before the deduction is called missing.")
    overtime_multiplier: Decimal = Field(
        Decimal("2"),
        description="ATT-024: statutory overtime rate as a multiple of the ordinary rate. "
                    "Section 59 of the Factories Act sets twice ordinary wages; some state "
                    "rules and settlements differ.")
    overtime_hours_per_day: Decimal = Field(
        Decimal("8"),
        description="Hours in a standard working day, used to turn a daily rate into an "
                    "hourly one for the overtime check.")
    require_days_reconcile: bool = Field(
        True,
        description="ATT-010: where a file states present, paid leave, weekly off, holiday "
                    "and LOP, require them to sum to the month.")

    @field_validator("day_tolerance", "lop_pay_tolerance_pct", "overtime_multiplier",
                     "overtime_hours_per_day", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)

    @field_validator("paid_days_basis", mode="before")
    @classmethod
    def _basis(cls, v):
        allowed = {"calendar", "fixed_26", "fixed_30"}
        text = str(v or "calendar").strip().lower()
        if text not in allowed:
            raise ValueError(f"paid_days_basis must be one of: {', '.join(sorted(allowed))}")
        return text


class LabourCodeThresholds(BaseModel):
    """
    LC-001 and the fixed-term gratuity relaxation — the four Labour Codes,
    in force from 21 November 2025.

    The Code on Wages, s.2(y) (and the Social Security Code, s.2(88)) define
    wages as Basic, DA and retaining allowance, then add back whatever the
    exclusions — HRA, conveyance, overtime, commission and the rest — pay above
    half of all remuneration. The Social Security Code, s.53, gives a
    fixed-term employee gratuity after one year rather than five.

    These are seed values from the Codes as notified. They carry no legal force
    here; the D6 sign-off is where a payroll expert confirms them.
    """

    effective_from: date = Field(
        date(2025, 11, 21),
        description="The Codes apply to pay periods ending on or after this date, and to exits on or after it")
    wage_exclusion_cap_pct: Decimal = Field(
        Decimal("50"),
        description="Exclusions above this %% of remuneration are deemed wages (s.2(y) proviso)")
    wage_component_keys: list[str] = Field(
        default_factory=list,
        description="Components that are wages (Basic, DA, retaining allowance). Empty: the PF-applicable components")
    one_off_component_keys: list[str] = Field(
        default_factory=lambda: ["gratuity", "leave_encashment", "retrenchment_compensation", "notice_pay",
                                 "bonus", "ex_gratia"],
        description="One-off payments — exit payments, annual bonus, ex gratia — left out of the monthly "
                    "50%% test. A company paying bonus monthly removes 'bonus'")
    fixed_term_gratuity_min_years: Decimal = Field(
        Decimal("1"), description="Service after which a fixed-term employee earns gratuity (s.53)")
    fixed_term_markers: list[str] = Field(
        default_factory=lambda: ["fixed term", "fixed term employee", "fixed term contract", "ftc"],
        description="Employment types that mean fixed-term (case, hyphens and underscores ignored)")

    @field_validator("wage_exclusion_cap_pct", "fixed_term_gratuity_min_years", mode="before")
    @classmethod
    def _parse(cls, v):
        return _dec(v)

    @field_validator("wage_exclusion_cap_pct")
    @classmethod
    def _cap(cls, v: Decimal) -> Decimal:
        if not Decimal("0") <= v <= Decimal("100"):
            raise ValueError("wage_exclusion_cap_pct must be between 0 and 100")
        return v


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
    attendance: AttendanceThresholds = Field(default_factory=AttendanceThresholds)
    labour_codes: LabourCodeThresholds = Field(default_factory=LabourCodeThresholds)
