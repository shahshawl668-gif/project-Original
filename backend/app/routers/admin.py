"""Admin-only tenant user management."""

from __future__ import annotations

import uuid
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import SYSTEM_USER_EMAIL, require_admin
from app.envelope import ok
from app.models import (
    DEFAULT_MINUTES,
    MAX_MINUTES,
    OrgMembership,
    Entity,
    Organization,
    PlatformInvitation,
    SecurityEvent,
    SupportAccessGrant,
    User,
)
from app.schemas.auth import AdminRoleUpdate, UserOut
from app.security import token_fingerprint
from app.services import audit, auth_security, invitations, support_access, tenancy

router = APIRouter(prefix="/admin", tags=["admin"])


class StaffInviteRequest(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(admin|support)$")


class StaffRoleUpdate(BaseModel):
    role: str = Field(pattern="^(admin|support|none)$")


@router.get("/staff")
def list_staff(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if admin.platform_role != "owner":
        raise HTTPException(status_code=403, detail="Platform owner required")
    rows = db.query(User).filter(User.platform_role.is_not(None)).order_by(User.email).all()
    return ok([{"id": str(u.id), "email": u.email, "role": u.platform_role} for u in rows])


@router.patch("/staff/{user_id}/role")
def update_staff_role(user_id: uuid.UUID, body: StaffRoleUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if admin.platform_role != "owner":
        raise HTTPException(status_code=403, detail="Platform owner required")
    target = db.get(User, user_id)
    if not target or target.platform_role not in {"admin", "support"}:
        raise HTTPException(status_code=404, detail="Staff account not found")
    target.platform_role = None if body.role == "none" else body.role
    db.commit()
    return ok({"id": str(target.id), "email": target.email, "role": target.platform_role})


@router.post("/staff/invitations", status_code=201)
def invite_platform_staff(body: StaffInviteRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if admin.platform_role != "owner":
        raise HTTPException(status_code=403, detail="Platform owner required")
    email = str(body.email).lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="This email already has an account")
    db.query(PlatformInvitation).filter(PlatformInvitation.email == email, PlatformInvitation.used_at.is_(None)).update({"used_at": datetime.now(UTC)})
    token = secrets.token_urlsafe(32)
    invite = PlatformInvitation(email=email, role=body.role, token_hash=token_fingerprint(token),
                                invited_by_user_id=admin.id, expires_at=datetime.now(UTC) + timedelta(days=7))
    db.add(invite)
    db.commit()
    return ok({"email": email, "role": body.role, "invitation_path": f"/platform/join?token={token}"})


class WorkspaceProvision(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    owner_email: EmailStr
    org_type: str = Field(default="enterprise", pattern="^(enterprise|practice)$")
    products: list[str] = Field(default_factory=lambda: ["payroll-validation"])


@router.get("/organizations")
def list_organizations(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if admin.platform_role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Platform administrator required")
    rows = db.query(Organization).order_by(Organization.created_at.desc()).limit(200).all()
    return ok([{"id": str(o.id), "name": o.name, "slug": o.slug, "cell": o.deployment_cell,
                "products": o.enabled_products, "login_path": f"/w/{o.slug}/login"} for o in rows])


@router.post("/organizations", status_code=201)
def provision_organization(body: WorkspaceProvision, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if admin.platform_role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Platform administrator required")
    if not body.products or any(p not in {"payroll-validation"} for p in body.products):
        raise HTTPException(status_code=400, detail="Unknown product")
    org = Organization(name=body.name.strip(), slug=tenancy.unique_org_slug(db, body.name),
                       org_type=body.org_type, enabled_products=list(set(body.products)))
    db.add(org)
    db.flush()
    entity = Entity(org_id=org.id, name=org.name, legal_name=org.name,
                    code=tenancy.unique_entity_code(db, org.id, org.name), is_active=True)
    db.add(entity)
    try:
        issued = invitations.create(db, org_id=org.id, actor=admin, actor_role="owner",
                                    email=str(body.owner_email), role="owner")
    except invitations.InvitationError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    audit.record(db, entity_id=None, org_id=org.id, user=admin, action="platform.org.provision",
                 object_type="organization", summary=f"Provisioned {org.name} and invited its owner")
    db.commit()
    return ok({"id": str(org.id), "name": org.name, "slug": org.slug, "cell": org.deployment_cell,
               "products": org.enabled_products, "login_path": f"/w/{org.slug}/login",
               "invitation_path": f"/invite?token={issued.token}"})


def _admin_count(db: Session) -> int:
    return (
        db.query(User)
        .filter(User.role == "admin", User.email != SYSTEM_USER_EMAIL)
        .count()
    )


def _visible_org_ids(db: Session, admin: User) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """
    The organizations this platform administrator may see accounts in.

    Their own, plus any they currently hold a support grant on — and nothing
    else. Being platform staff is not by itself a reason to read a client's
    people, which is the whole premise of break-glass: if a standing platform
    role could enumerate every client's staff list, the grant would be
    decoration.

    Returns the two sets separately because they are not the same fact. Reading
    your own organization is routine; reading a client's under a grant is an
    event their audit trail is entitled to.
    """
    membership = tenancy.get_membership(db, admin)
    own = [membership.org_id] if membership is not None else []
    granted = [
        org_id for org_id in support_access.granted_org_ids(db, admin) if org_id not in own
    ]
    return own, granted


def _users_in(db: Session, org_ids: list[uuid.UUID]) -> list[User]:
    if not org_ids:
        return []
    return (
        db.query(User)
        .join(OrgMembership, OrgMembership.user_id == User.id)
        .filter(OrgMembership.org_id.in_(org_ids), User.email != SYSTEM_USER_EMAIL)
        .order_by(User.created_at.asc())
        .all()
    )


@router.get("/users")
def list_tenant_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    own, granted = _visible_org_ids(db, admin)
    rows = _users_in(db, own + granted)

    for org_id in granted:
        # The client sees who looked at their people, and when. A read is the
        # whole point of a support session, so it is the thing worth recording.
        audit.record(
            db,
            entity_id=None,
            org_id=org_id,
            user=admin,
            action="support.read",
            object_type="org_members",
            summary=f"{admin.email} listed this organization's accounts under support access",
        )
    if granted:
        db.commit()

    seen: set[uuid.UUID] = set()
    unique: list[User] = []
    for row in rows:
        if row.id not in seen:
            seen.add(row.id)
            unique.append(row)
    return ok([UserOut.model_validate(u).model_dump() for u in unique])


@router.patch("/users/{target_id}/role")
def patch_user_role(
    target_id: uuid.UUID,
    body: AdminRoleUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if target_id == admin.id and body.role == "user" and _admin_count(db) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot demote yourself while you are the only admin.",
        )

    tgt = db.get(User, target_id)
    if not tgt:
        raise HTTPException(status_code=404, detail="User not found")
    if tgt.email == SYSTEM_USER_EMAIL or tgt.role == "system":
        raise HTTPException(status_code=400, detail="Cannot change system account role")

    # A user you are not entitled to see is a user you cannot promote. Same 404
    # as a missing one: which organizations exist is not something this endpoint
    # should confirm. Note that a support grant is read-only, so holding one
    # does not put a client's accounts in reach here — only your own do.
    own, _granted = _visible_org_ids(db, admin)
    if tgt.id != admin.id and tgt.id not in {u.id for u in _users_in(db, own)}:
        raise HTTPException(status_code=404, detail="User not found")

    if body.role == "user" and tgt.role == "admin" and _admin_count(db) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Cannot demote the last admin. Promote another user first.",
        )

    tgt.role = body.role
    db.add(tgt)
    db.commit()
    db.refresh(tgt)
    return ok(UserOut.model_validate(tgt).model_dump())


# ---------------------------------------------------------------------------
# Break-glass support access
# ---------------------------------------------------------------------------
class SupportOpenRequest(BaseModel):
    """Opening a session on a client's data. The reason is not optional."""

    org_id: uuid.UUID
    reason: str = Field(min_length=12, max_length=2000)
    minutes: int = Field(default=DEFAULT_MINUTES, ge=1, le=MAX_MINUTES)


class SupportEndRequest(BaseModel):
    reason: str = Field(default="finished", max_length=255)


def _support_error(exc: support_access.SupportAccessError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/support/organizations")
def support_organizations(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    The organizations support could open a session on, and on what terms.

    Names and policies only — never their data. Reaching data needs a grant.
    """
    rows = db.query(Organization).order_by(Organization.name).all()
    return ok([
        {
            "id": str(org.id),
            "name": org.name,
            "org_type": org.org_type,
            "support_access_policy": getattr(org, "support_access_policy", "break_glass"),
        }
        for org in rows
    ])


@router.get("/support/grants")
def list_support_grants(
    admin: User = Depends(require_admin),
    mine: bool = True,
    db: Session = Depends(get_db),
):
    query = db.query(SupportAccessGrant)
    if mine:
        query = query.filter(SupportAccessGrant.admin_user_id == admin.id)
    rows = query.order_by(SupportAccessGrant.requested_at.desc()).limit(200).all()
    orgs = {o.id: o.name for o in db.query(Organization).all()}
    return ok([
        {**support_access.describe(g), "organization": orgs.get(g.org_id, "")}
        for g in rows
    ])


@router.post("/support/grants")
def open_support_grant(
    body: SupportOpenRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Open a break-glass session, or request one where the client requires approval.

    Read-only and identity-masked, always. Time-boxed. Written to the client's
    own audit trail — not to a staff log they cannot see — because a support
    mechanism nobody can audit is a back door.
    """
    try:
        grant = support_access.open_grant(
            db, org_id=body.org_id, admin=admin, reason=body.reason, minutes=body.minutes,
        )
    except support_access.SupportAccessError as exc:
        raise _support_error(exc)

    opened = grant.state == "active"
    audit.record(
        db, entity_id=None, org_id=grant.org_id, user=admin,
        action="support.opened" if opened else "support.requested",
        object_type="support_access_grant", object_id=str(grant.id),
        summary=(
            f"{admin.email} {'opened' if opened else 'requested'} read-only support "
            f"access until {grant.expires_at:%d %b %Y %H:%M} UTC — {grant.reason}"
        ),
        detail={"policy": grant.policy_at_grant, "read_only": True, "masked": True},
    )
    db.commit()
    db.refresh(grant)
    return ok(support_access.describe(grant))


@router.post("/support/grants/{grant_id}/end")
def end_support_grant(
    grant_id: uuid.UUID,
    body: SupportEndRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Close your own session. Ending early is always available and never penalised."""
    grant = db.get(SupportAccessGrant, grant_id)
    if grant is None or grant.admin_user_id != admin.id:
        raise HTTPException(status_code=404, detail="Support session not found")

    support_access.end(db, grant, actor_email=admin.email, reason=body.reason)
    audit.record(
        db, entity_id=None, org_id=grant.org_id, user=admin, action="support.ended",
        object_type="support_access_grant", object_id=str(grant.id),
        summary=(
            f"{admin.email} ended their support session — {body.reason}. "
            f"Used {grant.use_count or 0} time(s)."
        ),
    )
    db.commit()
    db.refresh(grant)
    return ok(support_access.describe(grant))


# ---------------------------------------------------------------------------
# Security events and account protection
# ---------------------------------------------------------------------------
class UnlockRequest(BaseModel):
    email: EmailStr


def _security_officer(admin: User) -> None:
    if admin.platform_role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Platform owner or admin only")


@router.get("/security/events")
def security_events(
    request: Request,
    kind: str | None = None,
    outcome: str | None = None,
    subject: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Sign-ins, lockouts, two-step changes and session revocations — metadata
    about accounts, never payroll. No password, token or code is ever stored.
    """
    _security_officer(admin)
    q = db.query(SecurityEvent)
    if kind:
        q = q.filter(SecurityEvent.kind == kind)
    if outcome:
        q = q.filter(SecurityEvent.outcome == outcome)
    if subject:
        q = q.filter(SecurityEvent.subject == subject.strip().lower())
    rows = q.order_by(SecurityEvent.created_at.desc()).limit(limit).all()
    auth_security.event(db, request, kind="security_log_read", outcome="success", user=admin,
                        detail={"filters": {"kind": kind, "outcome": outcome, "subject": bool(subject)}}, commit=True)
    return ok([{
        "id": str(r.id), "at": r.created_at.isoformat() if r.created_at else None, "kind": r.kind,
        "outcome": r.outcome, "user_id": str(r.user_id) if r.user_id else None, "subject": r.subject,
        "client_ip": r.client_ip, "request_id": r.request_id, "detail": r.detail or {},
    } for r in rows])


@router.post("/security/unlock")
def security_unlock(body: UnlockRequest, request: Request, admin: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    """Lift a sign-in lock early. Locks expire on their own; this is for a caller on the phone."""
    _security_officer(admin)
    lifted = auth_security.unlock(db, body.email)
    auth_security.event(db, request, kind="unlock", outcome="changed", subject=body.email,
                        detail={"by": admin.email, "locks_lifted": lifted})
    db.commit()
    return ok({"locks_lifted": lifted})


@router.post("/staff/{user_id}/revoke-sessions")
def revoke_staff_sessions(user_id: uuid.UUID, request: Request, admin: User = Depends(require_admin),
                          db: Session = Depends(get_db)):
    """End every session a member of platform staff holds — a lost laptop, a departure."""
    if admin.platform_role != "owner" and admin.id != user_id:
        raise HTTPException(status_code=403, detail="Platform owner only")
    target = db.get(User, user_id)
    if target is None or target.platform_role is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    auth_security.end_all_sessions(db, request, target, reason="administrator", actor=admin)
    db.commit()
    return ok({"signed_out": True})
