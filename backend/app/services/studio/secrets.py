"""
Encrypted storage for connection and webhook secrets.

Secrets are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) under the key in
``STUDIO_SECRET_KEY``. Several keys may be given, comma separated: the first
encrypts, all decrypt, so a new key can be rotated in and old ciphertext
re-encrypted at leisure (``reencrypt``).

**No key, no secrets.** In production an unset key refuses to store anything —
a secret kept in clear because a variable was forgotten is exactly the failure
nobody notices until it matters. In development and tests a key is derived from
``JWT_SECRET`` so the feature works out of the box, and the boot log says so.

What leaves this module is ciphertext, or a mask (``••••1234``) for display.
Decrypted values are handed only to the outbound HTTP client and the signer.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import settings

logger = logging.getLogger("payroll.studio")


class SecretStoreUnavailable(RuntimeError):
    """No encryption key is configured, so no secret may be stored."""


_warned = False


def _keys() -> list[bytes]:
    global _warned
    raw = [k.strip() for k in (settings.studio_secret_key or "").split(",") if k.strip()]
    if raw:
        return [k.encode() for k in raw]
    if settings.is_production:
        raise SecretStoreUnavailable(
            "STUDIO_SECRET_KEY is not set on this server, so connection credentials cannot be stored. "
            "An administrator must set it (a Fernet key) before connections with credentials can be saved."
        )
    if not _warned:
        logger.warning("STUDIO_SECRET_KEY unset — deriving a development key from JWT_SECRET. "
                       "Never run production like this.")
        _warned = True
    derived = hashlib.sha256(("studio-secrets:" + settings.jwt_secret).encode()).digest()
    return [base64.urlsafe_b64encode(derived)]


def _fernet() -> MultiFernet:
    return MultiFernet([Fernet(k) for k in _keys()])


def available() -> tuple[bool, str]:
    try:
        _keys()
    except SecretStoreUnavailable as exc:
        return False, str(exc)
    configured = bool((settings.studio_secret_key or "").strip())
    return True, "configured" if configured else "development key derived from JWT_SECRET"


def seal(values: dict[str, Any]) -> bytes:
    """Encrypt a dict of secret values."""
    return _fernet().encrypt(json.dumps(values, separators=(",", ":")).encode())


def unseal(token: bytes | None) -> dict[str, Any]:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(bytes(token)).decode())
    except InvalidToken as exc:
        raise SecretStoreUnavailable(
            "A stored secret could not be decrypted with the configured key(s). If STUDIO_SECRET_KEY was "
            "changed, add the previous key after the new one, comma separated."
        ) from exc


def reencrypt(token: bytes | None) -> bytes | None:
    """Re-encrypt under the first key (after rotating a new key in)."""
    return _fernet().rotate(bytes(token)) if token else None


def mask(value: str | None) -> str | None:
    if not value:
        return None
    tail = value[-4:] if len(value) > 8 else ""
    return f"••••{tail}"


def masks(values: dict[str, Any]) -> dict[str, str | None]:
    return {k: mask(str(v)) if v else None for k, v in values.items()}
