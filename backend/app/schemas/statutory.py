from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class StatutorySettingsBase(BaseModel):
    pf_wage_ceiling: Decimal = Field(default=Decimal("15000"))
    pf_employee_rate: Decimal = Field(default=Decimal("0.12"))
    pf_employer_rate: Decimal = Field(default=Decimal("0.12"))
    pf_eps_rate: Decimal = Field(default=Decimal("0.0833"))
    pf_edli_rate: Decimal = Field(default=Decimal("0.0050"))
    pf_admin_rate: Decimal = Field(default=Decimal("0.0050"))
    pf_restrict_to_ceiling: bool = True

    esic_wage_ceiling: Decimal = Field(default=Decimal("21000"))
    esic_employee_rate: Decimal = Field(default=Decimal("0.0075"))
    esic_employer_rate: Decimal = Field(default=Decimal("0.0325"))
    esic_round_mode: Literal["up", "nearest", "down"] = "up"

    pt_states: list[str] = Field(default_factory=list)
    lwf_states: list[str] = Field(default_factory=list)


class StatutorySettingsUpdate(BaseModel):
    pf_wage_ceiling: Decimal | None = None
    pf_employee_rate: Decimal | None = None
    pf_employer_rate: Decimal | None = None
    pf_eps_rate: Decimal | None = None
    pf_edli_rate: Decimal | None = None
    pf_admin_rate: Decimal | None = None
    pf_restrict_to_ceiling: bool | None = None

    esic_wage_ceiling: Decimal | None = None
    esic_employee_rate: Decimal | None = None
    esic_employer_rate: Decimal | None = None
    esic_round_mode: Literal["up", "nearest", "down"] | None = None

    pt_states: list[str] | None = None
    lwf_states: list[str] | None = None


class StatutorySettingsOut(StatutorySettingsBase):
    updated_at: datetime

    model_config = {"from_attributes": True}
