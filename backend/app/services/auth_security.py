"""
Sign-in protection: throttling, session revocation, one-time passwords, and
the security event log.

Four promises, each tested in tests/test_auth_security.py:

* **Guessing is slowed per account, whether or not the account exists.** After
  ``LOGIN_MAX_FAILURES`` wrong answers inside the window the identifier is
  refused for ``LOGIN_LOCKOUT_MINUTES`` — the right password included, so a
  lock cannot be tested for. An address with no account is locked the same
  way, so the refusal says nothing about who has an account. A lock expires on
  its own: nothing here can shut an administrator out for good, and
  ``python -m app.auth_recovery unlock`` lifts one early.
* **A session can be ended everywhere.** Tokens carry the user's
  ``session_version``. Raising it ends every session at its next request.
* **A replayed refresh token ends the family.** A rotated refresh token that
  comes back after the grace window means two parties hold it; every session
  of that user is ended and the event recorded.
* **A one-time password is a vetted implementation.** TOTP is
  ``cryptography``'s RFC 6238 code; nothing here is home-made cryptography.
  The shared secret is stored under the application secrets key.

Nothing written here — event, log line or response — carries a password, a
token, a one-time code or a recovery code.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import time
import uuid
from base64 import b32decode, b32encode
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives.hashes import SHA1
from cryptography.hazmat.primitives.twofactor import InvalidToken
from cryptography.hazmat.primitives.twofactor.totp import TOTP
from fastapi import HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import LoginThrottle, RefreshToken, SecurityEvent, User

logger = logging.getLogger("payroll.security")

TOTP_DIGITS = 6
TOTP_STEP = 30
RECOVERY_CODES = 10
ISSUER = "PeopleOpsLab"

# A bcrypt hash of a random value, verified against when the account does not
# exist, so a wrong address costs the same time as a wrong password.
_DUMMY_HASH: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


# ── request context ─────────────────────────────────────────────────────────

_IP = re.compile(r"^[0-9A-Fa-f:.]{2,45}$")


def client_ip(request: Request | None) -> str | None:
    """The nearest proxy's claim about the caller. Informational only."""
    if request is None:
        return None
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded and _IP.match(forwarded):
        return forwarded
    return request.client.host if request.client else None


def request_id(request: Request | None) -> str | None:
    if request is None:
        return None
    return getattr(request.state, "request_id", None)


# ── the event log ───────────────────────────────────────────────────────────

def event(
    db: Session,
    request: Request | None,
    *,
    kind: str,
    outcome: str,
    user: User | None = None,
    subject: str | None = None,
    detail: dict[str, Any] | None = None,
    commit: bool = False,
) -> None:
    db.add(SecurityEvent(
        kind=kind, outcome=outcome,
        user_id=getattr(user, "id", None),
        subject=(subject or getattr(user, "email", None) or "")[:255].lower() or None,
        client_ip=client_ip(request), request_id=request_id(request),
        detail=detail or {},
    ))
    # The log line names the event, never the identifier: general logs are
    # read by more people, for longer, than the security log.
    logger.info("security event kind=%s outcome=%s request_id=%s", kind, outcome, request_id(request))
    if commit:
        db.commit()


# ── throttling ──────────────────────────────────────────────────────────────

def _key(scope: str, identifier: str) -> str:
    return f"{scope}:{identifier.strip().lower()}"[:300]


def check_not_locked(db: Session, request: Request | None, scope: str, identifier: str) -> None:
    row = db.get(LoginThrottle, _key(scope, identifier))
    until = _aware(row.locked_until) if row else None
    if until and until > _now():
        wait = max(1, int((until - _now()).total_seconds()))
        event(db, request, kind=scope, outcome="blocked", subject=identifier,
              detail={"retry_after_seconds": wait}, commit=True)
        raise HTTPException(
            status_code=429,
            detail="Too many unsuccessful attempts. Try again later.",
            headers={"Retry-After": str(wait)},
        )


def note_failure(db: Session, request: Request | None, scope: str, identifier: str,
                 user: User | None = None, reason: str = "credentials", outcome: str = "failure") -> None:
    key = _key(scope, identifier)
    now = _now()
    window = timedelta(minutes=settings.login_failure_window_minutes)
    row = db.get(LoginThrottle, key)
    if row is None:
        row = LoginThrottle(key=key, failures=0, window_started_at=now)
        db.add(row)
    elif _aware(row.window_started_at) + window < now:
        row.failures, row.window_started_at, row.locked_until = 0, now, None
    row.failures += 1
    locked = row.failures >= settings.login_max_failures
    if locked:
        row.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
    event(db, request, kind=scope, outcome=outcome, user=user, subject=identifier,
          detail={"reason": reason, "attempts": row.failures, "locked": locked})
    try:
        db.commit()
    except IntegrityError:  # two failures raced to create the row; the other one counted
        db.rollback()


def clear_failures(db: Session, scope: str, identifier: str) -> None:
    row = db.get(LoginThrottle, _key(scope, identifier))
    if row is not None:
        db.delete(row)


def unlock(db: Session, identifier: str) -> int:
    """Lift every lock on an identifier. For the recovery tool and administrators."""
    n = 0
    for scope in ("login", "platform_login", "mfa", "password_reset"):
        row = db.get(LoginThrottle, _key(scope, identifier))
        if row is not None:
            db.delete(row)
            n += 1
    return n


def spend_equal_time(password: str) -> None:
    """Verify against a throwaway hash so an unknown address is not faster to reject."""
    global _DUMMY_HASH
    from app.security import hash_password, verify_password

    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
    verify_password(password, _DUMMY_HASH)


# ── sessions ────────────────────────────────────────────────────────────────

def token_version(payload: dict) -> int:
    try:
        return int(payload.get("sv", 0))
    except (TypeError, ValueError):
        return -1


def session_current(user: User, payload: dict) -> bool:
    return token_version(payload) == int(user.session_version or 0)


def end_all_sessions(db: Session, request: Request | None, user: User, *, reason: str,
                     actor: User | None = None) -> None:
    """Every access and refresh token this user holds stops working. Does not commit."""
    user.session_version = int(user.session_version or 0) + 1
    db.query(RefreshToken).filter(RefreshToken.user_id == user.id).delete(synchronize_session=False)
    detail: dict[str, Any] = {"reason": reason}
    if actor is not None and actor.id != user.id:
        detail["by_user_id"] = str(actor.id)
        detail["by"] = actor.email
    event(db, request, kind="sessions_revoked", outcome="changed", user=user, detail=detail)


def replay_detected(row: RefreshToken) -> bool:
    rotated = _aware(row.rotated_at)
    if rotated is None:
        return False
    return (_now() - rotated).total_seconds() > settings.refresh_reuse_grace_seconds


def prune_refresh_tokens(db: Session, user_id: uuid.UUID) -> None:
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id, RefreshToken.expires_at < _now()
    ).delete(synchronize_session=False)


# ── one-time passwords ──────────────────────────────────────────────────────

def _totp(secret_b32: str) -> TOTP:
    raw = b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8))
    # HMAC-SHA1 is RFC 6238's default and the one every authenticator app
    # supports. SHA-1's collision weakness does not carry over to HMAC.
    return TOTP(raw, TOTP_DIGITS, SHA1(), TOTP_STEP)  # nosec B303


def new_secret() -> str:
    return b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def provisioning_uri(secret_b32: str, account: str) -> str:
    return _totp(secret_b32).get_provisioning_uri(account, ISSUER)


def seal_secret(secret_b32: str) -> str:
    from app.services.studio import secrets as store

    return store.seal({"purpose": "totp", "secret": secret_b32}).decode()


def unseal_secret(sealed: str | None) -> str | None:
    from app.services.studio import secrets as store

    if not sealed:
        return None
    return store.unseal(sealed.encode()).get("secret")


def verify_code(secret_b32: str, code: str, *, at: float | None = None, after_step: int | None = None) -> int | None:
    """
    The time step the code belongs to, or None.

    One step either side is accepted, for a phone clock a little off. A step at
    or before ``after_step`` is refused: a code that has signed someone in
    once is spent, even inside its 30 seconds.
    """
    code = re.sub(r"\s", "", code or "")
    if not re.fullmatch(r"\d{6}", code):
        return None
    now = time.time() if at is None else at
    otp = _totp(secret_b32)
    for drift in (0, -TOTP_STEP, TOTP_STEP):
        moment = int(now + drift)
        try:
            otp.verify(code.encode(), moment)
        except InvalidToken:
            continue
        step = moment // TOTP_STEP
        if after_step is not None and step <= after_step:
            return None
        return step
    return None


def accept_code(user: User, code: str) -> str | None:
    """'totp' or 'recovery' if the code is good (and spend it), else None. Does not commit."""
    secret = unseal_secret(user.mfa_secret_enc)
    if secret:
        step = verify_code(secret, code, after_step=user.mfa_last_step)
        if step is not None:
            user.mfa_last_step = step
            return "totp"
    if use_recovery_code(user, code):
        return "recovery"
    return None


def _digest(code: str) -> str:
    return hashlib.sha256(re.sub(r"[\s-]", "", code).lower().encode()).hexdigest()


def new_recovery_codes() -> tuple[list[str], list[str]]:
    """(codes to show once, digests to store)."""
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(RECOVERY_CODES)]
    return codes, [_digest(c) for c in codes]


def use_recovery_code(user: User, code: str) -> bool:
    digests = list(user.mfa_recovery_hashes or [])
    d = _digest(code)
    for stored in digests:
        if secrets.compare_digest(stored, d):
            digests.remove(stored)
            user.mfa_recovery_hashes = digests
            return True
    return False


def mfa_enabled(user: User) -> bool:
    return bool(user.mfa_enabled_at and user.mfa_secret_enc)


def mfa_required(db: Session, portal: str, org_id: Any) -> bool:
    """Does this kind of session have to be a two-step one?"""
    if portal == "platform":
        return settings.require_mfa_for_platform_staff
    if portal == "client" and org_id:
        from app.services import approvals

        try:
            return bool(approvals.policy_for(db, uuid.UUID(str(org_id))).get("members_require_mfa"))
        except ValueError:
            return False
    return False


def mfa_required_but_missing(db: Session, user: User, portal: str, org_id: Any) -> bool:
    """Required and not yet enrolled: signed in, but only to enrol. Nobody is locked out by it."""
    return not mfa_enabled(user) and mfa_required(db, portal, org_id)


def session_too_old(payload: dict) -> bool:
    """Past the absolute lifetime of the sign-in that began it. A token from before the claim existed is not."""
    started = payload.get("auth_time")
    if not isinstance(started, (int, float)):
        return False
    return time.time() - started > settings.session_absolute_hours * 3600
