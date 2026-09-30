"""
Service accounts and their API keys.

**Separate from people.** A service account is created with a shadow ``users``
row whose role is ``machine``: no password hash anything can match, no
organisation membership, no company role. It exists only because upload, job
and audit tables carry a ``user_id``. Every human permission check therefore
fails for it; what it may do is exactly its scopes and its named companies,
checked by the integration API and nowhere else.

**Never wider than its creator.** Whoever creates or edits an account must be
an owner or manager of every company it names. A key cannot reach a company its
maker could not.

**Keys.** ``pol_<env>_<8 hex>_<secret>``. Only a SHA-256 of the whole key is
stored; the ``pol_<env>_<8 hex>`` prefix is kept in clear so a key found in a
log can be identified and revoked by someone who never saw the secret. Every
key expires (at most a year out); rotation issues a new key and lets the old
one live on for a stated grace period; revocation is immediate.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import Entity, IntegrationCredential, ServiceAccount, User
from app.services import audit, tenancy

#: What a key may be allowed to do. Each is narrow; none implies another.
SCOPES: dict[str, str] = {
    "imports:write": "Submit employee-master, CTC, attendance and salary-register imports",
    "imports:read": "Read import status, reconciliation counts and rejected records",
    "validation:run": "Start payroll validation for a month",
    "validation:read": "Read validation jobs, runs, results and findings",
    "results:employee": "Read per-employee pay detail in validation results",
    "findings:write": "Assign findings, set due dates, comment and acknowledge — never waive or resolve",
    "config:read": "Read the company's validation configuration",
    "config:propose": "Submit draft validation-rule changes for human approval — never publish",
    "bi:read": "Read aggregate BI metrics and their data basis",
    "signoff:read": "Read sign-off status, readiness and evidence metadata",
}

#: Scopes that change data, which only a write role may grant.
WRITE_SCOPES = {"imports:write", "validation:run", "findings:write", "config:propose"}

ENV_TAG = {"production": "live", "test": "test", "development": "dev"}
KEY_PATTERN = re.compile(r"^pol_(live|test|dev)_([0-9a-f]{8})_([A-Za-z0-9_-]{32,})$")

DEFAULT_EXPIRY_DAYS = 90
MAX_EXPIRY_DAYS = 365
DEFAULT_ROTATION_GRACE_HOURS = 24
MAX_ROTATION_GRACE_HOURS = 24 * 7
#: last_used_at is written at most this often, not on every request.
LAST_USED_RESOLUTION = timedelta(minutes=1)


class CredentialError(Exception):
    """Why a presented key was not accepted. ``code`` is the stable API code."""

    def __init__(self, code: str, message: str, status: int = 401):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class Principal:
    """Who an integration request is, once its key has been checked."""

    credential: IntegrationCredential
    account: ServiceAccount
    user: User
    scopes: set[str] = field(default_factory=set)
    entity_ids: set[str] = field(default_factory=set)

    @property
    def id(self) -> str:
        return f"sa:{self.account.id}"

    @property
    def label(self) -> str:
        return f"{self.account.name} (service account, key {self.credential.prefix})"


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def redact(text: str) -> str:
    """Replace anything that looks like a key's secret with its prefix only."""
    return re.sub(r"(pol_(?:live|test|dev)_[0-9a-f]{8})_[A-Za-z0-9_-]{8,}", r"\1_[redacted]", text)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
def _check_scopes(scopes: list[str]) -> list[str]:
    unknown = sorted(set(scopes) - set(SCOPES))
    if unknown:
        raise ValueError(f"Unknown scope(s): {', '.join(unknown)}")
    if not scopes:
        raise ValueError("Choose at least one scope.")
    return sorted(set(scopes))


def _check_companies(db: Session, actor: User, org_id: uuid.UUID, entity_ids: list[str], environment: str | None = None) -> list[str]:
    """Every named company must be in this organisation and managed by the actor."""
    if not entity_ids:
        raise ValueError("Choose at least one company this account may act on.")
    from app.services.studio.releases import environment_of

    out: list[str] = []
    for raw in entity_ids:
        try:
            entity = db.get(Entity, uuid.UUID(str(raw)))
        except ValueError:
            entity = None
        # Unknown, another organisation's, or one the actor cannot manage: the
        # same answer for all three, so the form cannot probe for company ids.
        if (entity is None or entity.org_id != org_id
                or not entity.is_active
                or not tenancy.role_at_least(db, actor, "manager", entity)):
            raise PermissionError("You can only grant access to companies you manage.")
        if environment is not None and environment_of(db, entity.id) != environment:
            raise ValueError("The key environment must match every selected company environment.")
        out.append(str(entity.id))
    return sorted(set(out))


def _shadow_user(db: Session, name: str) -> User:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "service"
    user = User(
        email=f"{slug}.{uuid.uuid4().hex[:8]}@service-account.invalid",
        # Not a bcrypt hash: no password can ever verify against it.
        password_hash="__machine__",  # nosec B106
        company_name=name,
        role="machine",
    )
    db.add(user)
    db.flush()
    return user


def create_account(
    db: Session,
    *,
    actor: User,
    org_id: uuid.UUID,
    name: str,
    description: str | None,
    environment: str,
    entity_ids: list[str],
    scopes: list[str],
) -> ServiceAccount:
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the service account a name.")
    if environment not in ENV_TAG:
        raise ValueError("Environment must be development, test or production.")
    scopes = _check_scopes(scopes)
    companies = _check_companies(db, actor, org_id, entity_ids, environment)
    if db.query(ServiceAccount).filter(ServiceAccount.org_id == org_id, ServiceAccount.name == name).first():
        raise ValueError(f"A service account called “{name}” already exists.")
    account = ServiceAccount(
        org_id=org_id, user_id=_shadow_user(db, name).id, name=name, description=description,
        environment=environment, entity_ids=companies, scopes=scopes, created_by=actor.id,
    )
    db.add(account)
    db.flush()
    audit.record(
        db, entity_id=None, org_id=org_id, user=actor, action="studio.service_account.created",
        object_type="service_account", object_id=str(account.id),
        summary=f"Created service account “{name}” ({environment}) with {len(scopes)} scope(s) "
                f"on {len(companies)} company(ies)",
        detail={"scopes": scopes, "entity_ids": companies, "environment": environment},
    )
    return account


def update_account(
    db: Session,
    account: ServiceAccount,
    *,
    actor: User,
    description: str | None = None,
    entity_ids: list[str] | None = None,
    scopes: list[str] | None = None,
    status: str | None = None,
) -> ServiceAccount:
    before = {"scopes": list(account.scopes), "entity_ids": list(account.entity_ids), "status": account.status}
    # Editing needs the same authority over the companies it already names:
    # otherwise removing a company would be a way to act on one you cannot see.
    _check_companies(db, actor, account.org_id, list(account.entity_ids), account.environment)
    if description is not None:
        account.description = description
    if scopes is not None:
        account.scopes = _check_scopes(scopes)
    if entity_ids is not None:
        account.entity_ids = _check_companies(db, actor, account.org_id, entity_ids, account.environment)
    if status is not None:
        if status not in ("active", "disabled"):
            raise ValueError("Status must be active or disabled.")
        account.status = status
        account.disabled_at = _now() if status == "disabled" else None
        account.disabled_by = actor.id if status == "disabled" else None
    after = {"scopes": list(account.scopes), "entity_ids": list(account.entity_ids), "status": account.status}
    audit.record(
        db, entity_id=None, org_id=account.org_id, user=actor, action="studio.service_account.updated",
        object_type="service_account", object_id=str(account.id),
        summary=f"Changed service account “{account.name}”",
        detail={"before": before, "after": after},
    )
    return account


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------
def issue(
    db: Session,
    account: ServiceAccount,
    *,
    actor: User,
    label: str,
    expires_in_days: int = DEFAULT_EXPIRY_DAYS,
    rotated_from: IntegrationCredential | None = None,
) -> tuple[IntegrationCredential, str]:
    """Create a key. Returns the row and the key — the only time it exists in clear."""
    if not 1 <= int(expires_in_days) <= MAX_EXPIRY_DAYS:
        raise ValueError(f"A key must expire within {MAX_EXPIRY_DAYS} days.")
    if account.status != "active":
        raise ValueError("This service account is disabled. Enable it before issuing a key.")
    _check_companies(db, actor, account.org_id, list(account.entity_ids))
    tag = ENV_TAG[account.environment]
    while True:
        short = secrets.token_hex(4)
        prefix = f"pol_{tag}_{short}"
        if db.query(IntegrationCredential.id).filter(IntegrationCredential.prefix == prefix).first() is None:
            break
    key = f"{prefix}_{secrets.token_urlsafe(32)}"
    credential = IntegrationCredential(
        service_account_id=account.id, org_id=account.org_id, label=(label or "API key").strip()[:100],
        prefix=prefix, secret_hash=hash_key(key),
        expires_at=_now() + timedelta(days=int(expires_in_days)),
        rotated_from_id=rotated_from.id if rotated_from else None, created_by=actor.id,
    )
    db.add(credential)
    db.flush()
    audit.record(
        db, entity_id=None, org_id=account.org_id, user=actor,
        action="studio.credential.rotated" if rotated_from else "studio.credential.issued",
        object_type="integration_credential", object_id=prefix,
        summary=(f"Rotated key {rotated_from.prefix} → {prefix}" if rotated_from else f"Issued key {prefix}")
                + f" for “{account.name}”, expiring {credential.expires_at:%d %b %Y}",
        detail={"service_account_id": str(account.id), "expires_at": credential.expires_at.isoformat()},
    )
    return credential, key


def rotate(
    db: Session,
    credential: IntegrationCredential,
    *,
    actor: User,
    grace_hours: int = DEFAULT_ROTATION_GRACE_HOURS,
    expires_in_days: int = DEFAULT_EXPIRY_DAYS,
) -> tuple[IntegrationCredential, str]:
    if credential.revoked_at is not None:
        raise ValueError("A revoked key cannot be rotated. Issue a new one.")
    if credential.rotated_to_id is not None:
        raise ValueError("This key has already been rotated.")
    if not 0 <= int(grace_hours) <= MAX_ROTATION_GRACE_HOURS:
        raise ValueError(f"The overlap can be at most {MAX_ROTATION_GRACE_HOURS} hours.")
    account = db.get(ServiceAccount, credential.service_account_id)
    new, key = issue(db, account, actor=actor, label=credential.label,
                     expires_in_days=expires_in_days, rotated_from=credential)
    end = _now() + timedelta(hours=int(grace_hours))
    credential.expires_at = min(_aware(credential.expires_at), end)
    credential.rotated_to_id = new.id
    return new, key


def revoke(db: Session, credential: IntegrationCredential, *, actor: User, reason: str) -> IntegrationCredential:
    account = db.get(ServiceAccount, credential.service_account_id)
    if account is None:
        raise ValueError("Service account not found.")
    # A shared key affects every named company, so management of the current
    # company alone is insufficient to revoke it.
    _check_companies(db, actor, account.org_id, list(account.entity_ids or []))
    if not (reason or "").strip():
        raise ValueError("Say why the key is being revoked.")
    if credential.revoked_at is None:
        credential.revoked_at = _now()
        credential.revoked_by = actor.id
        credential.revoke_reason = reason.strip()
        account = db.get(ServiceAccount, credential.service_account_id)
        audit.record(
            db, entity_id=None, org_id=credential.org_id, user=actor, action="studio.credential.revoked",
            object_type="integration_credential", object_id=credential.prefix,
            summary=f"Revoked key {credential.prefix} of “{account.name if account else '?'}”: {reason.strip()}",
        )
    return credential


def authenticate(db: Session, key: str | None) -> Principal:
    """Resolve a presented key, or raise ``CredentialError``."""
    if not key:
        raise CredentialError("unauthorized", "Send an API key as 'Authorization: Bearer <key>'.")
    match = KEY_PATTERN.match(key.strip())
    if match is None:
        raise CredentialError("unauthorized", "The API key is not valid.")
    prefix = f"pol_{match.group(1)}_{match.group(2)}"
    credential = db.query(IntegrationCredential).filter(IntegrationCredential.prefix == prefix).first()
    # Compared even when no row matched, so timing does not reveal which
    # prefixes exist.
    expected = credential.secret_hash if credential else hash_key("absent")
    if not hmac.compare_digest(expected, hash_key(key.strip())) or credential is None:
        raise CredentialError("unauthorized", "The API key is not valid.")
    # Only someone holding the full secret gets past this point, so telling
    # them *why* it no longer works confirms nothing to a stranger.
    if credential.revoked_at is not None:
        raise CredentialError("credential_revoked", "This API key has been revoked.")
    if _aware(credential.expires_at) <= _now():
        raise CredentialError("credential_expired", "This API key has expired. Rotate or issue a new one.")
    account = db.get(ServiceAccount, credential.service_account_id)
    if account is None or account.status != "active":
        raise CredentialError("credential_revoked", "This service account is disabled.")
    user = db.get(User, account.user_id)
    if user is None or user.role != "machine":
        raise CredentialError("unauthorized", "The API key is not valid.")
    now = _now()
    if credential.last_used_at is None or now - _aware(credential.last_used_at) > LAST_USED_RESOLUTION:
        credential.last_used_at = now
        db.commit()
    return Principal(credential=credential, account=account, user=user,
                     scopes=set(account.scopes or []), entity_ids={str(e) for e in account.entity_ids or []})


# ---------------------------------------------------------------------------
# Describing
# ---------------------------------------------------------------------------
def credential_state(credential: IntegrationCredential, at: datetime | None = None) -> str:
    at = at or _now()
    if credential.revoked_at is not None:
        return "revoked"
    if _aware(credential.expires_at) <= at:
        return "expired"
    if credential.rotated_to_id is not None:
        return "rotating"
    return "active"


def describe_credential(credential: IntegrationCredential) -> dict[str, Any]:
    return {
        "id": str(credential.id),
        "label": credential.label,
        "prefix": credential.prefix,
        "state": credential_state(credential),
        "expires_at": _aware(credential.expires_at).isoformat(),
        "last_used_at": _aware(credential.last_used_at).isoformat() if credential.last_used_at else None,
        "revoked_at": _aware(credential.revoked_at).isoformat() if credential.revoked_at else None,
        "revoke_reason": credential.revoke_reason,
        "rotated_from_id": str(credential.rotated_from_id) if credential.rotated_from_id else None,
        "rotated_to_id": str(credential.rotated_to_id) if credential.rotated_to_id else None,
        "created_at": _aware(credential.created_at).isoformat() if credential.created_at else None,
    }


def describe_account(db: Session, account: ServiceAccount, visible_entities: dict[str, str]) -> dict[str, Any]:
    creds = (
        db.query(IntegrationCredential)
        .filter(IntegrationCredential.service_account_id == account.id)
        .order_by(IntegrationCredential.created_at.desc())
        .all()
    )
    return {
        "id": str(account.id),
        "name": account.name,
        "description": account.description,
        "environment": account.environment,
        "status": account.status,
        "scopes": list(account.scopes or []),
        # Companies the viewer cannot see are counted, never named.
        "companies": [
            {"id": e, "name": visible_entities[e]} for e in account.entity_ids or [] if e in visible_entities
        ],
        "hidden_companies": sum(1 for e in account.entity_ids or [] if e not in visible_entities),
        "credentials": [describe_credential(c) for c in creds],
        "created_at": _aware(account.created_at).isoformat() if account.created_at else None,
    }
