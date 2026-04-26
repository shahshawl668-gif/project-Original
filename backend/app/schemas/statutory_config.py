"""
Pydantic schemas for the Config-Driven Statutory Engine.

These represent the *structured* config stored as JSONB in
`statutory_config.pf_config` / `statutory_config.esic_config`.

Design principles
-----------------
* Every field has a sensible default so a brand-new tenant gets working
  India-standard values without any setup.
* `include_components` / `exclude_components` drive the dynamic wage calc.
* `expression` in each rule lets advanced users write custom threshold
  logic without touching code.
* `voluntary_pf_components` allows "above-ceiling" PF contributions.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ─── PF ──────────────────────────────────────────────────────────────────────

class PFRateConfig(BaseModel):
    """Contribution rates — editable per tenant."""
    employee_rate:  Decimal = Field(Decimal("0.12"),  description="12% employee contribution")
    employer_rate:  Decimal = Field(Decimal("0.12"),  description="12% employer contribution")
    eps_rate:       Decimal = Field(Decimal("0.0833"), description="8.33% EPS (from employer share)")
    edli_rate:      Decimal = Field(Decimal("0.0050"), description="0.5% EDLI")
    admin_rate:     Decimal = Field(Decimal("0.0050"), description="0.5% admin charges")

    @field_validator("employee_rate", "employer_rate", "eps_rate", "edli_rate", "admin_rate", mode="before")
    @classmethod
    def _parse_decimal(cls, v):
        return Decimal(str(v))


class PFWageConfig(BaseModel):
    """Dynamic wage composition for PF."""
    # Flags that mirror ComponentConfig columns
    use_pf_applicable_flag: bool = Field(
        True,
        description=(
            "When True, sum all components where pf_applicable=True. "
            "When False, use include_components / exclude_components list."
        ),
    )
    # Alternative: explicit component names to include / exclude
    include_components: list[str] = Field(
        default_factory=list,
        description="Component names to include in PF wage (used when use_pf_applicable_flag=False).",
    )
    exclude_components: list[str] = Field(
        default_factory=list,
        description="Component names to exclude from PF wage even if pf_applicable=True.",
    )
    wage_ceiling:         Decimal = Field(Decimal("15000"), description="₹15,000 statutory ceiling")
    restrict_to_ceiling:  bool    = Field(True, description="Cap PF wage at ceiling (default True)")

    @field_validator("wage_ceiling", mode="before")
    @classmethod
    def _parse_decimal(cls, v):
        return Decimal(str(v))


class PFEligibilityConfig(BaseModel):
    """Rules to determine if an employee is PF-eligible."""
    # Expression evaluated with employee context; must return bool
    # Supported vars: gross, pf_wage, basic, employee_type
    # Example: "pf_wage > 0 and employee_type != 'contractor'"
    expression: str = Field("pf_wage > 0", description="Python-safe expression for eligibility")
    exempt_employment_types: list[str] = Field(
        default_factory=list,
        description="Employment types exempted from PF (e.g. ['contractor', 'intern'])",
    )


class VoluntaryPFConfig(BaseModel):
    """Voluntary PF above the statutory ceiling."""
    enabled: bool = Field(False)
    # Components contributing to voluntary PF (e.g. ["vpf"])
    components: list[str] = Field(default_factory=list)


class PFConfig(BaseModel):
    """Full PF configuration for one tenant."""
    rates:       PFRateConfig       = Field(default_factory=PFRateConfig)
    wage:        PFWageConfig       = Field(default_factory=PFWageConfig)
    eligibility: PFEligibilityConfig = Field(default_factory=PFEligibilityConfig)
    voluntary:   VoluntaryPFConfig   = Field(default_factory=VoluntaryPFConfig)
    # "none" | "employee_choice" | "employer_choice"
    above_ceiling_mode: Literal["none", "employee_choice", "employer_choice"] = "none"

    class Config:
        json_encoders = {Decimal: str}


# ─── ESIC ─────────────────────────────────────────────────────────────────────

class ESICRateConfig(BaseModel):
    employee_rate: Decimal = Field(Decimal("0.0075"), description="0.75% employee")
    employer_rate: Decimal = Field(Decimal("0.0325"), description="3.25% employer")

    @field_validator("employee_rate", "employer_rate", mode="before")
    @classmethod
    def _parse_decimal(cls, v):
        return Decimal(str(v))


class ESICWageConfig(BaseModel):
    use_esic_applicable_flag: bool = Field(
        True,
        description="When True sum all esic_applicable components; otherwise use include list.",
    )
    include_components: list[str] = Field(default_factory=list)
    exclude_components: list[str] = Field(default_factory=list)
    wage_ceiling: Decimal = Field(Decimal("21000"), description="₹21,000 ESIC eligibility ceiling")

    @field_validator("wage_ceiling", mode="before")
    @classmethod
    def _parse_decimal(cls, v):
        return Decimal(str(v))


class ESICRoundingConfig(BaseModel):
    mode: Literal["up", "down", "nearest"] = "up"
    # Advanced: expression override e.g. "ceil(esic_wage * 0.0075)"
    expression: str = Field(
        "",
        description="Leave blank to use rate * wage + round mode. Provide expression for custom logic.",
    )


class ESICEligibilityConfig(BaseModel):
    expression: str = Field(
        "esic_wage > 0 and esic_wage <= esic_ceiling",
        description="Python-safe expression. Vars: esic_wage, esic_ceiling, employee_type",
    )
    exempt_employment_types: list[str] = Field(default_factory=list)
    # Entry/exit: If employee joined mid-month, treat as eligible for whole month
    full_month_on_entry: bool = Field(True)
    # Exit: continue ESIC contribution for the month of exit
    continue_month_on_exit: bool = Field(True)


class ESICConfig(BaseModel):
    rates:       ESICRateConfig       = Field(default_factory=ESICRateConfig)
    wage:        ESICWageConfig        = Field(default_factory=ESICWageConfig)
    rounding:    ESICRoundingConfig    = Field(default_factory=ESICRoundingConfig)
    eligibility: ESICEligibilityConfig = Field(default_factory=ESICEligibilityConfig)

    class Config:
        json_encoders = {Decimal: str}


# ─── Component mapping override ───────────────────────────────────────────────

class ComponentMappingEntry(BaseModel):
    """Override how a column in the uploaded file maps to a component."""
    upload_column: str  = Field(..., description="Column name in uploaded file (normalized)")
    component_name: str = Field(..., description="Internal component name")
    pf_applicable:    bool = False
    esic_applicable:  bool = False
    included_in_wages: bool = True
    taxable:          bool = True


class ComponentMappingConfig(BaseModel):
    """Tenant-level alias/mapping overrides."""
    entries: list[ComponentMappingEntry] = Field(default_factory=list)
    # Columns to silently ignore if present in upload
    ignore_columns: list[str] = Field(default_factory=list)


# ─── Full tenant statutory config ─────────────────────────────────────────────

class TenantStatutoryConfig(BaseModel):
    """Aggregated config returned by ConfigService."""
    pf:               PFConfig               = Field(default_factory=PFConfig)
    esic:             ESICConfig             = Field(default_factory=ESICConfig)
    component_mapping: ComponentMappingConfig = Field(default_factory=ComponentMappingConfig)

    class Config:
        json_encoders = {Decimal: str}


# ─── API request/response schemas ────────────────────────────────────────────

class PFConfigUpdate(BaseModel):
    pf: PFConfig


class ESICConfigUpdate(BaseModel):
    esic: ESICConfig


class StatutoryConfigResponse(BaseModel):
    tenant_id: str
    pf:   PFConfig
    esic: ESICConfig
    component_mapping: ComponentMappingConfig
    updated_at: str | None = None
