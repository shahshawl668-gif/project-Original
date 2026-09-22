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
    # Flush before reading entity.id: the primary key comes from a Python-side
    # default applied at INSERT, so it is still None on the pending object.
    db.flush()

    db.add(
        OrgMembership(
            org_id=org.id,
            user_id=user.id,
            role="owner",
            default_entity_id=entity.id,
        )
    )
    db.flush()
    return org, entity


def get_membership(db: Session, user: User) -> OrgMembership | None:
    return db.query(OrgMembership).filter(OrgMembership.user_id == user.id).first()


def accessible_entities(db: Session, user: User) -> list[Entity]:
    """
    Every entity the user may open, newest-membership org first.

    A live support grant adds that organization's entities to the list, so the
    switcher can reach them — but they are appended after the user's own, and
    carry no role, so nothing about them becomes writable.
    """
    from app.services import support_access

    supported = support_access.granted_org_ids(db, user)
    membership = get_membership(db, user)
    if membership is None:
        if not supported:
            return []
        return (
            db.query(Entity)
            .filter(Entity.org_id.in_(supported), Entity.is_active.is_(True))
            .order_by(Entity.name)
            .all()
        )

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

    own = query.order_by(Entity.name).all()
    if not supported:
        return own
    granted = (
        db.query(Entity)
        .filter(Entity.org_id.in_(supported), Entity.is_active.is_(True))
        .order_by(Entity.name)
        .all()
    )
    return own + [e for e in granted if e.org_id != membership.org_id]


def default_entity(db: Session, user: User) -> Entity | None:
    """
    The entity a request targets when it names none.

    Deliberately the *oldest* accessible entity — the one provisioned at signup
    — rather than the first by name. Ordering this by name would mean adding a
    client called "Alpha" silently redirects every header-less request away
    from the entity that had been receiving them.
    """
    entities = accessible_entities(db, user)
    if not entities:
        return None

    membership = get_membership(db, user)
    if membership is not None and membership.default_entity_id is not None:
        chosen = next((e for e in entities if e.id == membership.default_entity_id), None)
        if chosen is not None:
            return chosen

    # No stored default (or it points somewhere they can no longer reach):
    # fall back to the oldest entity and remember it, so the answer is stable
    # from here on.
    fallback = min(entities, key=lambda e: (e.created_at is None, e.created_at, str(e.id)))
    if membership is not None:
        membership.default_entity_id = fallback.id
        db.add(membership)
        db.flush()
    return fallback


def set_default_entity(db: Session, user: User, entity: Entity) -> None:
    """Remember the member's entity choice for requests that send no header."""
    membership = get_membership(db, user)
    if membership is None or membership.org_id != entity.org_id:
        return
    membership.default_entity_id = entity.id
    db.add(membership)


def support_grant_for(db: Session, user: User, entity: Entity):
    """
    A live break-glass grant letting this user read this entity, or ``None``.

    Kept separate from membership rather than folded into it: a support session
    is not a seat in the organization, and every caller that asks "what may this
    person do" must be able to tell the two apart. Roles come from membership
    only, so a support user has no role and therefore no write access anywhere.
    """
    from app.services import support_access

    return support_access.active_grant(db, user, entity.org_id)


def can_access_entity(db: Session, user: User, entity: Entity) -> bool:
    membership = get_membership(db, user)
    if membership is None or membership.org_id != entity.org_id:
        # Not a member. The only other way in is a live support grant, which is
        # time-boxed, reasoned, read-only and written to this organization's own
        # audit trail when it was opened.
        return support_grant_for(db, user, entity) is not None
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
    """
    Whether the user holds at least this role in their own organization.

    Reads membership only, never a support grant — which is what makes a
    support session read-only without a single explicit check: every mutating
    endpoint in the product is gated on this, and a support user has no seat.
    """
    membership = get_membership(db, user)
    if membership is None:
        return False
    have = ORG_ROLE_RANK.get(membership.role, len(ORG_ROLE_RANK))
    want = ORG_ROLE_RANK.get(minimum, 0)
    return have <= want
