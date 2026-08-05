"""Rule-engine documents — user-authored formulas and tenant PT/LWF slabs."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.models.base import Document, utcnow


@dataclass
class Formula(Document):
    """User-authored PF / ESIC formula. Each save creates a new version."""

    COLLECTION = "rule_formulas"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID | None = None
    rule_type: str = ""  # PF | ESIC
    name: str | None = None
    expression: str = ""
    conditions: list[dict[str, Any]] = field(default_factory=list)
    version: int = 1
    is_active: bool = True
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class SlabRule(Document):
    """Tenant-managed PT / LWF slab. Replaces seeded reference data when present."""

    COLLECTION = "slab_rules"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID | None = None
    state: str = ""
    rule_type: str = ""  # PT | LWF
    min_salary: Decimal = Decimal("0")
    max_salary: Decimal = Decimal("0")
    # For PT: employee deduction. For LWF: employee contribution.
    deduction_amount: Decimal = Decimal("0")
    # LWF only: employer contribution per period (None/0 for PT rows).
    employer_amount: Decimal | None = None
    frequency: str = "monthly"
    # Gender filter: "ALL" | "MALE" | "FEMALE". States like Maharashtra publish
    # different slabs by gender; "ALL" means the slab applies regardless.
    gender: str = "ALL"
    # Optional month numbers (1-12) the slab applies to. None/empty means every
    # month. Used for Feb-only top-up rows that round annual PT to the cap.
    applicable_months: list[int] | None = None
    sort_order: int = 0
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
