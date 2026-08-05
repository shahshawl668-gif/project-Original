"""Tenant-level rule toggles — suppress findings by rule_id in validation output."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.models.base import Document, utcnow


@dataclass
class TenantRulePreference(Document):
    """When suppressed=True, findings with matching rule_id are hidden for this tenant."""

    COLLECTION = "tenant_rule_preferences"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID | None = None
    rule_id: str = ""
    suppressed: bool = True
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
