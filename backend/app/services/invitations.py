"""
Inviting people into an organization, and managing them once they are in.

The rules below are the whole point of this module. Each one exists because the
obvious implementation without it hands someone access to a month of salary
data they should not have — or locks an organization out of its own account.

**You cannot invite above yourself.** A manager cannot mint an owner. Otherwise
the role ladder is decorative: anyone who can invite can promote themselves by
inviting a second account.

**You cannot change your own role, and you cannot remove yourself.** Both
directions are wrong. Upwards is self-escalation; downwards is how an
organization ends up with nobody who can administer it.

**The last owner is protected.** An organization with no owner cannot add
entities, approve a budget, approve the JV mapping or sign off a period. It is
not recoverable from inside the product.

**A token is not an identity.** Acceptance requires the invited address. A link
that leaks — forwarded, left in a mailbox, pasted into a ticket — is worth
nothing to anyone who is not that person.

**A user belongs to exactly one organization.** The membership table says so,
and accepting an invitation while already a member of another organization is
refused rather than resolved. Silently moving someone would take their existing
employer's data out from under them.
"""
from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    DEFAULT_EXPIRY_DAYS,
    Entity,
    EntityAccess,
    ORG_ROLE_RANK,
    ORG_ROLES,
    OrgInvitation,
    OrgMembership,
    User,
)
from app.security import token_fingerprint


class InvitationError(Exception):
    """Something about this invitation cannot be done, and the message says why."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def normalise_email(value: str) -> str:
    return (value or "").strip().lower()


def new_token() -> str:
    """
    A token with enough entropy that guessing is not a strategy.

    32 bytes, URL-safe. The invitation is looked up by the hash of this, so the
    raw value exists only in the response to the person who created it and in
    whatever they send to the invitee.
    """
    return secrets.token_urlsafe(32)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    """
    A timestamp that can be compared.

    SQLite hands back naive datetimes even for a timezone-aware column, so a
    direct comparison against an aware ``now`` raises. Treat a naive value as
    UTC, which is what it was written as.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def is_expired(invitation: OrgInvitation, at: datetime | None = None) -> bool:
    expires = _aware(invitation.expires_at)
    return expires is not None and expires <= (at or _now())


def effective_state(invitation: OrgInvitation, at: datetime | None = None) -> str:
    """
    What this invitation is right now.

    Expiry is derived rather than stored: a row that went stale overnight should
    not depend on a sweeper having run to stop working.
    """
    if invitation.state == "pending" and is_expired(invitation, at):
        return "expired"
    return invitation.state


def can_grant_role(actor_role: str, target_role: str) -> bool:
    """Whether someone holding ``actor_role`` may grant ``target_role``."""
    actor = ORG_ROLE_RANK.get(actor_role)
    target = ORG_ROLE_RANK.get(target_role)
    if actor is None or target is None:
        return False
    # Ranks run widest-first, so a lower number is a wider role.
    return actor <= target


def owner_count(db: Session, org_id: uuid.UUID) -> int:
    return (
        db.query(OrgMembership)
        .filter(OrgMembership.org_id == org_id, OrgMembership.role == "owner")
        .count()
    )


def _check_role(role: str) -> str:
    if role not in ORG_ROLES:
        raise InvitationError(f"'{role}' is not a role. One of: {', '.join(ORG_ROLES)}")
    return role


def _check_entities(db: Session, org_id: uuid.UUID, entity_ids: list[str] | None) -> list[str]:
    """
    Validate that every named entity belongs to this organization.

    Refused rather than filtered: an invitation that silently dropped an entity
    would grant narrower access than the person issuing it believed they gave,
    and they would have no way to notice.
    """
    if not entity_ids:
        return []
    out: list[str] = []
    for raw in entity_ids:
        try:
            entity_uuid = uuid.UUID(str(raw))
        except (ValueError, AttributeError, TypeError):
            raise InvitationError(f"'{raw}' is not a valid entity id")
        entity = db.get(Entity, entity_uuid)
        if entity is None or entity.org_id != org_id:
            raise InvitationError("That entity does not belong to this organization", status=404)
        out.append(str(entity_uuid))
    return out


# ---------------------------------------------------------------------------
# Issuing
# ---------------------------------------------------------------------------
@dataclass
class IssuedInvitation:
    """An invitation, together with the one and only sight of its token."""

    invitation: OrgInvitation
    token: str


def create(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor: User,
    actor_role: str,
    email: str,
    role: str,
    entity_ids: list[str] | None = None,
    note: str | None = None,
    expiry_days: int = DEFAULT_EXPIRY_DAYS,
) -> IssuedInvitation:
    """Issue an invitation, replacing any pending one for the same address."""
    email = normalise_email(email)
    if not email or "@" not in email:
        raise InvitationError("A valid email address is required")
    _check_role(role)

    if not can_grant_role(actor_role, role):
        raise InvitationError(
            f"A {actor_role} cannot invite someone as {role}. You can only invite at "
            f"your own level or below.",
            status=403,
        )

    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user is not None:
        member = (
            db.query(OrgMembership)
            .filter(OrgMembership.user_id == existing_user.id)
            .first()
        )
        if member is not None:
            if member.org_id == org_id:
                raise InvitationError("That person is already a member of this organization", 409)
            raise InvitationError(
                "That email already belongs to another organization. A person can be a "
                "member of one organization at a time.",
                status=409,
            )

    scoped = _check_entities(db, org_id, entity_ids)

    # A second invitation to the same address supersedes the first rather than
    # sitting beside it, so two live tokens never exist for one seat.
    for prior in (
        db.query(OrgInvitation)
        .filter(
            OrgInvitation.org_id == org_id,
            OrgInvitation.email == email,
            OrgInvitation.state == "pending",
        )
        .all()
    ):
        prior.state = "revoked"
        prior.revoked_at = _now()
        prior.revoked_by_email = getattr(actor, "email", None)

    token = new_token()
    invitation = OrgInvitation(
        org_id=org_id,
        email=email,
        role=role,
        token_hash=token_fingerprint(token),
        entity_ids=scoped,
        state="pending",
        note=note,
        invited_by_user_id=getattr(actor, "id", None),
        invited_by_email=getattr(actor, "email", None),
        expires_at=_now() + timedelta(days=max(int(expiry_days), 1)),
    )
    db.add(invitation)
    db.flush()
    return IssuedInvitation(invitation=invitation, token=token)


def resend(
    db: Session, invitation: OrgInvitation, *, actor: User, expiry_days: int = DEFAULT_EXPIRY_DAYS
) -> IssuedInvitation:
    """
    Issue a fresh token for a pending invitation and restart its clock.

    A new token rather than the old one re-sent: the previous value may have
    gone somewhere it should not, and there is no way to know.
    """
    if effective_state(invitation) not in ("pending", "expired"):
        raise InvitationError(
            f"This invitation has already been {invitation.state} and cannot be resent", 409
        )
    token = new_token()
    invitation.token_hash = token_fingerprint(token)
    invitation.state = "pending"
    invitation.expires_at = _now() + timedelta(days=max(int(expiry_days), 1))
    invitation.invited_by_email = getattr(actor, "email", invitation.invited_by_email)
    return IssuedInvitation(invitation=invitation, token=token)


def revoke(db: Session, invitation: OrgInvitation, *, actor: User) -> OrgInvitation:
    if invitation.state == "accepted":
        raise InvitationError(
            "This invitation was already accepted. Remove the member instead.", 409
        )
    invitation.state = "revoked"
    invitation.revoked_at = _now()
    invitation.revoked_by_email = getattr(actor, "email", None)
    return invitation


# ---------------------------------------------------------------------------
# Accepting
# ---------------------------------------------------------------------------
def lookup(db: Session, token: str) -> OrgInvitation:
    """
    Find the invitation a token refers to, or say it is not usable.

    Every failure returns the same message. Distinguishing "no such token" from
    "expired" from "already used" would let someone with a list of guesses learn
    which ones were once real.
    """
    if not token:
        raise InvitationError("This invitation link is not valid", status=404)
    invitation = (
        db.query(OrgInvitation)
        .filter(OrgInvitation.token_hash == token_fingerprint(token))
        .first()
    )
    if invitation is None or effective_state(invitation) != "pending":
        raise InvitationError(
            "This invitation link is not valid, or has expired or already been used.",
            status=404,
        )
    return invitation


def accept(
    db: Session,
    invitation: OrgInvitation,
    user: User,
) -> OrgMembership:
    """
    Attach a user to the organization on the terms of the invitation.

    The user must already be the invited address. Checked here rather than only
    at the router, so no future caller can skip it.
    """
    if normalise_email(user.email) != normalise_email(invitation.email):
        raise InvitationError(
            "This invitation was sent to a different email address. Sign in as "
            f"{invitation.email} to accept it.",
            status=403,
        )
    if effective_state(invitation) != "pending":
        raise InvitationError(
            "This invitation link is not valid, or has expired or already been used.",
            status=404,
        )

    already = db.query(OrgMembership).filter(OrgMembership.user_id == user.id).first()
    if already is not None:
        if already.org_id == invitation.org_id:
            raise InvitationError("You are already a member of this organization", 409)
        raise InvitationError(
            "This account already belongs to another organization. A person can be a "
            "member of one organization at a time.",
            status=409,
        )

    membership = OrgMembership(
        org_id=invitation.org_id,
        user_id=user.id,
        role=invitation.role,
    )
    db.add(membership)
    db.flush()

    set_entity_access(db, org_id=invitation.org_id, user_id=user.id,
                      entity_ids=list(invitation.entity_ids or []))

    # Land them somewhere. Without a default the first header-less request has
    # no entity to act on, which reads to the new member as a broken account.
    scoped = list(invitation.entity_ids or [])
    if scoped:
        membership.default_entity_id = uuid.UUID(str(scoped[0]))
    else:
        first = (
            db.query(Entity)
            .filter(Entity.org_id == invitation.org_id, Entity.is_active.is_(True))
            .order_by(Entity.created_at)
            .first()
        )
        membership.default_entity_id = first.id if first else None

    invitation.state = "accepted"
    invitation.accepted_at = _now()
    invitation.accepted_by_user_id = user.id
    return membership


# ---------------------------------------------------------------------------
# Managing members already in
# ---------------------------------------------------------------------------
def set_entity_access(
    db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, entity_ids: list[str] | None
) -> list[str]:
    """
    Replace a member's entity scoping.

    An empty list means the whole organization — the same convention
    ``EntityAccess`` already uses, where no rows means no restriction.
    """
    scoped = _check_entities(db, org_id, entity_ids)
    db.query(EntityAccess).filter(
        EntityAccess.org_id == org_id, EntityAccess.user_id == user_id
    ).delete(synchronize_session=False)
    for entity_id in scoped:
        db.add(
            EntityAccess(org_id=org_id, user_id=user_id, entity_id=uuid.UUID(entity_id))
        )
    return scoped


def change_role(
    db: Session,
    *,
    membership: OrgMembership,
    actor: User,
    actor_role: str,
    role: str,
) -> OrgMembership:
    _check_role(role)

    if membership.user_id == actor.id:
        raise InvitationError(
            "You cannot change your own role. Ask another owner to do it.", status=403
        )
    if not can_grant_role(actor_role, role):
        raise InvitationError(
            f"A {actor_role} cannot grant the {role} role.", status=403
        )
    if not can_grant_role(actor_role, membership.role):
        raise InvitationError(
            f"A {actor_role} cannot change the role of a {membership.role}.", status=403
        )
    if (
        membership.role == "owner"
        and role != "owner"
        and owner_count(db, membership.org_id) <= 1
    ):
        raise InvitationError(
            "This is the only owner. Promote someone else to owner first — an "
            "organization with no owner cannot be administered.",
            status=409,
        )

    membership.role = role
    return membership


def remove_member(
    db: Session, *, membership: OrgMembership, actor: User, actor_role: str
) -> None:
    if membership.user_id == actor.id:
        raise InvitationError(
            "You cannot remove yourself. Ask another owner to do it.", status=403
        )
    if not can_grant_role(actor_role, membership.role):
        raise InvitationError(
            f"A {actor_role} cannot remove a {membership.role}.", status=403
        )
    if membership.role == "owner" and owner_count(db, membership.org_id) <= 1:
        raise InvitationError(
            "This is the only owner. Promote someone else to owner first.", status=409
        )

    db.query(EntityAccess).filter(
        EntityAccess.org_id == membership.org_id,
        EntityAccess.user_id == membership.user_id,
    ).delete(synchronize_session=False)
    db.delete(membership)


def entity_access_for(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> list[str]:
    rows = (
        db.query(EntityAccess)
        .filter(EntityAccess.org_id == org_id, EntityAccess.user_id == user_id)
        .all()
    )
    return [str(r.entity_id) for r in rows]
