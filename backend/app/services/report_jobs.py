"""Postgres-backed queue for bounded aggregate report generation."""
from __future__ import annotations

import logging
import socket
import threading
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import SessionLocal
from app.models import Entity, ReportDefinition, ReportJob, ReportSchedule, User
from app.services import report_builder, report_exports, tenancy

logger = logging.getLogger("payroll.report_worker")
_stop = threading.Event()
_thread: threading.Thread | None = None
LEASE = timedelta(minutes=15)
MAX_ATTEMPTS = 2


def _now():
    return datetime.now(UTC)


def _aware(value):
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def enqueue(db, *, entity, report, user, fmt: str = "xlsx", specification: dict | None = None,
            origin: str = "person"):
    current = (db.query(ReportJob).filter(
        ReportJob.entity_id == entity.id, ReportJob.definition_id == report.id,
        ReportJob.requester_id == user.id, ReportJob.state.in_(("queued", "running"))
    ).first())
    if current:
        return current
    job = ReportJob(org_id=entity.org_id, entity_id=entity.id, definition_id=report.id,
                    requester_id=user.id, definition_version=report.version,
                    definition_name=report.name, specification=specification or report.specification,
                    state="queued", stage="queued", attempt=0, format=fmt, origin=origin)
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
            payload, info = report_exports.build(db, entity, snapshot, user, job.format or "xlsx")
            job = db.get(ReportJob, job_id)
            if job.cancel_requested:
                job.state, job.stage, job.finished_at = "cancelled", "cancelled", _now()
            elif len(payload) > settings.report_artifact_max_mb * 1024 * 1024:
                job.state, job.stage = "failed", "failed"
                job.error_code = "output_too_large"
                job.error_message = "The generated file exceeds the configured output limit"
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


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------
IST = timedelta(hours=5, minutes=30)  # India has no daylight saving


def next_run(frequency: str, day: int, hour: int, after: datetime) -> datetime:
    """The first scheduled moment strictly after ``after``, in UTC."""
    local = _aware(after) + IST
    if frequency == "weekly":
        candidate = local.replace(hour=hour, minute=0, second=0, microsecond=0)
        candidate += timedelta(days=(day - candidate.weekday()) % 7)
        if candidate <= local:
            candidate += timedelta(days=7)
    else:
        candidate = local.replace(day=day, hour=hour, minute=0, second=0, microsecond=0)
        if candidate <= local:
            year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
            candidate = candidate.replace(year=year, month=month)
    return candidate - IST


def rolling_window(months: int, when: datetime) -> tuple[str, str]:
    """``months`` complete months ending with the month before ``when`` (India time)."""
    local = _aware(when) + IST
    end_year, end_month = (local.year - 1, 12) if local.month == 1 else (local.year, local.month - 1)
    index = end_year * 12 + (end_month - 1) - (months - 1)
    return date(index // 12, index % 12 + 1, 1).isoformat(), date(end_year, end_month, 1).isoformat()


def schedule_due(db, now: datetime | None = None) -> int:
    """Queue every schedule whose time has come. Commits. Returns how many ran."""
    now = now or _now()
    query = (db.query(ReportSchedule)
             .filter(ReportSchedule.enabled.is_(True), ReportSchedule.next_run_at <= now)
             .order_by(ReportSchedule.next_run_at))
    if db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    ran = 0
    for schedule in query.limit(20).all():
        schedule.last_run_at = now
        schedule.next_run_at = next_run(schedule.frequency, schedule.day, schedule.hour, now)
        try:
            user = db.get(User, schedule.owner_user_id)
            entity = db.get(Entity, schedule.entity_id)
            report = db.get(ReportDefinition, schedule.definition_id)
            job = SimpleNamespace(requester_id=schedule.owner_user_id, entity_id=schedule.entity_id,
                                  definition_id=schedule.definition_id, org_id=schedule.org_id)
            _permission(db, job)
            spec = dict(report_builder.validate(report.specification))
            spec["date_from"], spec["date_to"] = rolling_window(schedule.months, now)
            queued = enqueue(db, entity=entity, report=report, user=user, fmt=schedule.format,
                             specification=report_builder.validate(spec), origin="schedule")
            schedule.last_job_id = queued.id
            schedule.last_error = None
            ran += 1
        except ValueError as exc:
            # Access or the report itself went away: stop, and say why, rather
            # than keep producing files nobody may open.
            schedule.enabled = False
            schedule.last_error = str(exc)[:500]
    db.commit()
    return ran


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


def _run_schedules() -> None:
    db = SessionLocal()
    try:
        schedule_due(db)
    finally:
        db.close()


def _loop():
    while not _stop.is_set():
        try:
            if not run_once():
                _run_schedules()
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
