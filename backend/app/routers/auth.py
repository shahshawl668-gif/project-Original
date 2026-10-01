import secrets
import time
import uuid
from datetime import datetime, timedelta, UTC

from fastapi import APIRouter, Depends, HTTPException, Request
from jwt import PyJWTError as JWTError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import SYSTEM_USER_EMAIL, get_current_user, require_admin
from app.envelope import ok
from app.models import Organization, PlatformInvitation, RefreshToken, User
from app.services import auth_security as guard
from app.services import support_access, tenancy
from app.models.user import PasswordResetToken
from app.schemas.auth import (
    LoginRequest,
    MfaChange,
    MfaEnable,
    MfaVerify,
    PasswordChange,
    PasswordConfirm,
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
    create_mfa_challenge,
    create_refresh_token,
    decode_token,
    hash_password,
    token_fingerprint,
    verify_password,
)

router = APIRouter()

STAFF_ROLES = {"owner", "admin", "support"}


def _issue_tokens(db: Session, user: User, *, portal: str = "client", org_id: uuid.UUID | None = None,
                  auth_time: int | None = None, session_id: str | None = None,
                  request: Request | None = None) -> TokenPair:
    """
    ``auth_time`` is when the person signed in and ``session_id`` which sign-in
    this is: a refresh carries both forward, a sign-in starts both.
    """
    if portal == "client" and org_id is None:
        membership = tenancy.get_membership(db, user)
        org_id = membership.org_id if membership else None
    started = int(auth_time or time.time())
    try:
        sid = uuid.UUID(str(session_id)) if session_id else uuid.uuid4()
    except ValueError:
        sid = uuid.uuid4()
    claims = {"portal": portal, "org_id": str(org_id) if org_id else None, "sv": int(user.session_version or 0),
              "auth_time": started, "sid": str(sid)}
    if guard.mfa_required_but_missing(db, user, portal, org_id):
        # Signed in to do one thing: set up two-step sign-in (see deps).
        claims["enrol_mfa"] = True
    access = create_access_token(str(user.id), extra=claims)
    refresh = create_refresh_token(str(user.id), extra=claims)
    guard.prune_refresh_tokens(db, user.id)
    agent = (request.headers.get("user-agent") or "")[:200] if request is not None else ""
    rt = RefreshToken(
        user_id=user.id,
        token_hash=token_fingerprint(refresh),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
        session_id=sid,
        signed_in_at=datetime.fromtimestamp(started, UTC),
        portal=portal,
        user_agent=agent or None,
    )
    db.add(rt)
    db.commit()
    return TokenPair(access_token=access, refresh_token=refresh)


def _signed_in(db: Session, request: Request, user: User, *, kind: str, portal: str,
               org_id: uuid.UUID | None, identifier: str) -> dict:
    """Password accepted. Either the session, or the second step it still needs."""
    if guard.mfa_enabled(user):
        guard.event(db, request, kind=kind, outcome="success", user=user,
                    detail={"step": "password", "next": "mfa"}, commit=True)
        token = create_mfa_challenge(str(user.id), portal=portal, org_id=str(org_id) if org_id else None,
                                     sv=int(user.session_version or 0), scope=kind, identifier=identifier)
        return {"mfa_required": True, "mfa_token": token}
    guard.clear_failures(db, kind, identifier)
    guard.event(db, request, kind=kind, outcome="success", user=user, detail={"mfa": False})
    return _issue_tokens(db, user, portal=portal, org_id=org_id, request=request).model_dump()


def _refuse(db: Session, request: Request, kind: str, identifier: str, user: User | None,
            password: str | None, detail: str, reason: str = "credentials", status: int = 401):
    if user is None and password is not None:
        guard.spend_equal_time(password)
    guard.note_failure(db, request, kind, identifier, user=user, reason=reason)
    raise HTTPException(status_code=status, detail=detail)


@router.post("/signup")
def signup(body: SignupRequest, request: Request, db: Session = Depends(get_db)):
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
    tokens = _issue_tokens(db, user, request=request)
    return ok(tokens.model_dump())


@router.post("/login")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ident = body.email.lower().strip()
    guard.check_not_locked(db, request, "login", ident)
    user = db.query(User).filter(User.email == ident).first()
    if not user or user.email == SYSTEM_USER_EMAIL or user.role in ("system", "machine"):
        _refuse(db, request, "login", ident, None, body.password, "Invalid email or password")
    if not verify_password(body.password, user.password_hash):
        _refuse(db, request, "login", ident, user, None, "Invalid email or password")
    if settings.is_production and not body.workspace_slug:
        raise HTTPException(status_code=400, detail="Use your organization's workspace login URL")
    membership = tenancy.get_membership(db, user)
    if not membership:
        _refuse(db, request, "login", ident, user, None, "No workspace membership for this account", "membership")
    org = db.get(Organization, membership.org_id)
    if not org or (body.workspace_slug and org.slug != body.workspace_slug):
        _refuse(db, request, "login", ident, user, None, "Invalid workspace or credentials", "workspace")
    return ok(_signed_in(db, request, user, kind="login", portal="client", org_id=org.id, identifier=ident))


@router.post("/platform-login")
def platform_login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ident = body.email.lower().strip()
    guard.check_not_locked(db, request, "platform_login", ident)
    user = db.query(User).filter(User.email == ident).first()
    if not user or user.email == SYSTEM_USER_EMAIL or user.platform_role not in STAFF_ROLES:
        _refuse(db, request, "platform_login", ident, None, body.password, "Invalid platform credentials")
    if not verify_password(body.password, user.password_hash):
        _refuse(db, request, "platform_login", ident, user, None, "Invalid platform credentials")
    return ok(_signed_in(db, request, user, kind="platform_login", portal="platform", org_id=None, identifier=ident))


@router.post("/mfa/verify")
def mfa_verify(body: MfaVerify, request: Request, db: Session = Depends(get_db)):
    """The second step: a code from the authenticator app, or one recovery code."""
    try:
        claims = decode_token(body.mfa_token)
        if claims.get("type") != "mfa_challenge":
            raise ValueError
        uid = uuid.UUID(claims["sub"])
    except (JWTError, ValueError, KeyError):
        raise HTTPException(status_code=401, detail="The sign-in has expired. Start again.")
    scope_key = str(uid)
    guard.check_not_locked(db, request, "mfa", scope_key)
    user = db.get(User, uid)
    if user is None or not guard.mfa_enabled(user) or not guard.session_current(user, claims):
        raise HTTPException(status_code=401, detail="The sign-in has expired. Start again.")
    method = guard.accept_code(user, body.code)
    if method is None:
        guard.note_failure(db, request, "mfa", scope_key, user=user, reason="code")
        raise HTTPException(status_code=401, detail="That code is not right, or has already been used.")
    portal = claims.get("portal", "client")
    org_id = claims.get("org_id")
    if portal == "client":
        membership = tenancy.get_membership(db, user)
        if not membership or str(membership.org_id) != org_id:
            raise HTTPException(status_code=401, detail="Workspace access revoked")
    elif portal != "platform" or user.platform_role not in STAFF_ROLES:
        raise HTTPException(status_code=401, detail="Platform access revoked")
    guard.clear_failures(db, "mfa", scope_key)
    guard.clear_failures(db, claims.get("scope", "login"), claims.get("identifier", user.email))
    guard.event(db, request, kind="mfa", outcome="success", user=user,
                detail={"method": method, "recovery_codes_left": len(user.mfa_recovery_hashes or [])})
    return ok(_issue_tokens(db, user, portal=portal, org_id=uuid.UUID(org_id) if org_id else None,
                            request=request).model_dump())


@router.post("/platform-invitations/register")
def register_platform_staff(body: PlatformInviteAccept, request: Request, db: Session = Depends(get_db)):
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
    db.flush()
    guard.event(db, request, kind="platform_invitation", outcome="success", user=user, detail={"role": invite.role})
    db.commit()
    db.refresh(user)
    return ok(_issue_tokens(db, user, portal="platform", request=request).model_dump())


@router.post("/support-session")
def open_support_session(body: SupportSessionRequest, request: Request, staff: User = Depends(require_admin),
                         db: Session = Depends(get_db)):
    if support_access.active_grant(db, staff, body.org_id) is None:
        guard.event(db, request, kind="support_session", outcome="failure", user=staff,
                    detail={"org_id": str(body.org_id), "reason": "no active grant"}, commit=True)
        raise HTTPException(status_code=403, detail="An active support grant is required")
    guard.event(db, request, kind="support_session", outcome="success", user=staff, detail={"org_id": str(body.org_id)})
    return ok(_issue_tokens(db, staff, portal="support", org_id=body.org_id, request=request).model_dump())


@router.post("/refresh")
def refresh_token(body: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token")
        uid = uuid.UUID(payload["sub"])
    except (JWTError, ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    fp = token_fingerprint(body.refresh_token)
    row = db.query(RefreshToken).filter(RefreshToken.user_id == uid, RefreshToken.token_hash == fp).first()
    if row is not None and row.rotated_at is not None:
        if guard.replay_detected(row):
            # Rotated a while ago and presented again: two parties hold it.
            # Which one is the user is unknowable, so both lose the session.
            user = db.get(User, uid)
            if user is not None:
                guard.end_all_sessions(db, request, user, reason="refresh_token_replay")
                guard.event(db, request, kind="refresh", outcome="detected", user=user,
                            detail={"reason": "a rotated refresh token was presented again"})
                db.commit()
        raise HTTPException(status_code=401, detail="Refresh token revoked or expired")
    expires = guard._aware(row.expires_at) if row else None
    if row is None or expires is None or expires <= datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Refresh token revoked or expired")

    user = db.get(User, uid)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not guard.session_current(user, payload):
        raise HTTPException(status_code=401, detail="Session ended. Sign in again.")
    if guard.session_too_old(payload):
        guard.event(db, request, kind="refresh", outcome="failure", user=user,
                    detail={"reason": "absolute session lifetime reached"}, commit=True)
        raise HTTPException(status_code=401, detail="Your session has reached its time limit. Sign in again.")

    portal = payload.get("portal", "client")
    org_id = payload.get("org_id")
    if portal == "platform":
        if user.platform_role not in STAFF_ROLES:
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
    # Exactly one exchange wins, even when two arrive together.
    won = db.execute(
        update(RefreshToken).where(RefreshToken.id == row.id, RefreshToken.rotated_at.is_(None))
        .values(rotated_at=datetime.now(UTC))
    ).rowcount
    db.commit()
    if won != 1:
        raise HTTPException(status_code=401, detail="Refresh token revoked or expired")

    started = payload.get("auth_time")
    tokens = _issue_tokens(db, user, portal=portal, org_id=uuid.UUID(org_id) if org_id else None,
                           auth_time=int(started) if isinstance(started, (int, float)) else None,
                           session_id=payload.get("sid") or (str(row.session_id) if row.session_id else None),
                           request=request)
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


@router.post("/sessions/revoke-all")
def revoke_all_sessions(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Sign out everywhere, this device included."""
    if user.role == "system":
        raise HTTPException(status_code=400, detail="The built-in account has no sessions to end")
    guard.end_all_sessions(db, request, user, reason="user_request")
    db.commit()
    return ok({"signed_out": True})


@router.get("/sessions")
def list_sessions(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Where you are signed in (OWASP ASVS 5.0 7.5.2): one row per sign-in, its
    portal, when it began, when it last refreshed, and the browser it named.
    """
    current = (getattr(request.state, "auth_claims", {}) or {}).get("sid")
    rows = (db.query(RefreshToken)
            .filter(RefreshToken.user_id == user.id, RefreshToken.rotated_at.is_(None),
                    RefreshToken.expires_at > datetime.now(UTC))
            .order_by(RefreshToken.created_at.desc()).all())
    return ok([{
        "id": str(r.session_id or r.id),
        "portal": r.portal,
        "signed_in_at": r.signed_in_at.isoformat() if r.signed_in_at else None,
        "last_active_at": r.created_at.isoformat() if r.created_at else None,
        "browser": r.user_agent,
        "current": bool(current and r.session_id and str(r.session_id) == current),
    } for r in rows])


@router.post("/sessions/{session_id}/end")
def end_session(session_id: uuid.UUID, body: PasswordConfirm, request: Request,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    End one sign-in, after confirming the password. Its refresh is refused at
    once; an access token it already holds lasts until it expires (at most
    ACCESS_TOKEN_EXPIRE_MINUTES). "Sign out everywhere" is immediate.
    """
    _own_account(request, user)
    _recheck_password(db, request, user, body.password)
    ended = db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id,
        (RefreshToken.session_id == session_id) | (RefreshToken.id == session_id),
    ).delete(synchronize_session=False)
    if not ended:
        raise HTTPException(status_code=404, detail="No such session")
    guard.event(db, request, kind="session_ended", outcome="changed", user=user,
                detail={"session": str(session_id)})
    db.commit()
    return ok({"ended": True})


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return ok(UserOut.model_validate(user).model_dump())


# ── two-step sign-in ────────────────────────────────────────────────────────

def _own_account(request: Request, user: User, what: str = "two-step sign-in") -> None:
    """A support session acts inside a client's workspace; it never changes the staff member's own sign-in."""
    if (getattr(request.state, "auth_claims", {}) or {}).get("portal") == "support" or user.role in ("system", "machine"):
        raise HTTPException(status_code=403, detail=f"Change {what} from your own session")


def _recheck_password(db: Session, request: Request, user: User, password: str) -> None:
    guard.check_not_locked(db, request, "mfa", str(user.id))
    if not verify_password(password, user.password_hash):
        guard.note_failure(db, request, "mfa", str(user.id), user=user, reason="password")
        raise HTTPException(status_code=401, detail="That password is not right")


@router.get("/mfa")
def mfa_status(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    claims = getattr(request.state, "auth_claims", {}) or {}
    return ok({
        "enabled": guard.mfa_enabled(user),
        "enabled_at": user.mfa_enabled_at.isoformat() if user.mfa_enabled_at else None,
        "recovery_codes_left": len(user.mfa_recovery_hashes or []) if guard.mfa_enabled(user) else 0,
        "required": bool(claims.get("enrol_mfa")) or guard.mfa_required(
            db, claims.get("portal", "client"), claims.get("org_id")),
    })


@router.post("/mfa/setup")
def mfa_setup(body: PasswordConfirm, request: Request, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """A new secret, pending until a code from it is entered. Shown once."""
    _own_account(request, user)
    if guard.mfa_enabled(user):
        raise HTTPException(status_code=409, detail="Two-step sign-in is already on. Turn it off first to change device.")
    _recheck_password(db, request, user, body.password)
    secret = guard.new_secret()
    user.mfa_secret_enc = guard.seal_secret(secret)
    user.mfa_enabled_at = None
    db.commit()
    return ok({"secret": secret, "otpauth_uri": guard.provisioning_uri(secret, user.email)})


@router.post("/mfa/enable")
def mfa_enable(body: MfaEnable, request: Request, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    _own_account(request, user)
    if guard.mfa_enabled(user):
        raise HTTPException(status_code=409, detail="Two-step sign-in is already on")
    guard.check_not_locked(db, request, "mfa", str(user.id))
    secret = guard.unseal_secret(user.mfa_secret_enc)
    step = guard.verify_code(secret, body.code) if secret else None
    if step is None:
        guard.note_failure(db, request, "mfa", str(user.id), user=user, reason="enrolment code")
        raise HTTPException(status_code=400, detail="That code is not right. Check the time on your phone and try again.")
    codes, digests = guard.new_recovery_codes()
    user.mfa_enabled_at = datetime.now(UTC)
    user.mfa_last_step = step
    user.mfa_recovery_hashes = digests
    guard.event(db, request, kind="mfa_enrolled", outcome="changed", user=user)
    # Sessions opened before enrolment were not second-factor sessions.
    guard.end_all_sessions(db, request, user, reason="mfa_enabled")
    db.commit()
    claims = request.state.auth_claims or {}
    tokens = _issue_tokens(db, user, portal=claims.get("portal", "client"), org_id=_claim_org(request),
                           auth_time=claims.get("auth_time"), session_id=claims.get("sid"), request=request)
    return ok({"recovery_codes": codes, **tokens.model_dump()})


@router.post("/mfa/disable")
def mfa_disable(body: MfaChange, request: Request, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    _own_account(request, user)
    if not guard.mfa_enabled(user):
        raise HTTPException(status_code=409, detail="Two-step sign-in is not on")
    _recheck_password(db, request, user, body.password)
    if guard.accept_code(user, body.code) is None:
        guard.note_failure(db, request, "mfa", str(user.id), user=user, reason="code")
        raise HTTPException(status_code=401, detail="That code is not right, or has already been used.")
    user.mfa_secret_enc = None
    user.mfa_enabled_at = None
    user.mfa_recovery_hashes = None
    user.mfa_last_step = None
    guard.event(db, request, kind="mfa_disabled", outcome="changed", user=user, detail={"by": "self"})
    db.commit()
    return ok({"enabled": False})


@router.post("/mfa/recovery-codes")
def mfa_new_recovery_codes(body: MfaChange, request: Request, user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """A fresh set of ten; the old set stops working."""
    _own_account(request, user)
    if not guard.mfa_enabled(user):
        raise HTTPException(status_code=409, detail="Two-step sign-in is not on")
    _recheck_password(db, request, user, body.password)
    if guard.accept_code(user, body.code) is None:
        guard.note_failure(db, request, "mfa", str(user.id), user=user, reason="code")
        raise HTTPException(status_code=401, detail="That code is not right, or has already been used.")
    codes, digests = guard.new_recovery_codes()
    user.mfa_recovery_hashes = digests
    guard.event(db, request, kind="mfa_recovery_codes", outcome="changed", user=user)
    db.commit()
    return ok({"recovery_codes": codes})


def _claim_org(request: Request) -> uuid.UUID | None:
    raw = (getattr(request.state, "auth_claims", {}) or {}).get("org_id")
    try:
        return uuid.UUID(raw) if raw else None
    except ValueError:
        return None


# ── password change ─────────────────────────────────────────────────────────

@router.post("/password")
def change_password(body: PasswordChange, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """
    Change your own password (OWASP ASVS 5.0 6.2.2, 6.2.3): the current one
    first, and the new one held to the same rules as sign-up.

    Every other sign-in ends, on every device — the usual reason to change a
    password is that someone else may know it. This device carries on with the
    pair returned. Two-step sign-in is untouched: the password is what changes.
    """
    _own_account(request, user, "your password")
    _recheck_password(db, request, user, body.current_password)
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="The new password is the same as the current one")
    user.password_hash = hash_password(body.new_password)
    # A reset link issued earlier would otherwise undo this change.
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id,
                                        PasswordResetToken.used_at.is_(None)).update({"used_at": datetime.now(UTC)})
    guard.event(db, request, kind="password_changed", outcome="changed", user=user)
    guard.end_all_sessions(db, request, user, reason="password_changed")
    db.commit()
    claims = request.state.auth_claims or {}
    tokens = _issue_tokens(db, user, portal=claims.get("portal", "client"), org_id=_claim_org(request),
                           auth_time=claims.get("auth_time"), session_id=claims.get("sid"), request=request)
    return ok(tokens.model_dump())


# ── password reset ──────────────────────────────────────────────────────────

@router.post("/password-reset-request")
def password_reset_request(body: PasswordResetRequest, request: Request, db: Session = Depends(get_db)):
    """
    The same answer whether or not the address has an account.

    This build has no mail service, so the token is not delivered anywhere; the
    endpoint exists for the flow's shape and is rate limited like sign-in.
    """
    ident = body.email.lower().strip()
    guard.check_not_locked(db, request, "password_reset", ident)
    user = db.query(User).filter(User.email == ident).first()
    guard.note_failure(db, request, "password_reset", ident, user=user,
                       reason="requested" if user else "no such account", outcome="requested")
    if user is not None and user.role not in ("system", "machine"):
        raw = secrets.token_urlsafe(32)
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=token_fingerprint(raw),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ))
        db.commit()
    return ok({"requested": True})


@router.post("/password-reset-confirm")
def password_reset_confirm(body: PasswordResetConfirm, request: Request, db: Session = Depends(get_db)):
    fp = token_fingerprint(body.token)
    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == fp, PasswordResetToken.used_at.is_(None))
        .filter(PasswordResetToken.expires_at > datetime.now(UTC))
        .first()
    )
    if not row:
        guard.event(db, request, kind="password_reset", outcome="failure", detail={"reason": "invalid token"},
                    commit=True)
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    user = db.get(User, row.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    user.password_hash = hash_password(body.new_password)
    now = datetime.now(UTC)
    # Every outstanding reset link for this account is spent, not just this one.
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id,
                                        PasswordResetToken.used_at.is_(None)).update({"used_at": now})
    guard.end_all_sessions(db, request, user, reason="password_reset")
    guard.event(db, request, kind="password_reset", outcome="changed", user=user)
    guard.unlock(db, user.email)
    db.commit()
    return ok({"password_updated": True})  # nosec B105
