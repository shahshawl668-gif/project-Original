"""Tenant-level validation rule suppression (UI-configurable)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.envelope import ok
from app.models import TenantRulePreference, User
from app.schemas.rule_preferences import TenantRulePreferenceOut, TenantRulePreferenceUpsert

router = APIRouter(prefix="/rule-preferences", tags=["rule-preferences"])


@router.get("")
def list_preferences(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(TenantRulePreference)
        .filter(TenantRulePreference.user_id == user.id)
        .order_by(TenantRulePreference.rule_id)
        .all()
    )
    data = [
        TenantRulePreferenceOut(rule_id=r.rule_id, suppressed=r.suppressed).model_dump()
        for r in rows
    ]
    return ok(data)


@router.put("")
def upsert_preference(
    body: TenantRulePreferenceUpsert,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rid = body.rule_id.strip()
    existing = (
        db.query(TenantRulePreference)
        .filter(TenantRulePreference.user_id == user.id, TenantRulePreference.rule_id == rid)
        .first()
    )
    if existing:
        existing.suppressed = body.suppressed
        db.add(existing)
    else:
        db.add(
            TenantRulePreference(
                user_id=user.id,
                rule_id=rid,
                suppressed=body.suppressed,
            )
        )
    db.commit()
    return ok({"rule_id": rid, "suppressed": body.suppressed})


@router.delete("/{rule_id}")
def delete_preference(
    rule_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(TenantRulePreference).filter(
        TenantRulePreference.user_id == user.id,
        TenantRulePreference.rule_id == rule_id,
    )
    if q.delete() == 0:
        raise HTTPException(status_code=404, detail="Preference not found")
    db.commit()
    return ok({"deleted": rule_id})
