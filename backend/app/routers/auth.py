import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import SYSTEM_USER_EMAIL, get_current_user
from app.envelope import ok
from app.models import RefreshToken, User
from app.models.user import PasswordResetToken
from app.schemas.auth import (
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    SignupRequest,
    TokenPair,
    UserOut,
)
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_fingerprint,
    verify_password,
)

router = APIRouter()


def _issue_tokens(db: Session, user: User) -> TokenPair:
    access = create_access_token(str(user.id), extra={"role": user.role})
    refresh = create_refresh_token(str(user.id))
    rt = RefreshToken(
        user_id=user.id,
        token_hash=token_fingerprint(refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(rt)
    db.commit()
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/signup")
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    email = body.email.lower().strip()
    if email == SYSTEM_USER_EMAIL:
        raise HTTPException(status_code=400, detail="Reserved email address")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    human_count = db.query(User).filter(User.email != SYSTEM_USER_EMAIL).count()
    role = "admin" if human_count == 0 else "user"

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        company_name=body.company_name,
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    tokens = _issue_tokens(db, user)
    return ok(tokens.model_dump())


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if (
        not user
        or user.email == SYSTEM_USER_EMAIL
        or user.role == "system"
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    tokens = _issue_tokens(db, user)
    return ok(tokens.model_dump())


@router.post("/refresh")
def refresh_token(body: RefreshRequest, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token")
        uid = uuid.UUID(payload["sub"])
    except (JWTError, ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    fp = token_fingerprint(body.refresh_token)
    row = (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == uid, RefreshToken.token_hash == fp)
        .filter(RefreshToken.expires_at > datetime.now(timezone.utc))
        .first()
    )
    if not row:
        raise HTTPException(status_code=401, detail="Refresh token revoked or expired")

    user = db.get(User, uid)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    db.delete(row)
    db.commit()

    tokens = _issue_tokens(db, user)
    return ok(tokens.model_dump())


@router.post("/logout")
def logout(body: RefreshRequest, db: Session = Depends(get_db)):
    """Revokes the given refresh token (no access token required)."""
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=400, detail="Invalid token type")
        uid = uuid.UUID(payload["sub"])
    except (JWTError, ValueError, KeyError):
        raise HTTPException(status_code=400, detail="Invalid refresh token")

    fp = token_fingerprint(body.refresh_token)
    db.query(RefreshToken).filter(RefreshToken.user_id == uid, RefreshToken.token_hash == fp).delete()
    db.commit()
    return ok({"logged_out": True})


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return ok(UserOut.model_validate(user).model_dump())


@router.post("/password-reset-request")
def password_reset_request(body: PasswordResetRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user:
        return ok({"sent": False})
    if user.role == "system":
        return ok({"sent": False})

    raw = secrets.token_urlsafe(32)
    pr = PasswordResetToken(
        user_id=user.id,
        token_hash=token_fingerprint(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(pr)
    db.commit()
    return ok({"sent": True})


@router.post("/password-reset-confirm")
def password_reset_confirm(body: PasswordResetConfirm, db: Session = Depends(get_db)):
    fp = token_fingerprint(body.token)
    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == fp, PasswordResetToken.used_at.is_(None))
        .filter(PasswordResetToken.expires_at > datetime.now(timezone.utc))
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    user = db.get(User, row.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="User not found")
    user.password_hash = hash_password(body.new_password)
    row.used_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    return ok({"password_updated": True})
