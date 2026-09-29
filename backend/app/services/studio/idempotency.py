"""
Idempotency keys for retryable writes.

A client that times out waiting for an import does not know whether it
landed. With a key it can send the same request again and get the first
answer back instead of a second import. The stored answer is keyed by caller
and key; the same key with a different request is refused rather than
silently answered with the wrong result.

Kept for 24 hours — long enough for any sane retry policy, short enough that
the table does not become a second copy of every payload.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import IdempotencyRecord

TTL = timedelta(hours=24)
MAX_KEY_LENGTH = 255


class IdempotencyConflict(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def request_hash(method: str, path: str, company: str | None, body: bytes) -> str:
    h = hashlib.sha256()
    for part in (method.upper(), path, company or ""):
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")
    h.update(body)
    return h.hexdigest()


def begin(
    db: Session, *, principal: str, key: str, method: str, path: str, fingerprint: str
) -> IdempotencyRecord | dict[str, Any]:
    """
    Reserve a key, or return the stored response for it.

    Returns the new reservation (the caller runs the request and calls
    ``finish``) or a dict ``{"status_code", "response"}`` to replay.
    """
    key = (key or "").strip()
    if not key or len(key) > MAX_KEY_LENGTH:
        raise IdempotencyConflict("idempotency_key_invalid",
                                  f"Idempotency-Key must be 1–{MAX_KEY_LENGTH} characters.")
    now = datetime.now(UTC)
    existing = (
        db.query(IdempotencyRecord)
        .filter(IdempotencyRecord.principal == principal, IdempotencyRecord.key == key)
        .first()
    )
    if existing is not None:
        expires = existing.expires_at if existing.expires_at.tzinfo else existing.expires_at.replace(tzinfo=UTC)
        if expires <= now:
            db.delete(existing)
            db.flush()
        elif existing.request_hash != fingerprint:
            raise IdempotencyConflict(
                "idempotency_key_reused",
                "This Idempotency-Key was already used for a different request. Use a new key.",
            )
        elif existing.status_code is None:
            raise IdempotencyConflict(
                "idempotency_in_progress",
                "A request with this Idempotency-Key is still being processed. Retry shortly.",
            )
        else:
            return {"status_code": existing.status_code, "response": existing.response}
    record = IdempotencyRecord(
        principal=principal, key=key, method=method.upper(), path=path[:255],
        request_hash=fingerprint, expires_at=now + TTL,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        # Two retries raced; the other one holds the key.
        db.rollback()
        raise IdempotencyConflict(
            "idempotency_in_progress",
            "A request with this Idempotency-Key is still being processed. Retry shortly.",
        )
    return record


def finish(db: Session, record: IdempotencyRecord, status_code: int, response: dict[str, Any]) -> None:
    record.status_code = status_code
    record.response = response
    db.commit()


def abandon(db: Session, record: IdempotencyRecord) -> None:
    """A request that failed before doing anything frees its key for a retry."""
    db.rollback()
    row = db.get(IdempotencyRecord, record.id)
    if row is not None:
        db.delete(row)
        db.commit()


def purge_expired(db: Session) -> int:
    n = db.query(IdempotencyRecord).filter(IdempotencyRecord.expires_at < datetime.now(UTC)).delete()
    db.commit()
    return n
