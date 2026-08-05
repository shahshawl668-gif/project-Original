"""Stored salary register documents — one register per tenant per month.

Rows live in their own collection rather than embedded in the register: a
register can hold tens of thousands of employees, and month-on-month rules
query rows directly by (user_id, period_month, employee_id).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.models.base import Document, utcnow


@dataclass
class SalaryRegister(Document):
    COLLECTION = "salary_registers"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID | None = None
    period_month: date | None = None
    filename: str | None = None
    employee_count: int | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class SalaryRegisterRow(Document):
    COLLECTION = "salary_register_rows"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    register_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    period_month: date | None = None
    employee_id: str = ""
    employee_name: str | None = None
    paid_days: Decimal | None = None
    lop_days: Decimal | None = None
    components: dict[str, Any] = field(default_factory=dict)
    arrears: dict[str, Any] = field(default_factory=dict)
    increment_arrear_total: Decimal | None = Decimal("0")
    created_at: datetime = field(default_factory=utcnow)
