"""Admin-only tenant user management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import SYSTEM_USER_EMAIL, require_admin
from app.envelope import ok
from app.models import (
    DEFAULT_MINUTES,
    MAX_MINUTES,
    Organization,
    SupportAccessGrant,
    User,
)
from app.schemas.auth import AdminRoleUpdate, UserOut
from app.services import audit, support_access

router = APIRouter(prefix="/admin", tags=["admin"])


def _admin_count(db: Session) -> int:
    return (
        db.query(User)
        .filter(User.role == "admin", User.email != SYSTEM_USER_EMAIL)
        .count()
    )


@router.get("/users")
def list_tenant_users(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(User)
        .filter(User.email != SYSTEM_USER_EMAIL)
        .order_by(User.created_at.asc())
        .all()
    )
    return ok([UserOut.model_validate(u).model_dump() for u in rows])


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
