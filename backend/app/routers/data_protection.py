"""
Data protection: the company's retention period, and erasing one person's data.

Every change here is an owner's decision and goes into the company's audit
trail. Reading the policy is open to every member: people working with the
data should know how long it is kept.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, require_entity_admin
from app.envelope import ok
from app.models import Entity, ErasureRequest, User
from app.services import data_protection as dp
from app.services import tenancy

router = APIRouter()


class RetentionUpdate(BaseModel):
    payroll_months: int | None = Field(None, description="Months of payroll periods kept; null keeps everything")
    reason: str = Field(..., min_length=5, max_length=1000)


class ErasureCreate(BaseModel):
    employee_id: str = Field(..., min_length=1, max_length=64)
    confirm_employee_id: str = Field(..., min_length=1, max_length=64)
    reason: str = Field(..., min_length=5, max_length=1000)


def _owner(db: Session, user: User, entity: Entity) -> None:
    if not tenancy.role_at_least(db, user, "owner", entity):
        raise HTTPException(status_code=403, detail="Only an owner can change retention or erase data")


@router.get("/retention")
def get_retention(entity: Entity = Depends(get_current_entity), db: Session = Depends(get_db)):
    return ok(dp.describe_policy(db, entity.id))


@router.get("/retention/preview")
def preview_retention(
    months: int = Query(..., ge=dp.MIN_MONTHS, le=dp.MAX_MONTHS),
    entity: Entity = Depends(get_current_entity),
    user: User = Depends(require_entity_admin),
    db: Session = Depends(get_db),
):
    """What a retention period of ``months`` would remove today. Nothing is written."""
    return ok(dp.retention_plan(db, entity.id, months))


@router.put("/retention")
def set_retention(
    body: RetentionUpdate,
    entity: Entity = Depends(get_current_entity),
    user: User = Depends(require_entity_admin),
    db: Session = Depends(get_db),
):
    _owner(db, user, entity)
    try:
        dp.set_policy(db, entity, user, body.payroll_months, body.reason.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return ok(dp.describe_policy(db, entity.id))


@router.post("/retention/apply")
def apply_retention(
    entity: Entity = Depends(get_current_entity),
    user: User = Depends(require_entity_admin),
    db: Session = Depends(get_db),
):
    """Apply the period now rather than on the worker's next daily pass."""
    _owner(db, user, entity)
    policy = dp.policy_for(db, entity.id)
    if policy is None or not policy.payroll_months:
        raise HTTPException(status_code=409, detail="No retention period is set, so there is nothing to apply")
    counts = dp.apply_retention(db, entity, policy, user)
    return ok({"counts": counts, "policy": dp.describe_policy(db, entity.id)})


@router.get("/erasures")
def list_erasures(
    entity: Entity = Depends(get_current_entity),
    user: User = Depends(require_entity_admin),
    db: Session = Depends(get_db),
):
    rows = (db.query(ErasureRequest).filter(ErasureRequest.entity_id == entity.id)
            .order_by(ErasureRequest.completed_at.desc()).limit(200).all())
    return ok([dp.describe_request(r) for r in rows])


@router.get("/erasures/preview")
def preview_erasure(
    employee_id: str = Query(..., min_length=1, max_length=64),
    entity: Entity = Depends(get_current_entity),
    user: User = Depends(require_entity_admin),
    db: Session = Depends(get_db),
):
    _owner(db, user, entity)
    return ok(dp.erasure_plan(db, entity.id, employee_id))


@router.post("/erasures", status_code=201)
def create_erasure(
    body: ErasureCreate,
    entity: Entity = Depends(get_current_entity),
    user: User = Depends(require_entity_admin),
    db: Session = Depends(get_db),
):
    _owner(db, user, entity)
    if body.employee_id.strip() != body.confirm_employee_id.strip():
        raise HTTPException(status_code=400, detail="The confirmation does not match the employee ID")
    try:
        request = dp.erase_employee(db, entity, user, body.employee_id, body.reason.strip())
    except dp.ErasureRefused as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ok(dp.describe_request(request))
