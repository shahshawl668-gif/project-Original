"""Admin-only tenant user management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import SYSTEM_USER_EMAIL, require_admin
from app.envelope import ok
from app.models import User
from app.schemas.auth import AdminRoleUpdate, UserOut

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
    if target_id == admin.id and body.role == "user":
        if _admin_count(db) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot demote yourself while you are the only admin.",
            )

    tgt = db.get(User, target_id)
    if not tgt:
        raise HTTPException(status_code=404, detail="User not found")
    if tgt.email == SYSTEM_USER_EMAIL or tgt.role == "system":
        raise HTTPException(status_code=400, detail="Cannot change system account role")

    if body.role == "user" and tgt.role == "admin":
        if _admin_count(db) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot demote the last admin. Promote another user first.",
            )

    tgt.role = body.role
    db.add(tgt)
    db.commit()
    db.refresh(tgt)
    return ok(UserOut.model_validate(tgt).model_dump())
