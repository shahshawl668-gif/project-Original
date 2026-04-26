import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
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
from app.config import settings

router = APIRouter()


@router.post("/signup", response_model=TokenPair)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        company_name=body.company_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))
    rt = RefreshToken(
        user_id=user.id,
        token_hash=token_fingerprint(refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(rt)
    db.commit()
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))
    rt = RefreshToken(
        user_id=user.id,
        token_hash=token_fingerprint(refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(rt)
    db.commit()
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenPair)
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

    db.delete(row)
    db.commit()

    access = create_access_token(str(uid))
    new_refresh = create_refresh_token(str(uid))
    rt = RefreshToken(
        user_id=uid,
        token_hash=token_fingerprint(new_refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(rt)
    db.commit()
    return TokenPair(access_token=access, refresh_token=new_refresh)


@router.post("/logout", status_code=204)
def logout(
    body: RefreshRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    fp = token_fingerprint(body.refresh_token)
    db.query(RefreshToken).filter(RefreshToken.user_id == user.id, RefreshToken.token_hash == fp).delete()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/password-reset-request", status_code=202)
def password_reset_request(body: PasswordResetRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user:
        return None

    raw = secrets.token_urlsafe(32)
    pr = PasswordResetToken(
        user_id=user.id,
        token_hash=token_fingerprint(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(pr)
    db.commit()
    # In production, email raw token to user. For dev, log is avoided; return 202 only.
    return None


@router.post("/password-reset-confirm", status_code=204)
def password_reset_confirm(body: PasswordResetConfirm, db: Session = Depends(get_db)) -> Response:
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
    return Response(status_code=status.HTTP_204_NO_CONTENT)
