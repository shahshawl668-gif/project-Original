"""Seeded reference data — PT slabs and LWF rates.

These are the month-blind fallbacks used when a tenant has not imported state
slabs of its own (see `services/pt_defaults.py` and `services/lwf_defaults.py`
for the richer, importable catalogs).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from app.models.base import Document, utcnow


@dataclass
class PtSlab(Document):
    COLLECTION = "pt_slabs"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    state: str = ""
    slab_min: Decimal = Decimal("0")
    slab_max: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    effective_from: date | None = None
    effective_to: date | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class LwfRate(Document):
    COLLECTION = "lwf_rates"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    state: str = ""
    wage_band_min: Decimal = Decimal("0")
    wage_band_max: Decimal = Decimal("0")
    employee_rate: Decimal = Decimal("0")
    employer_rate: Decimal = Decimal("0")
    effective_from: date | None = None
    effective_to: date | None = None
    created_at: datetime = field(default_factory=utcnow)
