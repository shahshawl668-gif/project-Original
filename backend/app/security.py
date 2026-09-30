import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, UTC

from jose import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str, extra: dict | None = None) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire, "type": "access"}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str, extra: dict | None = None) -> str:
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    payload = {"sub": subject, "exp": expire, "type": "refresh", "jti": secrets.token_urlsafe(16)}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


MFA_CHALLENGE_MINUTES = 5


def create_mfa_challenge(subject: str, **claims) -> str:
    """
    Proof that the password step passed, good for five minutes and for nothing
    else: it is not an access token and no route accepts it but the second step.
    """
    expire = datetime.now(UTC) + timedelta(minutes=MFA_CHALLENGE_MINUTES)
    payload = {"sub": subject, "exp": expire, "type": "mfa_challenge", "jti": secrets.token_urlsafe(8), **claims}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def safe_request_id(supplied: str | None) -> str:
    """
    The caller's X-Request-Id if it is a plain token, otherwise a fresh one.

    It is written into every log line and the security event log, so a value
    carrying newlines or markup would let a caller forge log entries.
    """
    if supplied and _REQUEST_ID.match(supplied):
        return supplied
    return uuid.uuid4().hex[:12]
