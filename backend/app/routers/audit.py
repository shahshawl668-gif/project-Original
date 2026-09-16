"""
The audit trail.

Uploads, approvals, configuration changes and exports, newest first. Read-only
by construction — there is no endpoint here that edits or removes an event,
because a trail that can be edited is not one.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user
from app.envelope import ok
from app.models import Entity, User
from app.services import audit

router = APIRouter()


@router.get("")
def trail(
    limit: int = Query(default=100, ge=1, le=1000),
    action: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """Who uploaded, approved, changed or exported what."""
    return ok({"events": audit.history(db, entity.id, limit=limit, action=action)})


@router.get("/actions")
def actions():
    """The action names the trail uses, so a filter can offer real options."""
    return ok({
        "actions": [
            {"key": "register.uploaded", "label": "Salary register uploaded"},
            {"key": "register.validated", "label": "Register validated"},
            {"key": "budget.uploaded", "label": "Budget uploaded"},
            {"key": "budget.approved", "label": "Budget approved"},
            {"key": "budget.deleted", "label": "Draft budget deleted"},
            {"key": "report.downloaded", "label": "Report downloaded"},
        ]
    })
