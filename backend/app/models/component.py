"""Salary component configuration document."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.models.base import Document, utcnow


@dataclass
class ComponentConfig(Document):
    COLLECTION = "components_config"

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID | None = None
    component_name: str = ""
    pf_applicable: bool = False
    esic_applicable: bool = False
    pt_applicable: bool = False
    lwf_applicable: bool = False
    bonus_applicable: bool = False
    included_in_wages: bool = False
    taxable: bool = False
    tax_exemption_type: str = "none"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
