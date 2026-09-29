"""
PeopleOps Studio — the screens' API.

For people signed in to the product. Managing machine identities and keys is
an owner's or manager's job; reading run history needs an analyst. Everything
here is scoped to the company in ``X-Entity-Id``: a run, an account or a key
of another company answers 404.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_admin, require_entity_write
from app.envelope import ok
from app.models import Entity, IntegrationCredential, ServiceAccount, StudioRun, StudioRunRejection, User
from app.services import tenancy
from app.services.studio import credentials, imports, runs

router = APIRouter()


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------
def require_studio_reader(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
) -> Entity:
    """Studio is a technical workspace: analyst and above."""
    if not tenancy.role_at_least(db, user, "analyst", entity):
        raise HTTPException(status_code=403, detail="PeopleOps Studio needs an analyst role or above")
    return entity


def _account(db: Session, entity: Entity, account_id: str) -> ServiceAccount:
    try:
        account = db.get(ServiceAccount, uuid.UUID(account_id))
    except ValueError:
        account = None
    if account is None or account.org_id != entity.org_id or str(entity.id) not in (account.entity_ids or []):
        raise HTTPException(status_code=404, detail="Service account not found")
    return account


def _credential(db: Session, entity: Entity, credential_id: str) -> IntegrationCredential:
    try:
        cred = db.get(IntegrationCredential, uuid.UUID(credential_id))
    except ValueError:
        cred = None
    if cred is None:
        raise HTTPException(status_code=404, detail="Key not found")
    _account(db, entity, str(cred.service_account_id))
    return cred


def _run(db: Session, entity: Entity, run_id: str) -> StudioRun:
    try:
        run = db.get(StudioRun, uuid.UUID(run_id))
    except ValueError:
        run = None
    if run is None or run.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _visible_entities(db: Session, user: User, org_id: uuid.UUID) -> dict[str, str]:
    return {str(e.id): e.name for e in tenancy.accessible_entities(db, user) if e.org_id == org_id}


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
#: Each Studio section and whether this release provides it. A section that is
#: not built says so on its card; it is never shown as if it worked.
SECTIONS = [
    {"key": "api", "label": "API Centre", "href": "/studio/api", "available": True,
     "summary": "Service accounts, keys, scopes, and the documented integration API."},
    {"key": "runs", "label": "Run history", "href": "/studio/runs", "available": True,
     "summary": "Every import and API-started validation, with counts, rejections and lineage."},
    {"key": "connections", "label": "Connections", "href": "/studio/connections", "available": True,
     "summary": "REST and file connections to HRMS, attendance and finance systems: credentials, tests, "
                "streams, schedules, checkpoints and health."},
    {"key": "mapping", "label": "Data mapping", "href": "/studio/mapping", "available": True,
     "summary": "Versioned mapping from external fields to product fields, previewed on sample data before "
                "it is published. Import a file with it."},
    {"key": "workflows", "label": "Workflows", "href": None, "available": False,
     "summary": "Trigger → conditions → actions automation. Not in this release."},
    {"key": "webhooks", "label": "Webhooks", "href": "/studio/webhooks", "available": True,
     "summary": "Signed events to your systems, delivered at least once with retries and a failed queue; "
                "signed inbound endpoints that push records in."},
    {"key": "developer", "label": "Developer workspace", "href": None, "available": False,
     "summary": "Formula and expression testing; scripted extensions. Not in this release."},
    {"key": "releases", "label": "Versions & releases", "href": None, "available": False,
     "summary": "Environments, promotion and rollback. Not in this release."},
]


@router.get("/overview")
def overview(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_studio_reader),
):
    now = datetime.now(UTC)
    accounts = [a for a in db.query(ServiceAccount).filter(ServiceAccount.org_id == entity.org_id).all()
                if str(entity.id) in (a.entity_ids or [])]
    account_ids = [a.id for a in accounts]
    creds = (db.query(IntegrationCredential)
             .filter(IntegrationCredential.service_account_id.in_(account_ids or [uuid.uuid4()])).all())
    states = [credentials.credential_state(c, now) for c in creds]
    expiring = [c for c, s in zip(creds, states, strict=True)
                if s in ("active", "rotating") and credentials._aware(c.expires_at) - now < timedelta(days=14)]
    since = now - timedelta(days=7)
    by_status = dict(
        db.query(StudioRun.status, func.count())
        .filter(StudioRun.entity_id == entity.id, StudioRun.queued_at >= since)
        .group_by(StudioRun.status).all()
    )
    last = (db.query(StudioRun).filter(StudioRun.entity_id == entity.id)
            .order_by(StudioRun.queued_at.desc()).first())
    attention = (db.query(StudioRun)
                 .filter(StudioRun.entity_id == entity.id,
                         StudioRun.status.in_(("failed", "partially_completed")),
                         StudioRun.queued_at >= since)
                 .order_by(StudioRun.queued_at.desc()).limit(5).all())
    return ok({
        "company": {"id": str(entity.id), "name": entity.name},
        "service_accounts": {"total": len(accounts), "active": sum(a.status == "active" for a in accounts)},
        "keys": {"active": states.count("active") + states.count("rotating"),
                 "expiring_within_14_days": [{"prefix": c.prefix, "expires_at": credentials._aware(c.expires_at).isoformat()} for c in expiring]},
        "runs_last_7_days": by_status,
        "last_run": runs.describe(db, last) if last else None,
        "needs_attention": [runs.describe(db, r) for r in attention],
        "worker_enabled": bool(settings.validation_worker_enabled),
        "integration_api": {"base_path": "/api/integration/v1", "openapi": "/api/integration/v1/openapi.json",
                            "docs": "/api/integration/v1/docs",
                            "limits": {"requests_per_minute": settings.integration_rate_limit_per_minute,
                                       "max_request_mb": settings.integration_max_request_mb,
                                       "max_records": settings.integration_max_records}},
        "sections": SECTIONS,
    })


@router.get("/scopes")
def list_scopes(entity: Entity = Depends(require_studio_reader)):
    return ok([{"scope": k, "grants": v, "writes": k in credentials.WRITE_SCOPES}
               for k, v in credentials.SCOPES.items()])


# ---------------------------------------------------------------------------
# Service accounts and keys
# ---------------------------------------------------------------------------
class AccountCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    environment: str = Field(default="production", pattern="^(development|test|production)$")
    entity_ids: list[str] = Field(min_length=1, max_length=200)
    scopes: list[str] = Field(min_length=1)


class AccountUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=1000)
    entity_ids: list[str] | None = None
    scopes: list[str] | None = None
    status: str | None = Field(default=None, pattern="^(active|disabled)$")


class KeyCreate(BaseModel):
    label: str = Field(default="API key", min_length=1, max_length=100)
    expires_in_days: int = Field(default=credentials.DEFAULT_EXPIRY_DAYS, ge=1, le=credentials.MAX_EXPIRY_DAYS)


class KeyRotate(BaseModel):
    grace_hours: int = Field(default=credentials.DEFAULT_ROTATION_GRACE_HOURS, ge=0,
                             le=credentials.MAX_ROTATION_GRACE_HOURS)
    expires_in_days: int = Field(default=credentials.DEFAULT_EXPIRY_DAYS, ge=1, le=credentials.MAX_EXPIRY_DAYS)


class KeyRevoke(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


def _issued(credential: IntegrationCredential, key: str) -> dict[str, Any]:
    out = credentials.describe_credential(credential)
    out["key"] = key
    out["shown_once"] = True
    return out


@router.get("/service-accounts")
def list_accounts(
    db: Session = Depends(get_db),
    user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    visible = _visible_entities(db, user, entity.org_id)
    rows = (db.query(ServiceAccount).filter(ServiceAccount.org_id == entity.org_id)
            .order_by(ServiceAccount.name).all())
    return ok([credentials.describe_account(db, a, visible) for a in rows if str(entity.id) in (a.entity_ids or [])])


@router.post("/service-accounts")
def create_account(
    body: AccountCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    try:
        account = credentials.create_account(
            db, actor=user, org_id=entity.org_id, name=body.name, description=body.description,
            environment=body.environment, entity_ids=body.entity_ids, scopes=body.scopes,
        )
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return ok(credentials.describe_account(db, account, _visible_entities(db, user, entity.org_id)))


@router.patch("/service-accounts/{account_id}")
def update_account(
    account_id: str,
    body: AccountUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    account = _account(db, entity, account_id)
    try:
        credentials.update_account(db, account, actor=user, description=body.description,
                                   entity_ids=body.entity_ids, scopes=body.scopes, status=body.status)
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return ok(credentials.describe_account(db, account, _visible_entities(db, user, entity.org_id)))


@router.post("/service-accounts/{account_id}/keys")
def issue_key(
    account_id: str,
    body: KeyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    account = _account(db, entity, account_id)
    try:
        cred, key = credentials.issue(db, account, actor=user, label=body.label, expires_in_days=body.expires_in_days)
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return ok(_issued(cred, key))


@router.post("/keys/{credential_id}/rotate")
def rotate_key(
    credential_id: str,
    body: KeyRotate,
    db: Session = Depends(get_db),
    user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    cred = _credential(db, entity, credential_id)
    try:
        new, key = credentials.rotate(db, cred, actor=user, grace_hours=body.grace_hours,
                                      expires_in_days=body.expires_in_days)
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    db.commit()
    return ok({"new": _issued(new, key), "previous": credentials.describe_credential(cred)})


@router.post("/keys/{credential_id}/revoke")
def revoke_key(
    credential_id: str,
    body: KeyRevoke,
    db: Session = Depends(get_db),
    user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    cred = _credential(db, entity, credential_id)
    try:
        credentials.revoke(db, cred, actor=user, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return ok(credentials.describe_credential(cred))


# ---------------------------------------------------------------------------
# Run history
# ---------------------------------------------------------------------------
@router.get("/runs")
def list_runs(
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    object_type: str | None = Query(default=None),
    actor_type: str | None = Query(default=None, pattern="^(user|machine)$"),
    q: str | None = Query(default=None, max_length=100),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    entity: Entity = Depends(require_studio_reader),
):
    rows, total = runs.search(db, entity.id, kind=kind, status=status, object_type=object_type,
                              actor_type=actor_type, q=q, date_from=date_from, date_to=date_to,
                              page=page, page_size=page_size)
    return ok({"items": [runs.describe(db, r) for r in rows], "page": page, "page_size": page_size,
               "total": total, "pages": (total + page_size - 1) // page_size})


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    entity: Entity = Depends(require_studio_reader),
):
    return ok(runs.describe(db, _run(db, entity, run_id), detail=True))


@router.get("/runs/{run_id}/rejections")
def get_rejections(
    run_id: str,
    disposition: str | None = Query(default=None, pattern="^(rejected|skipped)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    entity: Entity = Depends(require_studio_reader),
):
    run = _run(db, entity, run_id)
    rows, total = runs.rejections(db, run, page=page, page_size=page_size, disposition=disposition)
    return ok({"items": [runs.describe_rejection(r) for r in rows], "page": page, "page_size": page_size,
               "total": total, "pages": (total + page_size - 1) // page_size})


@router.get("/runs/{run_id}/rejections/{rejection_id}/record")
def get_rejected_record(
    run_id: str,
    rejection_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    """
    The rejected record as it was received.

    Owners and managers only: it can hold pay and identity data, which the
    rest of run history deliberately does not show. Reading it is audited.
    """
    run = _run(db, entity, run_id)
    try:
        row = db.get(StudioRunRejection, uuid.UUID(rejection_id))
    except ValueError:
        row = None
    if row is None or row.run_id != run.id:
        raise HTTPException(status_code=404, detail="Rejected record not found")
    if row.payload_gz is None:
        raise HTTPException(status_code=410, detail="The retained copy of this record has expired")
    from app.services import audit

    audit.record(db, entity_id=entity.id, user=user, action="studio.rejection.viewed",
                 object_type="studio_run", object_id=str(run.id),
                 summary=f"Viewed rejected record at row {row.row_number} of run {str(run.id)[:8]}")
    db.commit()
    return ok(runs.describe_rejection(row, with_payload=True))


@router.post("/runs/{run_id}/retry-rejected")
def retry_rejected(
    run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    run = _run(db, entity, run_id)
    try:
        new = imports.retry_rejected(db, run, actor=user, actor_label=user.email, actor_type="user")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    from app.services import audit

    audit.record(db, entity_id=entity.id, user=user, action="studio.import.retried",
                 object_type="studio_run", object_id=str(new.id),
                 summary=f"Retried the rejected records of run {str(run.id)[:8]}")
    db.commit()
    return ok(runs.describe(db, new))


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    run = _run(db, entity, run_id)
    if run.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail="Only a queued or running run can be cancelled")
    runs.request_cancel(db, run)
    db.commit()
    return ok(runs.describe(db, run))


# ===========================================================================
# Phase 2 — destinations, connections, streams, mappings, file imports
# ===========================================================================
from fastapi import File, Form, UploadFile  # noqa: E402

from app.models import StudioAllowedHost, StudioStream  # noqa: E402
from app.services.studio import connections as conns  # noqa: E402
from app.services.studio import egress, profiles, sync  # noqa: E402
from app.services.studio import mapping as mapping_engine  # noqa: E402
from app.services.studio import secrets as vault  # noqa: E402


def _http(exc: Exception) -> HTTPException:
    status = getattr(exc, "status", 400)
    if isinstance(exc, egress.EgressRefused):
        return HTTPException(status_code=400, detail=exc.message)
    if isinstance(exc, vault.SecretStoreUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=status, detail=str(exc))


def _stream(db: Session, entity: Entity, stream_id: str) -> StudioStream:
    try:
        row = db.get(StudioStream, uuid.UUID(stream_id))
    except ValueError:
        row = None
    if row is None or row.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Stream not found")
    return row


# ---- Allowed destinations --------------------------------------------------
class DestinationCreate(BaseModel):
    host: str = Field(min_length=3, max_length=255)
    note: str | None = Field(default=None, max_length=500)


@router.get("/destinations")
def list_destinations(db: Session = Depends(get_db), entity: Entity = Depends(require_studio_reader)):
    rows = (db.query(StudioAllowedHost).filter(StudioAllowedHost.org_id == entity.org_id)
            .order_by(StudioAllowedHost.host).all())
    ok_store, store_note = vault.available()
    return ok({"hosts": [{"id": str(r.id), "host": r.host, "note": r.note,
                          "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows],
               "private_destinations_allowed": bool(settings.studio_allow_private_destinations),
               "secret_store": {"available": ok_store, "note": store_note}})


@router.post("/destinations")
def add_destination(body: DestinationCreate, db: Session = Depends(get_db),
                    user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    try:
        row = conns.add_allowed_host(db, entity.org_id, user, body.host, body.note)
    except ValueError as exc:
        raise _http(exc)
    db.commit()
    return ok({"id": str(row.id), "host": row.host, "note": row.note})


@router.delete("/destinations/{host_id}")
def remove_destination(host_id: str, db: Session = Depends(get_db),
                       user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    try:
        conns.remove_allowed_host(db, entity.org_id, user, host_id)
    except ValueError as exc:
        raise _http(exc)
    db.commit()
    return ok({"removed": True})


# ---- Connections -------------------------------------------------------------
class ConnectionBody(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    system_kind: str | None = None
    provider: str | None = None
    environment: str | None = None
    base_url: str | None = Field(default=None, max_length=1000)
    auth_method: str | None = None
    auth_config: dict[str, Any] | None = None
    secrets: dict[str, str] | None = None
    status: str | None = None


@router.get("/connections")
def list_connections(db: Session = Depends(get_db), entity: Entity = Depends(require_studio_reader)):
    from app.models import StudioConnection

    rows = (db.query(StudioConnection).filter(StudioConnection.entity_id == entity.id)
            .order_by(StudioConnection.name).all())
    try:
        return ok([conns.describe(db, c) for c in rows])
    except vault.SecretStoreUnavailable as exc:
        raise _http(exc)


@router.get("/connections/meta")
def connection_meta(entity: Entity = Depends(require_studio_reader)):
    return ok({"auth_methods": conns.AUTH_METHODS, "system_kinds": conns.SYSTEM_KINDS, "providers": conns.PROVIDERS})


@router.post("/connections")
def create_connection(body: ConnectionBody, db: Session = Depends(get_db),
                      user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    try:
        conn = conns.create(db, entity, user, body.model_dump(exclude_none=True))
    except (ValueError, egress.EgressRefused, vault.SecretStoreUnavailable) as exc:
        db.rollback()
        raise _http(exc)
    db.commit()
    return ok(conns.describe(db, conn))


@router.get("/connections/{connection_id}")
def get_connection(connection_id: str, db: Session = Depends(get_db), entity: Entity = Depends(require_studio_reader)):
    try:
        conn = conns.get(db, entity, connection_id)
        out = conns.describe(db, conn)
    except (ValueError, vault.SecretStoreUnavailable) as exc:
        raise _http(exc)
    recent, _ = runs.search(db, entity.id, kind="sync", page=1, page_size=100)
    out["recent_runs"] = [runs.describe(db, r) for r in recent if r.connection_id == conn.id][:20]
    return ok(out)


@router.patch("/connections/{connection_id}")
def update_connection(connection_id: str, body: ConnectionBody, db: Session = Depends(get_db),
                      user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    try:
        conn = conns.get(db, entity, connection_id)
        conns.update(db, entity, conn, user, body.model_dump(exclude_none=True))
    except (ValueError, egress.EgressRefused, vault.SecretStoreUnavailable) as exc:
        db.rollback()
        raise _http(exc)
    db.commit()
    return ok(conns.describe(db, conn))


@router.post("/connections/{connection_id}/test")
def test_connection(connection_id: str, stream_id: str | None = Query(default=None), db: Session = Depends(get_db),
                    user: User = Depends(get_current_user), entity: Entity = Depends(require_entity_write)):
    try:
        conn = conns.get(db, entity, connection_id)
    except ValueError as exc:
        raise _http(exc)
    stream = _stream(db, entity, stream_id) if stream_id else None
    result = conns.test(db, conn, stream)
    from app.services import audit

    audit.record(db, entity_id=entity.id, user=user, action="studio.connection.tested",
                 object_type="studio_connection", object_id=str(conn.id),
                 summary=f"Tested “{conn.name}”: {'passed' if result['ok'] else 'failed — ' + result['message']}")
    db.commit()
    return ok(result)


@router.post("/connections/{connection_id}/sample")
def sample_records(connection_id: str, stream_id: str = Query(...), db: Session = Depends(get_db),
                   user: User = Depends(get_current_user), entity: Entity = Depends(require_entity_write)):
    """Up to 20 records from a stream, to build a mapping against. Nothing is stored."""
    conn = conns.get(db, entity, connection_id)
    stream = _stream(db, entity, stream_id)
    try:
        records, _ = conns.fetch(db, conn, stream, sample=20)
    except (egress.EgressRefused, egress.EgressFailed) as exc:
        db.commit()
        raise HTTPException(status_code=502 if isinstance(exc, egress.EgressFailed) else 400, detail=exc.message)
    db.commit()
    return ok({"records": records, "fields": sorted({k for r in records if isinstance(r, dict) for k in r})})


class OAuthStart(BaseModel):
    redirect_uri: str = Field(min_length=10, max_length=1000)


class OAuthFinish(BaseModel):
    state: str = Field(min_length=10, max_length=500)
    code: str = Field(min_length=1, max_length=4000)


@router.post("/connections/{connection_id}/oauth/start")
def oauth_start(connection_id: str, body: OAuthStart, db: Session = Depends(get_db),
                user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    try:
        conn = conns.get(db, entity, connection_id)
        url = conns.oauth_start(db, conn, user, body.redirect_uri)
    except (ValueError, vault.SecretStoreUnavailable) as exc:
        raise _http(exc)
    db.commit()
    return ok({"authorize_url": url})


@router.post("/oauth/callback")
def oauth_callback(body: OAuthFinish, db: Session = Depends(get_db),
                   user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    try:
        conn = conns.oauth_finish(db, entity, user, body.state, body.code)
    except (ValueError, vault.SecretStoreUnavailable) as exc:
        db.commit()
        raise _http(exc)
    except (egress.EgressRefused, egress.EgressFailed) as exc:
        db.commit()
        raise HTTPException(status_code=502, detail=exc.message)
    db.commit()
    return ok(conns.describe(db, conn))


# ---- Streams ---------------------------------------------------------------
@router.post("/connections/{connection_id}/streams")
def create_stream(connection_id: str, body: dict[str, Any], db: Session = Depends(get_db),
                  user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    try:
        conn = conns.get(db, entity, connection_id)
        stream = sync.save_stream(db, entity, conn, user, body)
    except ValueError as exc:
        db.rollback()
        raise _http(exc)
    db.commit()
    return ok(conns.describe_stream(stream))


@router.patch("/streams/{stream_id}")
def update_stream(stream_id: str, body: dict[str, Any], db: Session = Depends(get_db),
                  user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    from app.models import StudioConnection

    stream = _stream(db, entity, stream_id)
    try:
        merged = {**conns.describe_stream(stream), **body}
        sync.save_stream(db, entity, db.get(StudioConnection, stream.connection_id), user, merged, stream)
    except ValueError as exc:
        db.rollback()
        raise _http(exc)
    db.commit()
    return ok(conns.describe_stream(stream))


@router.post("/streams/{stream_id}/sync")
def sync_now(stream_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user),
             entity: Entity = Depends(require_entity_write)):
    stream = _stream(db, entity, stream_id)
    try:
        run = sync.start(db, entity, stream, actor=user, actor_label=user.email, trigger="manual")
    except ValueError as exc:
        raise _http(exc)
    db.commit()
    return ok(runs.describe(db, run))


@router.post("/streams/{stream_id}/reset-checkpoint")
def reset_checkpoint(stream_id: str, db: Session = Depends(get_db), user: User = Depends(require_entity_admin),
                     entity: Entity = Depends(get_current_entity)):
    stream = _stream(db, entity, stream_id)
    sync.reset_checkpoint(db, entity, stream, user)
    db.commit()
    return ok(conns.describe_stream(stream))


# ---- Mappings ----------------------------------------------------------------
class MappingBody(BaseModel):
    key: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=255)
    object_type: str | None = None
    spec: dict[str, Any] | None = None
    change_reason: str | None = Field(default=None, max_length=2000)
    effective_from: date | None = None


class PreviewBody(BaseModel):
    spec: dict[str, Any] | None = None
    object_type: str | None = None
    records: list[Any] = Field(default_factory=list, max_length=2000)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


@router.get("/mappings")
def list_mappings(db: Session = Depends(get_db), entity: Entity = Depends(require_studio_reader)):
    from app.models import StudioMapping

    rows = (db.query(StudioMapping).filter(StudioMapping.entity_id == entity.id)
            .order_by(StudioMapping.key, StudioMapping.version.desc()).all())
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r.key, []).append(profiles.describe(r))
    return ok([{"key": k, "name": v[0]["name"], "object_type": v[0]["object_type"], "versions": v,
                "in_force": next((x for x in v if x["status"] == "published"), None)} for k, v in grouped.items()])


@router.get("/mappings/targets")
def mapping_targets(object_type: str, db: Session = Depends(get_db), entity: Entity = Depends(require_studio_reader)):
    try:
        return ok({"targets": mapping_engine.targets_for(object_type, profiles.components(db, entity.id)),
                   "types": mapping_engine.TYPES, "operators": mapping_engine.OPS,
                   "attendance_categories": mapping_engine.ATTENDANCE_CATEGORIES})
    except ValueError as exc:
        raise _http(exc)


@router.post("/mappings")
def create_mapping(body: MappingBody, db: Session = Depends(get_db), user: User = Depends(get_current_user),
                   entity: Entity = Depends(require_entity_write)):
    try:
        row = profiles.create(db, entity, user, key=body.key or "", name=body.name or body.key or "",
                              object_type=body.object_type or "", spec=body.spec or {},
                              change_reason=body.change_reason, effective_from=body.effective_from)
    except ValueError as exc:
        db.rollback()
        raise _http(exc)
    db.commit()
    return ok(profiles.describe(row))


@router.get("/mappings/{mapping_id}")
def get_mapping(mapping_id: str, db: Session = Depends(get_db), entity: Entity = Depends(require_studio_reader)):
    try:
        return ok(profiles.describe(profiles.get(db, entity, mapping_id)))
    except ValueError as exc:
        raise _http(exc)


@router.patch("/mappings/{mapping_id}")
def update_mapping(mapping_id: str, body: MappingBody, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user), entity: Entity = Depends(require_entity_write)):
    try:
        row = profiles.get(db, entity, mapping_id)
        profiles.update_draft(db, entity, row, user, spec=body.spec, name=body.name,
                              change_reason=body.change_reason, effective_from=body.effective_from)
    except ValueError as exc:
        db.rollback()
        raise _http(exc)
    db.commit()
    return ok(profiles.describe(row))


@router.post("/mappings/{mapping_id}/new-version")
def new_mapping_version(mapping_id: str, body: MappingBody, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user), entity: Entity = Depends(require_entity_write)):
    try:
        row = profiles.new_version_from(db, entity, profiles.get(db, entity, mapping_id), user, body.change_reason)
    except ValueError as exc:
        db.rollback()
        raise _http(exc)
    db.commit()
    return ok(profiles.describe(row))


@router.post("/mappings/{mapping_id}/publish")
def publish_mapping(mapping_id: str, db: Session = Depends(get_db), user: User = Depends(require_entity_admin),
                    entity: Entity = Depends(get_current_entity)):
    try:
        row = profiles.publish(db, entity, profiles.get(db, entity, mapping_id), user)
    except ValueError as exc:
        db.rollback()
        raise _http(exc)
    db.commit()
    return ok(profiles.describe(row))


@router.post("/mappings/{mapping_id}/retire")
def retire_mapping(mapping_id: str, body: ReasonBody, db: Session = Depends(get_db),
                   user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    try:
        row = profiles.retire(db, entity, profiles.get(db, entity, mapping_id), user, body.reason)
    except ValueError as exc:
        db.rollback()
        raise _http(exc)
    db.commit()
    return ok(profiles.describe(row))


@router.get("/mappings/{mapping_id}/compare")
def compare_mappings(mapping_id: str, other: str = Query(...), db: Session = Depends(get_db),
                     entity: Entity = Depends(require_studio_reader)):
    try:
        a, b = profiles.get(db, entity, other), profiles.get(db, entity, mapping_id)
    except ValueError as exc:
        raise _http(exc)
    return ok({"from": profiles.describe(a), "to": profiles.describe(b),
               "changes": mapping_engine.compare(a.spec, b.spec)})


@router.post("/mappings/preview")
def preview_spec(body: PreviewBody, db: Session = Depends(get_db), entity: Entity = Depends(require_studio_reader)):
    """Preview an unsaved specification against sample records."""
    try:
        spec = mapping_engine.check_spec(body.spec or {}, body.object_type or "", profiles.components(db, entity.id))
    except ValueError as exc:
        raise _http(exc)
    return ok(profiles.preview(spec, body.records))


@router.post("/mappings/{mapping_id}/preview")
async def preview_mapping(mapping_id: str, file: UploadFile | None = File(default=None),
                          records: str | None = Form(default=None), db: Session = Depends(get_db),
                          entity: Entity = Depends(require_studio_reader)):
    """Preview a saved version against a sample file or pasted JSON records."""
    try:
        row = profiles.get(db, entity, mapping_id)
        if file is not None:
            sample = imports.records_from_file(await file.read(), file.filename or "sample.csv", max_rows=2000)
        else:
            import json as _json

            sample = _json.loads(records or "[]")
            if not isinstance(sample, list):
                raise ValueError("Records must be a JSON list.")
    except ValueError as exc:
        raise _http(exc)
    return ok(profiles.preview(row.spec, sample))


# ---- File import with a mapping ------------------------------------------------
@router.post("/imports")
async def import_file(
    file: UploadFile = File(...),
    meta: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """
    Import a file through a published mapping — the administrator's path to
    everything the API does: the same checks, counts, rejections and lineage.
    """
    import json as _json

    try:
        options_in = _json.loads(meta)
        mapping = profiles.get(db, entity, options_in.get("mapping_id", ""))
        if mapping.status != "published":
            raise profiles.ProfileError("Publish the mapping before importing with it — or preview the draft.", 409)
        content = await file.read()
        records = imports.records_from_file(content, file.filename or "upload.csv")
        body = {**{k: v for k, v in options_in.items() if k != "mapping_id"}, "records": records}
        options = imports.check_submission(mapping.object_type, body)
    except (ValueError, _json.JSONDecodeError) as exc:
        raise _http(exc)
    connection_id = None
    if options_in.get("connection_id"):
        connection_id = conns.get(db, entity, options_in["connection_id"]).id
    run = runs.create(
        db, org_id=entity.org_id, entity_id=entity.id, kind="import", object_type=mapping.object_type,
        actor_type="user", actor_user_id=user.id, actor_label=user.email, trigger="ui",
        source_system=options_in.get("source_system") or "File upload", source_object=file.filename,
        batch_id=options_in.get("batch_id"),
        period_month=date.fromisoformat(options["period_month"]) if options.get("period_month") else None,
        effective_from=date.fromisoformat(options["effective_from"]) if options.get("effective_from") else None,
        options=options, payload=records, connection_id=connection_id,
        versions={"mapping": f"{mapping.key} v{mapping.version}", "mapping_id": str(mapping.id)},
    )
    from app.services import audit

    audit.record(db, entity_id=entity.id, user=user, action="studio.import.submitted", object_type="studio_run",
                 object_id=str(run.id), summary=f"Imported {file.filename} ({len(records):,} rows) with mapping "
                 f"{mapping.key} v{mapping.version}")
    db.commit()
    return ok(runs.describe(db, run))


# ===========================================================================
# Phase 2b — webhooks
# ===========================================================================
from app.models import (  # noqa: E402
    StudioDelivery,
    StudioEvent,
    StudioInboundEndpoint,
    StudioInboundReceipt,
    StudioWebhook,
)
from app.services.studio import events as studio_events  # noqa: E402
from app.services.studio import webhooks as hooks  # noqa: E402


class WebhookBody(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    url: str | None = Field(default=None, max_length=1000)
    events: list[str] | None = None
    environment: str | None = Field(default=None, pattern="^(development|test|production)$")
    status: str | None = Field(default=None, pattern="^(active|disabled)$")


class RotateBody(BaseModel):
    overlap_hours: int = Field(default=24, ge=0, le=hooks.MAX_ROTATION_OVERLAP_HOURS)


class InboundBody(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    object_type: str
    mapping_key: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    environment: str = Field(default="production", pattern="^(development|test|production)$")


def _webhook(db: Session, entity: Entity, webhook_id: str) -> StudioWebhook:
    try:
        row = db.get(StudioWebhook, uuid.UUID(webhook_id))
    except ValueError:
        row = None
    if row is None or row.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return row


def _inbound(db: Session, entity: Entity, endpoint_id: str) -> StudioInboundEndpoint:
    try:
        row = db.get(StudioInboundEndpoint, uuid.UUID(endpoint_id))
    except ValueError:
        row = None
    if row is None or row.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Inbound endpoint not found")
    return row


def _hook_stats(db: Session, hook_id: uuid.UUID) -> dict[str, int]:
    return dict(db.query(StudioDelivery.status, func.count()).filter(StudioDelivery.webhook_id == hook_id)
                .group_by(StudioDelivery.status).all())


@router.get("/webhooks/events")
def webhook_catalogue(entity: Entity = Depends(require_studio_reader)):
    return ok({"events": [{"type": k, "description": v} for k, v in studio_events.CATALOGUE.items() if k != "webhook.test"],
               "payload_version": studio_events.PAYLOAD_VERSION,
               "delivery": "at least once — de-duplicate on the event id",
               "retry_schedule_seconds": hooks.BACKOFF})


@router.get("/webhooks")
def list_webhooks(db: Session = Depends(get_db), entity: Entity = Depends(require_studio_reader)):
    rows = db.query(StudioWebhook).filter(StudioWebhook.entity_id == entity.id).order_by(StudioWebhook.name).all()
    return ok([hooks.describe(h, _hook_stats(db, h.id)) for h in rows])


@router.post("/webhooks")
def create_webhook(body: WebhookBody, db: Session = Depends(get_db), user: User = Depends(require_entity_admin),
                   entity: Entity = Depends(get_current_entity)):
    try:
        hook, secret = hooks.create(db, entity, user, name=body.name or "Webhook", url=body.url or "",
                                    event_names=body.events or [], environment=body.environment or "production")
    except (ValueError, egress.EgressRefused, vault.SecretStoreUnavailable) as exc:
        db.rollback()
        raise _http(exc)
    db.commit()
    return ok({**hooks.describe(hook), "secret": secret, "shown_once": True})


@router.patch("/webhooks/{webhook_id}")
def update_webhook(webhook_id: str, body: WebhookBody, db: Session = Depends(get_db),
                   user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    hook = _webhook(db, entity, webhook_id)
    try:
        hooks.update(db, entity, hook, user, body.model_dump(exclude_none=True))
    except (ValueError, egress.EgressRefused) as exc:
        db.rollback()
        raise _http(exc)
    db.commit()
    return ok(hooks.describe(hook, _hook_stats(db, hook.id)))


@router.post("/webhooks/{webhook_id}/rotate-secret")
def rotate_webhook_secret(webhook_id: str, body: RotateBody, db: Session = Depends(get_db),
                          user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    hook = _webhook(db, entity, webhook_id)
    try:
        secret = hooks.rotate_secret(db, entity, hook, user, body.overlap_hours)
    except (ValueError, vault.SecretStoreUnavailable) as exc:
        raise _http(exc)
    db.commit()
    return ok({"secret": secret, "shown_once": True, "overlap_hours": body.overlap_hours})


@router.post("/webhooks/{webhook_id}/test")
def test_webhook(webhook_id: str, db: Session = Depends(get_db), user: User = Depends(require_entity_admin),
                 entity: Entity = Depends(get_current_entity)):
    hook = _webhook(db, entity, webhook_id)
    event = hooks.send_test(db, entity, hook, user)
    db.commit()
    return ok({"event_id": str(event.id), "note": "Queued; the worker delivers it within seconds."})


@router.get("/webhooks/deliveries")
def list_deliveries(webhook_id: str | None = Query(default=None), status: str | None = Query(default=None),
                    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200),
                    db: Session = Depends(get_db), entity: Entity = Depends(require_studio_reader)):
    q = db.query(StudioDelivery).filter(StudioDelivery.entity_id == entity.id)
    if webhook_id:
        q = q.filter(StudioDelivery.webhook_id == _webhook(db, entity, webhook_id).id)
    if status:
        q = q.filter(StudioDelivery.status == status)
    total = q.count()
    rows = q.order_by(StudioDelivery.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    events_by_id = {e.id: e for e in db.query(StudioEvent).filter(StudioEvent.id.in_([r.event_id for r in rows] or [uuid.uuid4()]))}
    return ok({"items": [hooks.describe_delivery(r, events_by_id.get(r.event_id)) for r in rows],
               "page": page, "page_size": page_size, "total": total, "pages": (total + page_size - 1) // page_size})


@router.post("/deliveries/{delivery_id}/replay")
def replay_delivery(delivery_id: str, db: Session = Depends(get_db), user: User = Depends(require_entity_admin),
                    entity: Entity = Depends(get_current_entity)):
    try:
        row = db.get(StudioDelivery, uuid.UUID(delivery_id))
    except ValueError:
        row = None
    if row is None or row.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Delivery not found")
    again = hooks.replay(db, entity, row, user)
    db.commit()
    return ok(hooks.describe_delivery(again, db.get(StudioEvent, again.event_id)))


@router.post("/webhooks/{webhook_id}/replay-failed")
def replay_failed(webhook_id: str, db: Session = Depends(get_db), user: User = Depends(require_entity_admin),
                  entity: Entity = Depends(get_current_entity)):
    hook = _webhook(db, entity, webhook_id)
    failed = (db.query(StudioDelivery).filter(StudioDelivery.webhook_id == hook.id, StudioDelivery.status == "failed")
              .all())
    replayed = [hooks.replay(db, entity, d, user) for d in failed]
    for d in failed:
        d.status = "replayed"
    db.commit()
    return ok({"replayed": len(replayed)})


@router.get("/inbound")
def list_inbound(request: Request, db: Session = Depends(get_db), entity: Entity = Depends(require_studio_reader)):
    base = str(request.base_url).rstrip("/") + "/api/integration/v1"
    rows = (db.query(StudioInboundEndpoint).filter(StudioInboundEndpoint.entity_id == entity.id)
            .order_by(StudioInboundEndpoint.name).all())
    return ok([hooks.describe_inbound(r, base) for r in rows])


@router.post("/inbound")
def create_inbound(body: InboundBody, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    try:
        endpoint, secret = hooks.create_inbound(
            db, entity, user, name=body.name, environment=body.environment,
            action={"type": "import", "object_type": body.object_type, "mapping_key": body.mapping_key,
                    "options": body.options})
    except (ValueError, vault.SecretStoreUnavailable) as exc:
        db.rollback()
        raise _http(exc)
    db.commit()
    base = str(request.base_url).rstrip("/") + "/api/integration/v1"
    return ok({**hooks.describe_inbound(endpoint, base), "secret": secret, "shown_once": True})


@router.patch("/inbound/{endpoint_id}")
def update_inbound(endpoint_id: str, body: WebhookBody, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    endpoint = _inbound(db, entity, endpoint_id)
    if body.status:
        endpoint.status = body.status
        from app.services import audit

        audit.record(db, entity_id=entity.id, user=user, action="studio.inbound.updated",
                     object_type="studio_inbound_endpoint", object_id=str(endpoint.id),
                     summary=f"Set inbound endpoint “{endpoint.name}” to {endpoint.status}")
    db.commit()
    return ok(hooks.describe_inbound(endpoint, str(request.base_url).rstrip("/") + "/api/integration/v1"))


@router.get("/inbound/{endpoint_id}/receipts")
def inbound_receipts(endpoint_id: str, db: Session = Depends(get_db), entity: Entity = Depends(require_studio_reader)):
    endpoint = _inbound(db, entity, endpoint_id)
    rows = (db.query(StudioInboundReceipt).filter(StudioInboundReceipt.endpoint_id == endpoint.id)
            .order_by(StudioInboundReceipt.received_at.desc()).limit(200).all())
    return ok([{"id": str(r.id), "event_id": r.event_id, "run_id": str(r.run_id) if r.run_id else None,
                "received_at": r.received_at.isoformat() if r.received_at else None} for r in rows])
