"""StatutoryConfig — config-driven statutory engine document.

Stores PF, ESIC, component-mapping, FY-versioned income tax, and rule-threshold
configs as nested documents. MongoDB stores these natively, so the config can
grow new sections without any migration — `ConfigService` reads and writes them
through typed Pydantic schemas and callers never touch the raw dicts.

One document per tenant (`user_id`, unique index).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models.base import Document, utcnow


@dataclass
class StatutoryConfig(Document):
    COLLECTION = "statutory_config"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID | None = None

    pf_config: dict[str, Any] = field(default_factory=dict)
    esic_config: dict[str, Any] = field(default_factory=dict)
    component_mapping_config: dict[str, Any] = field(default_factory=dict)
    # FY-versioned income-tax parameters and tunable rule-engine thresholds.
    # None means "use the seeded defaults" (see ConfigService).
    income_tax_config: dict[str, Any] | None = None
    rule_thresholds_config: dict[str, Any] | None = None

    updated_at: datetime = field(default_factory=utcnow)
