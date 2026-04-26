from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

RuleTypeFormula = Literal["PF", "ESIC"]
RuleTypeSlab = Literal["PT", "LWF"]
Frequency = Literal["monthly", "yearly", "half-yearly", "quarterly"]
ConditionOperator = Literal[">", "<", ">=", "<=", "==", "!="]
Gender = Literal["ALL", "MALE", "FEMALE"]


class Condition(BaseModel):
    field: str
    operator: ConditionOperator
    value: float


class FormulaCreate(BaseModel):
    rule_type: RuleTypeFormula
    name: str | None = None
    expression: str = Field(min_length=1)
    conditions: list[Condition] = Field(default_factory=list)
    activate: bool = True


class FormulaOut(BaseModel):
    id: str
    rule_type: RuleTypeFormula
    name: str | None
    expression: str
    conditions: list[Condition]
    version: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def _id_to_str(cls, v):
        return str(v)


class TestFormulaRequest(BaseModel):
    expression: str = Field(min_length=1)
    conditions: list[Condition] = Field(default_factory=list)
    variables: dict[str, float] = Field(default_factory=dict)


class TestFormulaResponse(BaseModel):
    ok: bool
    result: float | None = None
    conditions_passed: bool | None = None
    error: str | None = None


class SlabRow(BaseModel):
    min_salary: Decimal
    max_salary: Decimal
    # PT: employee deduction.   LWF: employee contribution per period.
    deduction_amount: Decimal
    # LWF only — employer contribution per period. None/0 for PT rows.
    employer_amount: Decimal | None = None
    frequency: Frequency = "monthly"
    gender: Gender = "ALL"
    # Months 1..12 the row applies in. None / [] = every month.
    applicable_months: list[int] | None = None

    @field_validator("applicable_months", mode="before")
    @classmethod
    def _coerce_months(cls, v):
        if v in (None, "", []):
            return None
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",") if p.strip()]
            v = [int(p) for p in parts]
        try:
            cleaned = sorted({int(x) for x in v})
        except (TypeError, ValueError) as e:
            raise ValueError(f"applicable_months must be 1..12 ints: {e}")
        for m in cleaned:
            if m < 1 or m > 12:
                raise ValueError(f"applicable_months entries must be 1..12 (got {m})")
        return cleaned or None


class SlabSaveRequest(BaseModel):
    state: str = Field(min_length=1, max_length=100)
    rule_type: RuleTypeSlab
    slabs: list[SlabRow]


class SlabRowOut(SlabRow):
    id: str

    @field_validator("id", mode="before")
    @classmethod
    def _id_to_str(cls, v):
        return str(v)


class SlabsResponse(BaseModel):
    state: str
    rule_type: RuleTypeSlab
    slabs: list[SlabRowOut]
