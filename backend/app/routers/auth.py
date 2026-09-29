import secrets
import uuid
from datetime import datetime, timedelta, UTC

from fastapi import APIRouter, Depends, HTTPException
from jose import JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import SYSTEM_USER_EMAIL, get_current_user, require_admin
from app.envelope import ok
from app.models import Organization, PlatformInvitation, RefreshToken, User
from app.services import support_access, tenancy
from app.models.user import PasswordResetToken
from app.schemas.auth import (
    LoginRequest,
    PlatformInviteAccept,
    SupportSessionRequest,
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


def _issue_tokens(db: Session, user: User, *, portal: str = "client", org_id: uuid.UUID | None = None) -> TokenPair:
    if portal == "client" and org_id is None:
        membership = tenancy.get_membership(db, user)
        org_id = membership.org_id if membership else None
    claims = {"portal": portal, "org_id": str(org_id) if org_id else None}
    access = create_access_token(str(user.id), extra=claims)
    refresh = create_refresh_token(str(user.id), extra=claims)
    rt = RefreshToken(
        user_id=user.id,
        token_hash=token_fingerprint(refresh),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(rt)
    db.commit()
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/signup")
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    if not settings.allow_public_signup:
        raise HTTPException(status_code=404, detail="Workspace registration is invitation-only")
    email = body.email.lower().strip()
    if email == SYSTEM_USER_EMAIL:
        raise HTTPException(status_code=400, detail="Reserved email address")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Service accounts carry a users row for authorship only; they are not people.
    human_count = db.query(User).filter(
        User.email != SYSTEM_USER_EMAIL, User.role != "machine"
    ).count()
    role = "admin" if human_count == 0 else "user"

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        company_name=body.company_name,
        role=role,
        platform_role="owner" if role == "admin" else None,
    )
    db.add(user)
    db.flush()

    # Every user needs somewhere to put data. A fresh signup gets an
    # organization with one entity; a practice adds the rest of its client
    # book afterwards and flips org_type from the settings screen.
    tenancy.provision_org_for_user(db, user, org_name=body.company_name)

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
        or user.role in ("system", "machine")
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if settings.is_production and not body.workspace_slug:
        raise HTTPException(status_code=400, detail="Use your organization's workspace login URL")
    membership = tenancy.get_membership(db, user)
    if not membership:
        raise HTTPException(status_code=401, detail="No workspace membership for this account")
    org = db.get(Organization, membership.org_id)
    if not org or (body.workspace_slug and org.slug != body.workspace_slug):
        raise HTTPException(status_code=401, detail="Invalid workspace or credentials")
    tokens = _issue_tokens(db, user, org_id=org.id)
    return ok(tokens.model_dump())


@router.post("/platform-login")
def platform_login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or user.email == SYSTEM_USER_EMAIL or user.platform_role not in {"owner", "admin", "support"} or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid platform credentials")
    return ok(_issue_tokens(db, user, portal="platform").model_dump())


@router.post("/platform-invitations/register")
def register_platform_staff(body: PlatformInviteAccept, db: Session = Depends(get_db)):
    invite = db.query(PlatformInvitation).filter(
        PlatformInvitation.token_hash == token_fingerprint(body.token),
        PlatformInvitation.used_at.is_(None),
        PlatformInvitation.expires_at > datetime.now(UTC),
    ).first()
    if not invite:
        raise HTTPException(status_code=400, detail="Invalid or expired invitation")
    if db.query(User).filter(User.email == invite.email).first():
        raise HTTPException(status_code=409, detail="This email already has an account")
    user = User(email=invite.email, password_hash=hash_password(body.password), role="user", platform_role=invite.role)
    db.add(user)
    invite.used_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)
    return ok(_issue_tokens(db, user, portal="platform").model_dump())


@router.post("/support-session")
def open_support_session(body: SupportSessionRequest, staff: User = Depends(require_admin), db: Session = Depends(get_db)):
    if support_access.active_grant(db, staff, body.org_id) is None:
        raise HTTPException(status_code=403, detail="An active support grant is required")
    return ok(_issue_tokens(db, staff, portal="support", org_id=body.org_id).model_dump())


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
        .filter(RefreshToken.expires_at > datetime.now(UTC))
        .first()
    )
    if not row:
        raise HTTPException(status_code=401, detail="Refresh token revoked or expired")

    user = db.get(User, uid)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    portal = payload.get("portal", "client")
    org_id = payload.get("org_id")
    if portal == "platform":
        if user.platform_role not in {"owner", "admin", "support"}:
            raise HTTPException(status_code=401, detail="Platform access revoked")
    elif portal == "client":
        membership = tenancy.get_membership(db, user)
        if not membership or (org_id and str(membership.org_id) != org_id) or (settings.is_production and not org_id):
            raise HTTPException(status_code=401, detail="Workspace access revoked")
        org_id = str(membership.org_id)
    elif portal == "support":
        if not org_id or support_access.active_grant(db, user, uuid.UUID(org_id)) is None:
            raise HTTPException(status_code=401, detail="Support access ended")
    else:
        raise HTTPException(status_code=401, detail="Invalid session")
    db.delete(row)
    db.commit()

    tokens = _issue_tokens(db, user, portal=portal, org_id=uuid.UUID(org_id) if org_id else None)
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
    if user.role in ("system", "machine"):
        return ok({"sent": False})

    raw = secrets.token_urlsafe(32)
    pr = PasswordResetToken(
        user_id=user.id,
        token_hash=token_fingerprint(raw),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
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
        .filter(PasswordResetToken.expires_at > datetime.now(UTC))
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    user = db.get(User, row.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="User not found")
    user.password_hash = hash_password(body.new_password)
    row.used_at = datetime.now(UTC)
    db.add(user)
    db.commit()
    return ok({"password_updated": True})  # nosec B105
