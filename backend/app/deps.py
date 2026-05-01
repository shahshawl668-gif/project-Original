"""
Tenant context and JWT auth.

When `settings.allow_anonymous_api` is True, missing Authorization falls back to the
built-in system user (local dev). Set `allow_anonymous_api=False` for production.
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
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
