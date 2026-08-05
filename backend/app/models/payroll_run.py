"""Payroll run document — one per uploaded/validated register."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from app.models.base import Document, utcnow


@dataclass
class PayrollRun(Document):
    COLLECTION = "payroll_runs"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID | None = None
    run_type: str = "regular"
    effective_month_from: date | None = None
    effective_month_to: date | None = None
    filename: str | None = None
    employee_count: int | None = None
    created_at: datetime = field(default_factory=utcnow)
