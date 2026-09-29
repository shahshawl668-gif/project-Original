"""Authentication, company scoping, scopes and idempotency for the integration API."""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import Depends, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.integration.errors import ApiError
from app.models import Entity
from app.services.studio import credentials, idempotency, ratelimit
from app.services.studio.credentials import Principal


def request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None) or request.headers.get("X-Request-Id")
    if not rid:
        rid = uuid.uuid4().hex[:12]
    request.state.request_id = rid
    return rid


def get_principal(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Principal:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    try:
        principal = credentials.authenticate(db, token)
    except credentials.CredentialError as exc:
        raise ApiError(exc.code, exc.message, status=exc.status,
                       headers={"WWW-Authenticate": 'Bearer realm="peopleopslab-integration"'})
    decision = ratelimit.check(f"cred:{principal.credential.id}", settings.integration_rate_limit_per_minute)
    request.state.rate_limit = decision
    if not decision.allowed:
        raise ApiError("rate_limited", f"Limit of {decision.limit} requests per minute reached for this key.",
                       headers={"Retry-After": str(decision.reset_seconds)})
    request.state.principal = principal
    return principal


def require(*scopes: str) -> Callable[..., Principal]:
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        missing = [s for s in scopes if s not in principal.scopes]
        if missing:
            raise ApiError("forbidden_scope", f"This key needs the scope(s): {', '.join(missing)}.")
        return principal

    dependency.__name__ = "require_" + "_".join(s.replace(":", "_") for s in scopes)
    return dependency


def get_company(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    x_company_id: str | None = Header(default=None, alias="X-Company-Id"),
) -> Entity:
    """
    The company this request acts on — always one the key names.

    Unknown, another organisation's, or simply not on this key: the same 404,
    so a key cannot be used to learn which companies exist.
    """
    wanted = (x_company_id or "").strip()
    if not wanted:
        if len(principal.entity_ids) == 1:
            wanted = next(iter(principal.entity_ids))
        else:
            raise ApiError("company_required")
    try:
        entity = db.get(Entity, uuid.UUID(wanted))
    except ValueError:
        entity = None
    if (entity is None or str(entity.id) not in principal.entity_ids
            or entity.org_id != principal.account.org_id or not entity.is_active):
        raise ApiError("not_found", "Company not found.")
    return entity


def envelope(data: Any) -> dict[str, Any]:
    return {"success": True, "data": jsonable_encoder(data), "error": None}


async def idempotent(
    request: Request,
    db: Session,
    principal: Principal,
    company: Entity | None,
    work: Callable[[], tuple[int, Any]],
    *,
    required: bool = True,
) -> tuple[int, dict[str, Any], bool]:
    """
    Run ``work`` at most once per Idempotency-Key.

    Returns ``(status, envelope, replayed)``. ``work`` returns ``(status, data)``
    and runs in a worker thread. A failure inside ``work`` frees the key so a
    corrected retry can use it; a success is stored and replayed for 24 hours.
    """
    key = request.headers.get("Idempotency-Key")
    if not key:
        if required:
            raise ApiError("idempotency_key_required")
        status, data = await run_in_threadpool(work)
        return status, envelope(data), False
    raw = await request.body()
    fingerprint = idempotency.request_hash(request.method, request.url.path,
                                           str(company.id) if company else None, raw)
    try:
        reservation = idempotency.begin(db, principal=principal.id, key=key, method=request.method,
                                        path=request.url.path, fingerprint=fingerprint)
    except idempotency.IdempotencyConflict as exc:
        raise ApiError(exc.code, exc.message)
    if isinstance(reservation, dict):
        return reservation["status_code"], reservation["response"], True
    try:
        status, data = await run_in_threadpool(work)
    except BaseException:
        idempotency.abandon(db, reservation)
        raise
    payload = envelope(data)
    # Stored as JSON text round-tripped, so the replay is byte-for-byte what
    # the client would have received.
    idempotency.finish(db, reservation, status, json.loads(json.dumps(payload, default=str)))
    return status, payload, False


def page_params(page: int, page_size: int) -> tuple[int, int]:
    if page < 1:
        raise ApiError("invalid_request", "'page' starts at 1.")
    if not 1 <= page_size <= 500:
        raise ApiError("invalid_request", "'page_size' must be between 1 and 500.")
    return page, page_size


def paged(items: list[Any], page: int, page_size: int, total: int, **extra: Any) -> dict[str, Any]:
    pages = (total + page_size - 1) // page_size if page_size else 0
    return {"items": items, "page": page, "page_size": page_size, "total": total,
            "pages": pages, "has_more": page < pages, **extra}
