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
    org_id: uuid.UUID | None = None,
) -> AuditEvent:
    """
    Write one audit row.

    Deliberately does not commit: the audit entry and the thing it describes
    belong to the same transaction. A trail that can survive a rolled-back
    change records events that never happened.
    """
    event = AuditEvent(
        entity_id=entity_id,
        org_id=org_id,
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
    org_id: uuid.UUID | None = None,
) -> list[dict]:
    """
    The trail for one entity, plus the organization-level events around it.

    Membership changes belong to the organization rather than to any one
    entity, so they carry no ``entity_id``. Reading only by entity would write
    them and never show them. ``org_id`` is required to see them, and scopes
    them, so one organization's membership history never reaches another.
    """
    from sqlalchemy import or_

    scope = AuditEvent.entity_id == entity_id
    if org_id is not None:
        scope = or_(scope, AuditEvent.org_id == org_id)
    query = db.query(AuditEvent).filter(scope)
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
