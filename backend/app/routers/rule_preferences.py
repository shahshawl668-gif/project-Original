"""Tenant-level validation rule suppression (UI-configurable)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database

from app.database import get_db
from app.deps import get_current_user
from app.envelope import ok
from app.models import TenantRulePreference, User
from app.schemas.rule_preferences import TenantRulePreferenceOut, TenantRulePreferenceUpsert

router = APIRouter(prefix="/rule-preferences", tags=["rule-preferences"])


@router.get("")
def list_preferences(db: Database = Depends(get_db), user: User = Depends(get_current_user)):
    rows = TenantRulePreference.find_many(db, {"user_id": user.id}, sort=[("rule_id", 1)])
    data = [
        TenantRulePreferenceOut(rule_id=r.rule_id, suppressed=r.suppressed).model_dump()
        for r in rows
    ]
    return ok(data)


@router.put("")
def upsert_preference(
    body: TenantRulePreferenceUpsert,
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rid = body.rule_id.strip()
    existing = TenantRulePreference.find_one(db, {"user_id": user.id, "rule_id": rid})
    if existing:
        existing.suppressed = body.suppressed
        existing.save(db)
    else:
        TenantRulePreference(
            user_id=user.id,
            rule_id=rid,
            suppressed=body.suppressed,
        ).insert(db)
    return ok({"rule_id": rid, "suppressed": body.suppressed})


@router.delete("/{rule_id}")
def delete_preference(
    rule_id: str,
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if TenantRulePreference.delete_many(db, {"user_id": user.id, "rule_id": rule_id}) == 0:
        raise HTTPException(status_code=404, detail="Preference not found")
    return ok({"deleted": rule_id})
