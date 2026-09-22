"""
Tenant context and JWT auth.

When `settings.allow_anonymous_api` is True, missing Authorization falls back to the
built-in system user (local dev). Set `allow_anonymous_api=False` for production.
"""
from __future__ import annotations

import uuid

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Entity, User
from app.services import tenancy
from app.security import decode_token

SYSTEM_USER_EMAIL = "system@payrollcheck.local"

security = HTTPBearer(auto_error=False)


def get_current_user(
    db: Session = Depends(get_db),
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> User:
    if settings.allow_anonymous_api and (creds is None or not creds.credentials):
        user = db.query(User).filter(User.email == SYSTEM_USER_EMAIL).first()
        if user is None:
            raise RuntimeError(
                "System user not found. Make sure the application startup completed successfully."
            )
        return user

    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_token(creds.credentials)
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        uid = uuid.UUID(str(payload["sub"]))
    except HTTPException:
        raise
    except (JWTError, ValueError, KeyError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = db.get(User, uid)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def _note_support_use(db: Session, user: User, entity: Entity) -> None:
    """
    Mark a support grant as having been used.

    A session opened and never used is a different fact from one that read the
    whole book, and the client is entitled to tell them apart.
    """
    membership = tenancy.get_membership(db, user)
    if membership is not None and membership.org_id == entity.org_id:
        return
    grant = tenancy.support_grant_for(db, user, entity)
    if grant is not None:
        from app.services import support_access

        support_access.note_use(db, grant)
        db.commit()


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def get_tenant_context(user: User = Depends(get_current_user)) -> dict:
    return {"user_id": str(user.id), "tenant_id": str(user.id)}


def get_current_entity(
    x_entity_id: str | None = Header(default=None, alias="X-Entity-Id"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Entity:
    """
    Resolve which entity this request is acting on.

    The client names it with an ``X-Entity-Id`` header. When it doesn't — a
    single-entity enterprise, or a first-load before the switcher has mounted —
    the user's default entity is used, which keeps the enterprise case
    header-free while still letting a practice switch clients per request.

    A user with no membership at all is provisioned one on the spot, so accounts
    created before entities existed keep working without a manual repair.
    """
    if x_entity_id:
        try:
            entity_uuid = uuid.UUID(x_entity_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid X-Entity-Id")
        entity = db.get(Entity, entity_uuid)
        if entity is None or not tenancy.can_access_entity(db, user, entity):
            # Same response whether it's missing or merely someone else's, so the
            # header can't be used to probe for entity ids across organizations.
            raise HTTPException(status_code=404, detail="Entity not found")
        _note_support_use(db, user, entity)
        return entity

    entity = tenancy.default_entity(db, user)
    if entity is not None:
        return entity

    _, entity = tenancy.provision_org_for_user(db, user)
    db.commit()
    db.refresh(entity)
    return entity


SUPPORT_READ_ONLY = (
    "Support access is read-only. Ask an owner at this organization to make the change."
)


def _must_be_member(db: Session, user: User, entity: Entity) -> None:
    """
    Writing to an entity requires a seat in its organization.

    The check that keeps break-glass support read-only, and it has to be this
    rather than a role check. A platform engineer holding a support grant is
    usually an *owner of their own organization*, so ``role_at_least`` — which
    reads their own membership — says yes. Without this, a support session
    could approve a budget or a JV mapping in someone else's ledger.
    """
    membership = tenancy.get_membership(db, user)
    if membership is None or membership.org_id != entity.org_id:
        raise HTTPException(status_code=403, detail=SUPPORT_READ_ONLY)


def require_entity_write(
    entity: Entity = Depends(get_current_entity),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Entity:
    """Entity context for mutating endpoints — viewers are read-only."""
    _must_be_member(db, user, entity)
    if not tenancy.role_at_least(db, user, "analyst"):
        raise HTTPException(status_code=403, detail="Your role does not permit changes")
    return entity


def require_entity_admin(
    entity: Entity = Depends(get_current_entity),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    """
    Owner or manager **of this entity's organization**.

    Distinct from ``require_org_admin``, which asks only about the caller's own
    organization. Approving a budget, a JV mapping or a period sign-off is a
    decision inside one client's books, so the seat has to be in that client's
    organization — not merely somewhere.
    """
    _must_be_member(db, user, entity)
    if not tenancy.role_at_least(db, user, "manager"):
        raise HTTPException(status_code=403, detail="Owner or manager access required")
    return user


def get_identity(
    x_mask_identity: str | None = Header(default=None, alias="X-Mask-Identity"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """
    Whether this request may see who earns what.

    Masked by default for anyone below analyst — a business-unit head reading
    their own cost should not thereby learn every salary in their team. Any
    caller can ask for masking explicitly with ``X-Mask-Identity: on``, which is
    what someone presenting to a room wants; nobody can ask their way *out* of
    it, because that decision belongs to their role.
    """
    from app.services.masking import Identity

    if (x_mask_identity or "").strip().lower() in {"1", "on", "true", "yes"}:
        return Identity(entity.id, True, "requested for this session")
    # A break-glass session never sees who earns what. Almost no bug lives in an
    # individual salary — they live in configuration, findings and totals, which
    # masking leaves entirely legible.
    membership = tenancy.get_membership(db, user)
    if membership is None or membership.org_id != entity.org_id:
        return Identity(entity.id, True, "support access is masked")
    if not tenancy.role_at_least(db, user, "analyst"):
        return Identity(entity.id, True, "your role does not include employee-level pay")
    return Identity(entity.id, False, "visible to your role")


def require_pay_equity(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
) -> Entity:
    """
    The gate on the gender pay gap analysis.

    Two conditions, both required. The entity must have the analysis switched
    on, because India mandates no gender pay reporting and running it is the
    employer's decision rather than the product's — and on a bureau's login one
    client authorising it must not enable it across the book. And the caller
    must be an owner or a manager: this is population-level pay data about a
    protected characteristic, and the analyst tier that can see individual
    salaries is deliberately *not* the tier that can see this.
    """
    if not getattr(entity, "pay_equity_enabled", False):
        raise HTTPException(
            status_code=403,
            detail="Pay equity analysis is not enabled for this entity. An owner or "
                   "manager can turn it on, and who did so is recorded.",
        )
    if not tenancy.role_at_least(db, user, "manager"):
        raise HTTPException(
            status_code=403,
            detail="Pay equity analysis is restricted to owners and managers.",
        )
    return entity


def require_org_admin(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    """Managing entities and members is restricted to owners and managers."""
    if not tenancy.role_at_least(db, user, "manager"):
        raise HTTPException(status_code=403, detail="Owner or manager access required")
    return user
