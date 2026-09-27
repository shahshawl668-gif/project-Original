from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Source = Literal["field", "component", "deduction", "literal"]
Operator = Literal["eq", "ne", "gt", "gte", "lt", "lte"]


class Operand(BaseModel):
    source: Source
    key: str | None = Field(default=None, max_length=100)
    value: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def valid_source(self):
        if self.source == "literal" and self.value is None:
            raise ValueError("A literal needs a value")
        if self.source != "literal" and not self.key:
            raise ValueError("Select a field or component")
        return self


class Comparison(BaseModel):
    left: Operand
    operator: Operator
    right: Operand
    tolerance: str = "0"


class RuleCreate(BaseModel):
    rule_key: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{2,31}$")
    name: str = Field(min_length=3, max_length=255)
    category: Literal["custom", "statutory"] = "custom"
    effective_from: date
    effective_to: date | None = None
    state: str | None = Field(default=None, max_length=100)
    condition: Comparison | None = None
    conditions: list[Comparison] = Field(default_factory=list, max_length=5)
    condition_mode: Literal["all", "any"] = "all"
    assertion: Comparison
    severity: Literal["CRITICAL", "WARNING", "INFO"] = "WARNING"
    blocks_signoff: bool = False
    responsible_team: str | None = Field(default=None, max_length=100)
    suggested_fix: str | None = Field(default=None, max_length=2000)
    source_reference: str | None = Field(default=None, max_length=1000)
    change_reason: str = Field(min_length=8, max_length=2000)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("End date must be on or after start date")
        if self.condition and self.conditions:
            raise ValueError("Use either a single condition or a condition group")
        if self.category == "statutory" and not self.source_reference:
            raise ValueError("Statutory rules need an official source reference")
        return self


class SimulationRequest(BaseModel):
    period_month: date
    limit: int = Field(default=100, ge=1, le=500)
