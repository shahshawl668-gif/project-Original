from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Source = Literal["field", "component", "deduction", "literal", "previous", "master", "expr"]
Operator = Literal["eq", "ne", "gt", "gte", "lt", "lte", "present", "in", "not_in"]


class Operand(BaseModel):
    source: Source
    key: str | None = Field(default=None, max_length=100)
    value: str | None = Field(default=None, max_length=500)
    # For ``previous``: which kind of input last month's value is read from.
    of: Literal["field", "component", "deduction"] | None = None

    @model_validator(mode="after")
    def valid_source(self):
        if self.source in ("literal", "expr") and not (self.value or "").strip():
            raise ValueError("A fixed value needs a value" if self.source == "literal" else "Write the expression")
        if self.source not in ("literal", "expr") and not self.key:
            raise ValueError("Select a field or component")
        return self


class Comparison(BaseModel):
    left: Operand
    operator: Operator
    right: Operand
    tolerance: str = "0"


class Group(BaseModel):
    """Comparisons or further groups, joined by all/any, optionally negated."""

    mode: Literal["all", "any"] = "all"
    negate: bool = False
    items: list[Comparison | Group] = Field(min_length=1, max_length=20)


Group.model_rebuild()


class RuleCreate(BaseModel):
    rule_key: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{2,31}$")
    name: str = Field(min_length=3, max_length=255)
    category: Literal["custom", "statutory"] = "custom"
    effective_from: date
    effective_to: date | None = None
    state: str | None = Field(default=None, max_length=100)
    # Basic mode: one condition, or a flat list joined by condition_mode.
    condition: Comparison | None = None
    conditions: list[Comparison] = Field(default_factory=list, max_length=5)
    condition_mode: Literal["all", "any"] = "all"
    # Advanced mode: a nested group.
    condition_group: Group | None = None
    assertion: Comparison
    applies_to: dict[str, list[str]] | None = None
    on_missing: Literal["cannot_validate", "skip", "fail"] = "cannot_validate"
    editor_mode: Literal["basic", "advanced"] = "basic"
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
        if sum(bool(x) for x in (self.condition, self.conditions, self.condition_group)) > 1:
            raise ValueError("Use one of: a single condition, a condition list, or a condition group")
        if self.category == "statutory" and not self.source_reference:
            raise ValueError("Statutory rules need an official source reference")
        return self

    def stored_condition(self) -> dict | None:
        if self.condition_group:
            return self.condition_group.model_dump()
        if self.conditions:
            return {"mode": self.condition_mode, "items": [c.model_dump() for c in self.conditions]}
        return self.condition.model_dump() if self.condition else None

    def stored_applies_to(self) -> dict | None:
        cleaned = {k: [v.strip() for v in vals if v and v.strip()] for k, vals in (self.applies_to or {}).items()}
        return {k: v for k, v in cleaned.items() if v} or None


class SimulationRequest(BaseModel):
    period_month: date
    limit: int = Field(default=100, ge=1, le=500)


class ImpactRequest(BaseModel):
    period_month: date


class CloneRequest(BaseModel):
    rule_key: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_-]{2,31}$")
    change_reason: str = Field(min_length=8, max_length=2000)


class RetireRequest(BaseModel):
    effective_to: date
    reason: str = Field(min_length=8, max_length=2000)


class ReturnRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=2000)


class CopyRequest(BaseModel):
    rule_ids: list[str] = Field(min_length=1, max_length=100)
    target_entity_ids: list[str] = Field(min_length=1, max_length=50)
    change_reason: str = Field(min_length=8, max_length=2000)
    dry_run: bool = True
