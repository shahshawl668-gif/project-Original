"""Postgres-backed queue for bounded aggregate report generation."""
from __future__ import annotations

import logging
import socket
import threading
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import SessionLocal
from app.models import Entity, ReportDefinition, ReportJob, User
from app.services import report_exports, tenancy

logger = logging.getLogger("payroll.report_worker")
_stop = threading.Event()
_thread: threading.Thread | None = None
LEASE = timedelta(minutes=15)
MAX_ATTEMPTS = 2


def _now():
    return datetime.now(UTC)


def _aware(value):
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def enqueue(db, *, entity, report, user):
    current = (db.query(ReportJob).filter(
        ReportJob.entity_id == entity.id, ReportJob.definition_id == report.id,
        ReportJob.requester_id == user.id, ReportJob.state.in_(("queued", "running"))
    ).first())
    if current:
        return current
    job = ReportJob(org_id=entity.org_id, entity_id=entity.id, definition_id=report.id,
                    requester_id=user.id, definition_version=report.version,
                    definition_name=report.name, specification=report.specification,
                    state="queued", stage="queued", attempt=0)
    db.add(job)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return db.query(ReportJob).filter(
            ReportJob.entity_id == entity.id, ReportJob.definition_id == report.id,
            ReportJob.requester_id == user.id, ReportJob.state.in_(("queued", "running"))
        ).one()
    return job


def _claim(db):
    now = _now()
    stale = now - LEASE
    # Atomic conditional update makes SQLite development safe; PostgreSQL's
    # row lock avoids workers repeatedly trying the same oldest job.
    query = (db.query(ReportJob)
             .filter((ReportJob.state == "queued") |
                     ((ReportJob.state == "running") & (ReportJob.heartbeat_at < stale)))
             .order_by(ReportJob.queued_at))
    if db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    job = query.first()
    if job is None:
        return None
    previous = job.state
    result = db.execute(
        update(ReportJob).where(ReportJob.id == job.id, ReportJob.state == previous)
        .values(state="running", stage="preparing", attempt=job.attempt + 1,
                worker_id=f"{socket.gethostname()[:30]}/{uuid.uuid4().hex[:8]}",
                started_at=job.started_at or now, heartbeat_at=now)
    )
    if result.rowcount != 1:
        db.rollback()
        return None
    db.commit()
    return job.id


def _permission(db, job):
    user = db.get(User, job.requester_id)
    entity = db.get(Entity, job.entity_id)
    definition = db.get(ReportDefinition, job.definition_id)
    if not user or not entity or not definition or entity.org_id != job.org_id:
        raise ValueError("Report or company no longer exists")
    if definition.entity_id != entity.id or definition.status == "retired":
        raise ValueError("Report is no longer available")
    if definition.visibility == "private" and definition.owner_user_id != user.id:
        raise ValueError("Private report access has been revoked")
    if not tenancy.role_at_least(db, user, "analyst", entity):
        raise ValueError("Report access has been revoked")
    return user, entity


def run_once() -> bool:
    db = SessionLocal()
    try:
        job_id = _claim(db)
        if job_id is None:
            return False
        job = db.get(ReportJob, job_id)
        if job.cancel_requested:
            job.state, job.stage, job.finished_at = "cancelled", "cancelled", _now()
            db.commit()
            return True
        try:
            user, entity = _permission(db, job)
            snapshot = SimpleNamespace(id=job.definition_id, name=job.definition_name,
                                       version=job.definition_version, specification=job.specification)
            job.stage = "generating"
            job.heartbeat_at = _now()
            db.commit()
            payload, info = report_exports.build(db, entity, snapshot, user)
            job = db.get(ReportJob, job_id)
            if job.cancel_requested:
                job.state, job.stage, job.finished_at = "cancelled", "cancelled", _now()
            elif len(payload) > settings.report_artifact_max_mb * 1024 * 1024:
                job.state, job.stage = "failed", "failed"
                job.error_code = "output_too_large"
                job.error_message = "The aggregate workbook exceeds the configured output limit"
                job.finished_at = _now()
            else:
                job.artifact = payload
                job.artifact_bytes = len(payload)
                job.artifact_sha256 = info["sha256"]
                job.record_count = info["record_count"]
                job.control_totals = info["control_totals"]
                job.source_references = info["source_references"]
                job.state, job.stage, job.finished_at = "succeeded", "completed", _now()
                job.expires_at = _now() + timedelta(days=settings.report_artifact_retention_days)
            db.commit()
        except ValueError as exc:
            db.rollback()
            job = db.get(ReportJob, job_id)
            job.state, job.stage, job.finished_at = "failed", "failed", _now()
            job.error_code, job.error_message = "invalid_or_revoked", str(exc)[:500]
            db.commit()
        except Exception:
            logger.exception("Report job %s failed", job_id)
            db.rollback()
            job = db.get(ReportJob, job_id)
            job.error_code, job.error_message = "generation_failed", "Report generation failed"
            if job.attempt < MAX_ATTEMPTS and not job.cancel_requested:
                job.state, job.stage = "queued", "retrying"
                job.heartbeat_at = None
            else:
                job.state, job.stage, job.finished_at = "failed", "failed", _now()
            db.commit()
        return True
    finally:
        db.close()


def cleanup_expired() -> int:
    db = SessionLocal()
    try:
        jobs = (db.query(ReportJob)
                .filter(ReportJob.expires_at <= _now(), ReportJob.artifact.isnot(None))
                .limit(50).all())
        for job in jobs:
            job.artifact = None
            job.stage = "expired"
        db.commit()
        return len(jobs)
    finally:
        db.close()


def _loop():
    while not _stop.is_set():
        try:
            if not run_once():
                cleanup_expired()
                _stop.wait(2)
        except Exception:
            logger.exception("Report worker loop failed")
            _stop.wait(5)


def start_in_thread():
    global _thread
    if not settings.report_worker_enabled:
        return False
    if _thread and _thread.is_alive():
        return True
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="peopleops-report-worker", daemon=True)
    _thread.start()
    return True


def stop():
    _stop.set()
