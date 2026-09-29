"""
Business events, written to the outbox.

``emit`` adds a ``studio_events`` row to the caller's session and never
commits: the event belongs to the same transaction as the change it
announces. If the change rolls back, so does the event; if the process dies
after the commit, the event is already safely stored and the worker fans it
out when it next runs. A change and its announcement can never disagree.

Payloads carry identifiers and states only — never pay figures, never
identity data. A subscriber that needs detail reads it through the
integration API, with a key scoped to see it.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import StudioEvent

PAYLOAD_VERSION = "2026-10-01"

#: Every event a webhook can subscribe to, and what its data holds.
CATALOGUE: dict[str, str] = {
    "import.completed": "An import or sync finished (completed, partially completed or failed): run id, "
                        "object type, status, reconciliation counts.",
    "validation.completed": "A month's validation finished: job id, run id, period.",
    "validation.failed": "A month's validation failed for good: job id, period, error code.",
    "finding.state_changed": "A finding was acknowledged, waived, resolved or reopened: fingerprint, from, to.",
    "period.submitted": "A month was submitted for approval: period, sign-off id.",
    "period.signed_off": "A month was signed off: period, sign-off id, snapshot digest.",
    "period.reopened": "A signed month was reopened: period, sign-off id.",
    "inbound.received": "A signed inbound webhook call was accepted: endpoint id, receipt id, run id.",
    "workflow.finished": "A workflow run finished: workflow id, run id, status.",
    "workflow.message": "Sent by a workflow's webhook action to one webhook: workflow id, run id, period.",
    "webhook.test": "A test event sent from Studio to one webhook.",
}


def emit(db: Session, *, org_id: Any, entity_id: Any, type: str, data: dict[str, Any],
         causation: dict[str, Any] | None = None, only_webhook_id: Any = None) -> StudioEvent:
    if type not in CATALOGUE:
        raise ValueError(f"Unknown event type {type}")
    event = StudioEvent(org_id=org_id, entity_id=entity_id, type=type, version=PAYLOAD_VERSION,
                        data=data, causation=causation or {}, only_webhook_id=only_webhook_id)
    db.add(event)
    return event


def envelope(event: StudioEvent) -> dict[str, Any]:
    """The body a subscriber receives."""
    return {
        "id": str(event.id),
        "type": event.type,
        "version": event.version,
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "company_id": str(event.entity_id),
        "data": event.data,
    }
