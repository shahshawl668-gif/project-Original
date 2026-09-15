"""
Organization and entity management.

``GET /api/org/context`` is the endpoint the frontend calls on boot: it returns
the organization, the caller's role, and the entities they may open, so the
entity switcher can render without a second round trip.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_org_admin
from app.envelope import ok
from app.models import Entity, OrgMembership, Organization, User
from app.schemas.org import (
    ContextOut,
    EntityCreate,
    EntityOut,
    EntityUpdate,
    MembershipOut,
    OrganizationOut,
    OrganizationUpdate,
)
from app.services import tenancy

router = APIRouter()


@router.get("/context")
def get_context(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    membership = tenancy.get_membership(db, user)
    org = db.get(Organization, membership.org_id) if membership else None
    entities = tenancy.accessible_entities(db, user)
    payload = ContextOut(
        organization=OrganizationOut.model_validate(org) if org else None,
        role=membership.role if membership else None,
        active_entity=EntityOut.model_validate(entity),
        entities=[EntityOut.model_validate(e) for e in entities],
    )
    return ok(payload.model_dump(mode="json"))


@router.get("/entities")
def list_entities(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    entities = tenancy.accessible_entities(db, user)
    return ok([EntityOut.model_validate(e).model_dump(mode="json") for e in entities])


@router.post("/entities")
def create_entity(
    body: EntityCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    membership = tenancy.get_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=400, detail="No organization for this user")

    code = (body.code or "").strip().upper() or tenancy.unique_entity_code(db, membership.org_id, body.name)
    clash = (
        db.query(Entity)
        .filter(Entity.org_id == membership.org_id, Entity.code == code)
        .first()
    )
    if clash:
        raise HTTPException(status_code=400, detail=f"Entity code '{code}' already in use")

    entity = Entity(
        org_id=membership.org_id,
        code=code,
        **body.model_dump(exclude={"code"}),
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return ok(EntityOut.model_validate(entity).model_dump(mode="json"))


@router.patch("/entities/{entity_id}")
def update_entity(
    entity_id: uuid.UUID,
    body: EntityUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    entity = db.get(Entity, entity_id)
    if entity is None or not tenancy.can_access_entity(db, user, entity):
        raise HTTPException(status_code=404, detail="Entity not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(entity, field, value)
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return ok(EntityOut.model_validate(entity).model_dump(mode="json"))


@router.get("/members")
def list_members(db: Session = Depends(get_db), user: User = Depends(require_org_admin)):
    membership = tenancy.get_membership(db, user)
    if membership is None:
        return ok([])
    rows = (
        db.query(OrgMembership, User)
        .join(User, User.id == OrgMembership.user_id)
        .filter(OrgMembership.org_id == membership.org_id)
        .all()
    )
    out = []
    for m, u in rows:
        item = MembershipOut.model_validate(m)
        item.email = u.email
        out.append(item.model_dump(mode="json"))
    return ok(out)


@router.patch("")
def update_org(
    body: OrganizationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    membership = tenancy.get_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=400, detail="No organization for this user")
    org = db.get(Organization, membership.org_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(org, field, value)
    db.add(org)
    db.commit()
    db.refresh(org)
    return ok(OrganizationOut.model_validate(org).model_dump(mode="json"))
