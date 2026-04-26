"""
Authentication is disabled — all API calls are served as the single
built-in system user that is auto-created during application startup.

To re-enable per-user auth later, swap get_current_user back to a
JWT-based implementation.
"""
from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

SYSTEM_USER_EMAIL = "system@payrollcheck.local"


def get_current_user(db: Session = Depends(get_db)) -> User:
    """Return the system user. No token or session required."""
    user = db.query(User).filter(User.email == SYSTEM_USER_EMAIL).first()
    if user is None:
        raise RuntimeError(
            "System user not found. "
            "Make sure the application startup completed successfully."
        )
    return user


def get_tenant_context(user: User = Depends(get_current_user)) -> dict:
    return {"user_id": str(user.id), "tenant_id": str(user.id)}
