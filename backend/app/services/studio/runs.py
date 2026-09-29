"""
Studio runs: the queue and the record.

A run is created when work is asked for, processed by the worker, and kept as
the evidence of what happened: who started it, what arrived, what was accepted
and rejected and why, which versions applied, what it produced downstream. The
same row is the queue entry and the history entry — a separate queue would be
a second truth about the same work.

The queue mechanics copy ``validation_jobs``: ``FOR UPDATE SKIP LOCKED`` on
PostgreSQL so two workers never take the same run, a lease renewed while
working, and a run whose worker went silent is picked up again. An import
commits its records in one transaction, so a crash mid-way leaves nothing
behind and the retry starts clean.
"""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.models import StudioRun, StudioRunRejection

LEASE_SECONDS = 120

#: Counts every import reports, in reading order.
COUNT_KEYS = ("received", "accepted", "rejected", "skipped", "created", "updated", "unchanged", "removed")

#: What someone should do, by error category. Shown beside every failure.
RECOMMENDED = {
    "input": "Correct the rejected records at the source and send them again — only those.",
    "configuration": "Fix the configuration named in the message, then retry the rejected records.",
    "permission": "Ask an owner or manager to grant this key the scope or company it needs.",
    "conflict": "Another run holds this month. Wait for it to finish, then retry.",
    "transient": "Nothing to change — the run is retried automatically.",
    "internal": "Retry once. If it fails again, send the run id to support.",
    "cancelled": "Start a new run when ready.",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def gz(value: Any) -> bytes:
    return gzip.compress(json.dumps(value, default=str, separators=(",", ":")).encode("utf-8"))


def ungz(blob: bytes | None) -> Any:
    if not blob:
        return None
    return json.loads(gzip.decompress(blob).decode("utf-8"))


def sha256_of(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def create(
    db: Session,
    *,
    org_id: uuid.UUID,
    entity_id: uuid.UUID,
    kind: str,
    object_type: str | None,
    actor_type: str,
    actor_user_id: uuid.UUID,
    actor_label: str,
    trigger: str = "api",
    environment: str = "production",
    service_account_id: uuid.UUID | None = None,
    credential_prefix: str | None = None,
    source_system: str | None = None,
    source_object: str | None = None,
    batch_id: str | None = None,
    period_month: date | None = None,
    effective_from: date | None = None,
    options: dict[str, Any] | None = None,
    payload: Any = None,
    versions: dict[str, Any] | None = None,
    request_id: str | None = None,
    idempotency_key: str | None = None,
    retry_of_run_id: uuid.UUID | None = None,
    status: str = "queued",
    connection_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
) -> StudioRun:
    run = StudioRun(
        org_id=org_id, entity_id=entity_id, kind=kind, object_type=object_type,
        status=status, stage=status, trigger=trigger, actor_type=actor_type,
        actor_user_id=actor_user_id, actor_label=actor_label[:255], environment=environment,
        service_account_id=service_account_id, credential_prefix=credential_prefix,
        source_system=source_system, source_object=source_object, batch_id=batch_id,
        period_month=period_month, effective_from=effective_from, options=options or {},
        counts={}, versions=versions or {}, result_ref={},
        payload_gz=gz(payload) if payload is not None else None,
        payload_sha256=sha256_of(payload) if payload is not None else None,
        request_id=request_id, idempotency_key=idempotency_key, retry_of_run_id=retry_of_run_id,
        connection_id=connection_id, workflow_id=workflow_id, queued_at=_now(),
    )
    db.add(run)
    db.flush()
    return run


# ---------------------------------------------------------------------------
# Claiming
# ---------------------------------------------------------------------------
_CLAIMABLE = """
    SELECT id FROM studio_runs
    WHERE ((status = 'queued' AND queued_at <= :now)
       OR (status = 'running' AND (heartbeat_at IS NULL OR heartbeat_at < :stale)))
      AND kind IN ('import', 'sync')
    ORDER BY queued_at
    {locking}
    LIMIT 1
"""


def claim(db: Session, worker: str, kinds: tuple[str, ...] | None = None) -> StudioRun | None:
    locking = "FOR UPDATE SKIP LOCKED" if db.bind.dialect.name == "postgresql" else ""
    stale = _now() - timedelta(seconds=LEASE_SECONDS)
    row = db.execute(text(_CLAIMABLE.format(locking=locking)),  # nosec B608
                     {"stale": stale, "now": _now()}).first()
    if row is None:
        db.rollback()
        return None
    run_id = row[0] if isinstance(row[0], uuid.UUID) else uuid.UUID(str(row[0]))
    run = db.get(StudioRun, run_id)
    if run is None:
        db.rollback()
        return None
    if run.cancel_requested_at is not None and run.status == "queued":
        finish(db, run, "cancelled", error_category="cancelled", error_message="Cancelled before it started.")
        db.commit()
        return None
    run.status = "running"
    run.stage = "starting"
    run.worker_id = worker[:100]
    run.attempts = (run.attempts or 0) + 1
    run.started_at = run.started_at or _now()
    run.heartbeat_at = _now()
    db.commit()
    return run


def heartbeat(db: Session, run: StudioRun, stage: str | None = None) -> None:
    run.heartbeat_at = _now()
    if stage:
        run.stage = stage
    db.commit()


def finish(
    db: Session,
    run: StudioRun,
    status: str,
    *,
    counts: dict[str, int] | None = None,
    error_category: str | None = None,
    error_message: str | None = None,
    result_ref: dict[str, Any] | None = None,
) -> StudioRun:
    run.status = status
    run.stage = status
    run.finished_at = _now()
    run.heartbeat_at = None
    if counts is not None:
        run.counts = {k: int(counts.get(k, 0)) for k in COUNT_KEYS}
    if error_category:
        run.error_category = error_category
        run.error_message = (error_message or "")[:4000]
        run.recommended_action = RECOMMENDED.get(error_category)
    if result_ref:
        run.result_ref = {**(run.result_ref or {}), **result_ref}
    # The staged input has done its job; the rejected records keep their own
    # copies, and the accepted ones are stored where they belong.
    if status in ("completed", "partially_completed", "failed", "cancelled"):
        run.payload_gz = None
        if run.kind in ("import", "sync"):
            # In the same transaction as the run's final state and its records.
            from app.services.studio import events

            events.emit(db, org_id=run.org_id, entity_id=run.entity_id, type="import.completed",
                        data={"run_id": str(run.id), "kind": run.kind, "object_type": run.object_type,
                              "status": status, "counts": run.counts or {}, "batch_id": run.batch_id},
                        causation=(run.options or {}).get("causation") or {})
    return run


def request_cancel(db: Session, run: StudioRun) -> StudioRun:
    if run.status == "queued":
        run.cancel_requested_at = _now()
        finish(db, run, "cancelled", error_category="cancelled", error_message="Cancelled before it started.")
    elif run.status == "running":
        run.cancel_requested_at = _now()
    return run


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------
def reject(
    db: Session,
    run: StudioRun,
    *,
    row_number: int,
    code: str,
    message: str,
    record: dict[str, Any] | None,
    record_key: str | None = None,
    field: str | None = None,
    disposition: str = "rejected",
    retain_days: int = 30,
    source_record_id: str | None = None,
) -> StudioRunRejection:
    ref = {
        "system": run.source_system,
        "object": run.source_object,
        "record_id": source_record_id or ((record or {}).get("_source_record_id") if isinstance(record, dict) else None),
        "batch_id": run.batch_id,
    }
    row = StudioRunRejection(
        run_id=run.id, entity_id=run.entity_id, row_number=row_number,
        record_key=(str(record_key)[:100] if record_key is not None else None),
        disposition=disposition, code=code, field=field, message=message[:2000],
        source_ref={k: v for k, v in ref.items() if v is not None},
        payload_gz=gz(record) if record is not None else None,
        retain_until=date.today() + timedelta(days=retain_days),
    )
    db.add(row)
    return row


def rejections(db: Session, run: StudioRun, *, page: int = 1, page_size: int = 100,
               disposition: str | None = None) -> tuple[list[StudioRunRejection], int]:
    q = db.query(StudioRunRejection).filter(StudioRunRejection.run_id == run.id)
    if disposition:
        q = q.filter(StudioRunRejection.disposition == disposition)
    total = q.count()
    rows = q.order_by(StudioRunRejection.row_number).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def describe_rejection(row: StudioRunRejection, *, with_payload: bool = False) -> dict[str, Any]:
    out = {
        "id": str(row.id),
        "row_number": row.row_number,
        "record_key": row.record_key,
        "disposition": row.disposition,
        "code": row.code,
        "field": row.field,
        "message": row.message,
        "source_ref": row.source_ref or {},
        "retried_in_run_id": str(row.retried_in_run_id) if row.retried_in_run_id else None,
        "payload_retained": row.payload_gz is not None,
        "retain_until": row.retain_until.isoformat() if row.retain_until else None,
    }
    if with_payload:
        out["record"] = ungz(row.payload_gz)
    return out


def purge_expired_payloads(db: Session, today: date | None = None) -> int:
    """Drop retained record copies past their date. The rejection itself stays."""
    today = today or date.today()
    n = (
        db.query(StudioRunRejection)
        .filter(StudioRunRejection.retain_until < today, StudioRunRejection.payload_gz.is_not(None))
        .update({StudioRunRejection.payload_gz: None}, synchronize_session=False)
    )
    db.commit()
    return n


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def live_status(db: Session, run: StudioRun) -> str:
    """A validation run's status follows the job it started."""
    if run.kind == "validation" and run.validation_job_id is not None:
        from app.models import ValidationJob

        job = db.get(ValidationJob, run.validation_job_id)
        if job is not None:
            return {
                "queued": "queued", "running": "running", "succeeded": "completed",
                "failed": "failed", "cancelled": "cancelled",
            }.get(job.state, run.status)
    return run.status


def describe(db: Session, run: StudioRun, *, detail: bool = False) -> dict[str, Any]:
    status = live_status(db, run)
    counts = run.counts or {}
    out: dict[str, Any] = {
        "id": str(run.id),
        "kind": run.kind,
        "object_type": run.object_type,
        "status": status,
        "stage": run.stage if status == run.status else status,
        "trigger": run.trigger,
        "actor": {"type": run.actor_type, "label": run.actor_label,
                  "credential_prefix": run.credential_prefix},
        "environment": run.environment,
        "company_id": str(run.entity_id),
        "source": {"system": run.source_system, "object": run.source_object, "batch_id": run.batch_id},
        "period_month": run.period_month.isoformat() if run.period_month else None,
        "effective_from": run.effective_from.isoformat() if run.effective_from else None,
        "counts": {k: counts.get(k) for k in COUNT_KEYS} if counts else None,
        "versions": run.versions or {},
        "error": (
            {"category": run.error_category, "message": run.error_message,
             "recommended_action": run.recommended_action}
            if run.error_category else None
        ),
        "attempts": run.attempts,
        "retry_of_run_id": str(run.retry_of_run_id) if run.retry_of_run_id else None,
        "links": {
            "validation_job_id": str(run.validation_job_id) if run.validation_job_id else None,
            "validation_run_id": str(run.validation_run_id) if run.validation_run_id else None,
            "connection_id": str(run.connection_id) if run.connection_id else None,
            "workflow_id": str(run.workflow_id) if run.workflow_id else None,
            **dict(run.result_ref or {}),
        },
        "request_id": run.request_id,
        "queued_at": _aware(run.queued_at).isoformat() if run.queued_at else None,
        "started_at": _aware(run.started_at).isoformat() if run.started_at else None,
        "finished_at": _aware(run.finished_at).isoformat() if run.finished_at else None,
    }
    if run.validation_job_id is not None and not out["links"].get("validation_run_id"):
        from app.models import ValidationJob

        job = db.get(ValidationJob, run.validation_job_id)
        if job is not None and job.run_id is not None:
            out["links"]["validation_run_id"] = str(job.run_id)
    if detail:
        out["options"] = run.options or {}
        retries = db.query(StudioRun).filter(StudioRun.retry_of_run_id == run.id).order_by(StudioRun.queued_at).all()
        out["retries"] = [{"id": str(r.id), "status": live_status(db, r), "queued_at": _aware(r.queued_at).isoformat()} for r in retries]
        reasons = (
            db.query(StudioRunRejection.code, StudioRunRejection.disposition)
            .filter(StudioRunRejection.run_id == run.id)
            .all()
        )
        by_code: dict[str, int] = {}
        for code, disposition in reasons:
            key = f"{disposition}:{code}"
            by_code[key] = by_code.get(key, 0) + 1
        out["rejection_summary"] = [
            {"disposition": k.split(":", 1)[0], "code": k.split(":", 1)[1], "count": v}
            for k, v in sorted(by_code.items(), key=lambda kv: -kv[1])
        ]
    return out


def search(
    db: Session,
    entity_id: uuid.UUID,
    *,
    kind: str | None = None,
    status: str | None = None,
    object_type: str | None = None,
    actor_type: str | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[StudioRun], int]:
    query = db.query(StudioRun).filter(StudioRun.entity_id == entity_id)
    if kind:
        query = query.filter(StudioRun.kind == kind)
    if status:
        query = query.filter(StudioRun.status == status)
    if object_type:
        query = query.filter(StudioRun.object_type == object_type)
    if actor_type:
        query = query.filter(StudioRun.actor_type == actor_type)
    if date_from:
        query = query.filter(StudioRun.queued_at >= datetime.combine(date_from, datetime.min.time(), UTC))
    if date_to:
        query = query.filter(StudioRun.queued_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), UTC))
    if q:
        like = f"%{q.strip()}%"
        clauses = [StudioRun.batch_id.ilike(like), StudioRun.actor_label.ilike(like),
                   StudioRun.source_system.ilike(like), StudioRun.source_object.ilike(like),
                   StudioRun.request_id.ilike(like)]
        with contextlib.suppress(ValueError):
            clauses.append(StudioRun.id == uuid.UUID(q.strip()))
        query = query.filter(or_(*clauses))
    total = query.count()
    rows = query.order_by(StudioRun.queued_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return rows, total
