"""
Organization / entity provisioning and access resolution.

Access rules, in one place so they cannot drift between routers:

* a user reaches data only through an ``OrgMembership``;
* within their org, a user reaches every entity **unless** ``EntityAccess`` rows
  exist for them, in which case those rows are the whitelist;
* the role on the membership decides what they may *do* with an entity.
"""
from __future__ import annotations

import re
import uuid

from sqlalchemy.orm import Session

from app.models import Entity, EntityAccess, OrgMembership, Organization, User
from app.models.org import ORG_ROLE_RANK

# Actions gated by role. Anything not listed is readable by every member.
WRITE_ROLES = ("owner", "manager", "analyst")
ADMIN_ROLES = ("owner", "manager")


def slugify_code(name: str, fallback: str = "ENTITY") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", (name or "").upper())[:12]
    return cleaned or fallback


def unique_entity_code(db: Session, org_id: uuid.UUID, name: str) -> str:
    """Derive an entity code that does not collide inside the organization."""
    base = slugify_code(name)
    taken = {
        code
        for (code,) in db.query(Entity.code).filter(Entity.org_id == org_id).all()
    }
    if base not in taken:
        return base
    for suffix in range(2, 100):
        candidate = f"{base[:10]}{suffix}"
        if candidate not in taken:
            return candidate
    return f"{base[:6]}{uuid.uuid4().hex[:6].upper()}"


def provision_org_for_user(
    db: Session,
    user: User,
    org_name: str | None = None,
    org_type: str = "enterprise",
    entity_name: str | None = None,
) -> tuple[Organization, Entity]:
    """
    Create an organization, its first entity, and an owner seat for ``user``.

    Called when a new user signs up, and by the migration for users who predate
    entities. Commits nothing — the caller owns the transaction.
    """
    display = (org_name or user.company_name or (user.email or "").split("@")[0] or "My organization").strip()
    org = Organization(name=display, org_type=org_type)
    db.add(org)
    db.flush()

    first_entity_name = (entity_name or display).strip()
    entity = Entity(
        org_id=org.id,
        name=first_entity_name,
        legal_name=first_entity_name,
        code=unique_entity_code(db, org.id, first_entity_name),
        is_active=True,
    )
    db.add(entity)
    db.add(OrgMembership(org_id=org.id, user_id=user.id, role="owner"))
    db.flush()
    return org, entity


def get_membership(db: Session, user: User) -> OrgMembership | None:
    return db.query(OrgMembership).filter(OrgMembership.user_id == user.id).first()


def accessible_entities(db: Session, user: User) -> list[Entity]:
    """Every entity the user may open, newest-membership org first."""
    membership = get_membership(db, user)
    if membership is None:
        return []

    query = db.query(Entity).filter(
        Entity.org_id == membership.org_id,
        Entity.is_active.is_(True),
    )

    restricted = {
        row.entity_id
        for row in db.query(EntityAccess).filter(
            EntityAccess.user_id == user.id,
            EntityAccess.org_id == membership.org_id,
        )
    }
    if restricted:
        query = query.filter(Entity.id.in_(restricted))

    return query.order_by(Entity.name).all()


def can_access_entity(db: Session, user: User, entity: Entity) -> bool:
    membership = get_membership(db, user)
    if membership is None or membership.org_id != entity.org_id:
        return False
    restricted = (
        db.query(EntityAccess)
        .filter(EntityAccess.user_id == user.id, EntityAccess.org_id == membership.org_id)
        .count()
    )
    if not restricted:
        return True
    return (
        db.query(EntityAccess)
        .filter(EntityAccess.user_id == user.id, EntityAccess.entity_id == entity.id)
        .count()
        > 0
    )


def role_at_least(db: Session, user: User, minimum: str) -> bool:
    membership = get_membership(db, user)
    if membership is None:
        return False
    have = ORG_ROLE_RANK.get(membership.role, len(ORG_ROLE_RANK))
    want = ORG_ROLE_RANK.get(minimum, 0)
    return have <= want
