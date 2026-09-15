from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class MinimumWageRateIn(BaseModel):
    state: str = Field(min_length=1, max_length=100)
    zone: str = Field(default="*", max_length=64)
    scheduled_employment: str = Field(default="*", max_length=255)
    skill_category: str = Field(min_length=1, max_length=64)
    basic_per_month: Decimal = Decimal("0")
    vda_per_month: Decimal = Decimal("0")
    working_days_basis: Decimal = Decimal("26")
    effective_from: date
    effective_to: date | None = None
    source_reference: str | None = Field(default=None, max_length=512)


class MinimumWageRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    state: str
    zone: str
    scheduled_employment: str
    skill_category: str
    basic_per_month: Decimal
    vda_per_month: Decimal
    working_days_basis: Decimal
    effective_from: date
    effective_to: date | None
    source_reference: str | None


class MinimumWageImport(BaseModel):
    rates: list[MinimumWageRateIn]
    # Replace the whole table rather than merging — used when a practice
    # re-loads a corrected schedule wholesale.
    replace: bool = False
