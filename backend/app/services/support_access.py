"""
Opening, using and closing a break-glass support session.

The rules here are what make this safe to have at all. Each one is the
difference between a documented support mechanism and a back door.

**A grant is never implicit.** Nothing widens access as a side effect. A
platform administrator with no grant reads no client data, exactly as before.

**A grant is never silent.** Opening one writes to the *client's* audit trail,
not to a separate staff log they cannot see. So does ending it, and so does the
client revoking it.

**A grant cannot outlive its box.** Expiry is derived from a stored timestamp
rather than swept, so a lapsed session stops working the moment it lapses,
whether or not anything ran.

**A grant never carries write access, and never unmasks.** Both are recorded on
the grant rather than decided at read time, so what a past session could see
stays true even if the product later gains a wider mode.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    DEFAULT_MINUTES,
    MAX_MINUTES,
    SUPPORT_POLICIES,
    Organization,
    SupportAccessGrant,
    User,
)

# A reason short enough to be meaningless is not a reason.
MIN_REASON = 12


class SupportAccessError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    """
    A timestamp that can be compared.

    SQLite returns naive datetimes even for a timezone-aware column, so a direct
    comparison against an aware ``now`` raises. A naive value is treated as UTC,
    which is what it was written as.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def is_expired(grant: SupportAccessGrant, at: datetime | None = None) -> bool:
    expires = _aware(grant.expires_at)
    return expires is not None and expires <= (at or _now())


def effective_state(grant: SupportAccessGrant, at: datetime | None = None) -> str:
    """What this grant is right now. Expiry is derived, never swept."""
    if grant.state in ("active", "pending") and is_expired(grant, at):
        return "expired"
    return grant.state


def policy_for(db: Session, org_id: uuid.UUID) -> str:
    org = db.get(Organization, org_id)
    return getattr(org, "support_access_policy", "break_glass") or "break_glass"


def set_policy(db: Session, org: Organization, policy: str) -> Organization:
    if policy not in SUPPORT_POLICIES:
        raise SupportAccessError(
            f"'{policy}' is not a support policy. One of: {', '.join(SUPPORT_POLICIES)}"
        )
    org.support_access_policy = policy
    if policy == "disabled":
        # Switching support off closes anything already open. A policy that only
        # applied to future sessions would not be the switch it appears to be.
        for grant in active_grants_for_org(db, org.id):
            end(db, grant, actor_email=None, reason="support access disabled for this organization")
    return org


# ---------------------------------------------------------------------------
# Opening
# ---------------------------------------------------------------------------
def open_grant(
    db: Session,
    *,
    org_id: uuid.UUID,
    admin: User,
    reason: str,
    minutes: int = DEFAULT_MINUTES,
) -> SupportAccessGrant:
    """
    Open a session, or request one where the client requires approval.

    Returns a grant that is ``active`` under a break-glass policy and
    ``pending`` under approval. Never returns something usable under a
    ``disabled`` policy — it raises instead.
    """
    org = db.get(Organization, org_id)
    if org is None:
        raise SupportAccessError("Organization not found", status=404)

    reason = (reason or "").strip()
    if len(reason) < MIN_REASON:
        raise SupportAccessError(
            f"A reason of at least {MIN_REASON} characters is required. It is written to "
            "the client's own audit trail, so it should say what you are investigating."
        )

    minutes = int(minutes or DEFAULT_MINUTES)
    if minutes < 1 or minutes > MAX_MINUTES:
        raise SupportAccessError(
            f"Duration must be between 1 and {MAX_MINUTES} minutes."
        )

    policy = policy_for(db, org_id)
    if policy == "disabled":
        raise SupportAccessError(
            "This organization has turned support access off. An owner there must "
            "re-enable it before anyone can open a session.",
            status=403,
        )

    existing = active_grant(db, admin, org_id)
    if existing is not None:
        raise SupportAccessError(
            "You already have an open session on this organization.", status=409
        )

    grant = SupportAccessGrant(
        org_id=org_id,
        admin_user_id=admin.id,
        admin_email=admin.email,
        reason=reason,
        state="active" if policy == "break_glass" else "pending",
        policy_at_grant=policy,
        read_only=True,
        identity_masked=True,
        expires_at=_now() + timedelta(minutes=minutes),
    )
    db.add(grant)
    db.flush()
    return grant


def approve(db: Session, grant: SupportAccessGrant, *, approver: User) -> SupportAccessGrant:
    if effective_state(grant) != "pending":
        raise SupportAccessError(
            "This request is no longer pending — it may have expired or been withdrawn.",
            status=409,
        )
    grant.state = "active"
    grant.approved_by_email = approver.email
    grant.approved_at = _now()
    return grant


def end(
    db: Session,
    grant: SupportAccessGrant,
    *,
    actor_email: str | None,
    reason: str,
    revoked: bool = False,
) -> SupportAccessGrant:
    """Close a session. Ending and revoking are different facts, recorded as such."""
    if grant.state in ("ended", "revoked"):
        return grant
    grant.state = "revoked" if revoked else "ended"
    grant.ended_at = _now()
    grant.ended_by_email = actor_email
    grant.ended_reason = reason[:255] if reason else None
    return grant


# ---------------------------------------------------------------------------
# Using
# ---------------------------------------------------------------------------
def active_grant(
    db: Session, user: User, org_id: uuid.UUID
) -> SupportAccessGrant | None:
    """
    This user's live grant on this organization, or ``None``.

    The platform-role check lives here rather than only at the router: a grant
    held by someone who is no longer platform staff must stop working the moment
    their role changes, without anyone having to revoke it.
    """
    if getattr(user, "role", None) != "admin":
        return None
    grant = (
        db.query(SupportAccessGrant)
        .filter(
            SupportAccessGrant.admin_user_id == user.id,
            SupportAccessGrant.org_id == org_id,
            SupportAccessGrant.state == "active",
        )
        .order_by(SupportAccessGrant.requested_at.desc())
        .first()
    )
    if grant is None or is_expired(grant):
        return None
    return grant


def active_grants_for_org(db: Session, org_id: uuid.UUID) -> list[SupportAccessGrant]:
    return [
        g
        for g in db.query(SupportAccessGrant)
        .filter(
            SupportAccessGrant.org_id == org_id,
            SupportAccessGrant.state.in_(("active", "pending")),
        )
        .all()
        if not is_expired(g)
    ]


def granted_org_ids(db: Session, user: User) -> list[uuid.UUID]:
    """Every organization this user currently holds a live grant on."""
    if getattr(user, "role", None) != "admin":
        return []
    rows = (
        db.query(SupportAccessGrant)
        .filter(
            SupportAccessGrant.admin_user_id == user.id,
            SupportAccessGrant.state == "active",
        )
        .all()
    )
    return [g.org_id for g in rows if not is_expired(g)]


def note_use(db: Session, grant: SupportAccessGrant) -> None:
    """
    Record that the session was actually used.

    A session opened and never used is a different fact from one that read the
    whole book, and the client is entitled to tell them apart.
    """
    grant.use_count = (grant.use_count or 0) + 1
    grant.last_used_at = _now()


def describe(grant: SupportAccessGrant) -> dict:
    return {
        "id": str(grant.id),
        "org_id": str(grant.org_id),
        "admin_email": grant.admin_email,
        "reason": grant.reason,
        "state": effective_state(grant),
        "policy_at_grant": grant.policy_at_grant,
        "read_only": grant.read_only,
        "identity_masked": grant.identity_masked,
        "requested_at": grant.requested_at.isoformat() if grant.requested_at else None,
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        "approved_by": grant.approved_by_email,
        "approved_at": grant.approved_at.isoformat() if grant.approved_at else None,
        "ended_at": grant.ended_at.isoformat() if grant.ended_at else None,
        "ended_by": grant.ended_by_email,
        "ended_reason": grant.ended_reason,
        "last_used_at": grant.last_used_at.isoformat() if grant.last_used_at else None,
        "use_count": grant.use_count or 0,
    }
