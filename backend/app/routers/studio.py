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

from fastapi import APIRouter, Depends, HTTPException, Query
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
    {"key": "connections", "label": "Connections", "href": None, "available": False,
     "summary": "REST and file connections to HRMS, attendance and finance systems. Not in this release."},
    {"key": "mapping", "label": "Data mapping", "href": None, "available": False,
     "summary": "Versioned mapping from external fields to product fields. Not in this release."},
    {"key": "workflows", "label": "Workflows", "href": None, "available": False,
     "summary": "Trigger → conditions → actions automation. Not in this release."},
    {"key": "webhooks", "label": "Webhooks", "href": None, "available": False,
     "summary": "Signed inbound and outbound events. Not in this release."},
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
