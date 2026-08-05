"""CTC upload and per-employee CTC record documents."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.models.base import Document, utcnow


@dataclass
class CtcUpload(Document):
    COLLECTION = "ctc_uploads"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID | None = None
    effective_from: date | None = None
    filename: str | None = None
    employee_count: int | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class CtcRecord(Document):
    COLLECTION = "ctc_records"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    upload_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    employee_id: str = ""
    employee_name: str | None = None
    effective_from: date | None = None
    annual_components: dict[str, Any] = field(default_factory=dict)
    annual_ctc: Decimal | None = None
    created_at: datetime = field(default_factory=utcnow)
