from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class FindingStateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fingerprint: str
    employee_id: str
    employee_name: str | None
    rule_id: str
    rule_name: str
    component: str | None
    severity: str
    state: str
    first_seen_period: date
    last_seen_period: date
    occurrence_count: int
    last_financial_impact: Decimal
    resolved_period: date | None
    note: str | None
    waiver_reason: str | None
    waived_until: date | None
    decided_at: datetime | None


class FindingDecision(BaseModel):
    """A human decision on one fingerprint."""

    state: str = Field(pattern="^(open|acknowledged|waived|resolved)$")
    # Required when waiving: an accepted exception with no stated grounds is
    # indistinguishable from one that was never looked at.
    reason: str | None = Field(default=None, max_length=2000)
    waived_until: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class FindingEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_state: str | None
    to_state: str
    reason: str | None
    waived_until: date | None
    actor_email: str | None
    created_at: datetime | None


class ValidationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    period_month: date
    employee_count: int
    total_findings: int
    critical_count: int
    warning_count: int
    total_financial_impact: Decimal
    open_financial_impact: Decimal
    created_at: datetime | None
