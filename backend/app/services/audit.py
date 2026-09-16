"""Append-only record of who did what."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record(
    db: Session,
    *,
    entity_id: uuid.UUID | None,
    user: Any | None,
    action: str,
    object_type: str,
    summary: str,
    object_id: str | None = None,
    detail: dict | None = None,
) -> AuditEvent:
    """
    Write one audit row.

    Deliberately does not commit: the audit entry and the thing it describes
    belong to the same transaction. A trail that can survive a rolled-back
    change records events that never happened.
    """
    event = AuditEvent(
        entity_id=entity_id,
        user_id=getattr(user, "id", None),
        user_email=getattr(user, "email", None),
        action=action,
        object_type=object_type,
        object_id=object_id,
        summary=summary,
        detail=detail or {},
    )
    db.add(event)
    return event


def history(
    db: Session,
    entity_id: uuid.UUID,
    *,
    limit: int = 100,
    action: str | None = None,
) -> list[dict]:
    query = db.query(AuditEvent).filter(AuditEvent.entity_id == entity_id)
    if action:
        query = query.filter(AuditEvent.action == action)
    events = query.order_by(AuditEvent.created_at.desc()).limit(limit).all()
    return [
        {
            "id": str(e.id),
            "action": e.action,
            "object_type": e.object_type,
            "object_id": e.object_id,
            "summary": e.summary,
            "detail": e.detail or {},
            "user_email": e.user_email,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]
