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
        return entity

    entity = tenancy.default_entity(db, user)
    if entity is not None:
        return entity

    _, entity = tenancy.provision_org_for_user(db, user)
    db.commit()
    db.refresh(entity)
    return entity


def require_entity_write(
    entity: Entity = Depends(get_current_entity),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Entity:
    """Entity context for mutating endpoints — viewers are read-only."""
    if not tenancy.role_at_least(db, user, "analyst"):
        raise HTTPException(status_code=403, detail="Your role does not permit changes")
    return entity


def require_org_admin(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    """Managing entities and members is restricted to owners and managers."""
    if not tenancy.role_at_least(db, user, "manager"):
        raise HTTPException(status_code=403, detail="Owner or manager access required")
    return user
