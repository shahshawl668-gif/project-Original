"""Legacy statutory settings document (PF/ESIC rates + PT/LWF state lists).

The config-driven engine (`statutory_config`) supersedes the PF/ESIC fields
here, but PT/LWF state lists still live on this document.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.models.base import Document, utcnow


@dataclass
class StatutorySettings(Document):
    COLLECTION = "statutory_settings"

    # One document per tenant; `user_id` is the natural key (unique index).
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    user_id: uuid.UUID | None = None

    # PF
    pf_wage_ceiling: Decimal = Decimal("15000")
    pf_employee_rate: Decimal = Decimal("0.12")
    pf_employer_rate: Decimal = Decimal("0.12")
    pf_eps_rate: Decimal = Decimal("0.0833")
    pf_edli_rate: Decimal = Decimal("0.0050")
    pf_admin_rate: Decimal = Decimal("0.0050")
    pf_restrict_to_ceiling: bool = True

    # ESIC
    esic_wage_ceiling: Decimal = Decimal("21000")
    esic_employee_rate: Decimal = Decimal("0.0075")
    esic_employer_rate: Decimal = Decimal("0.0325")
    esic_round_mode: str = "up"

    # PT and LWF can apply across multiple states for one tenant. Per-employee
    # state comes from the salary register row ("state" column); these lists are
    # the allowed states and the fallback default when a row has no state.
    pt_states: list[str] = field(default_factory=list)
    lwf_states: list[str] = field(default_factory=list)

    updated_at: datetime = field(default_factory=utcnow)
