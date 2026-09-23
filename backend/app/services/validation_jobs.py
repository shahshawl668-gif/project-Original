"""
The queue, in the database we already have.

``SELECT ... FOR UPDATE SKIP LOCKED`` is a correct queue primitive and has been
for a decade. Using PostgreSQL rather than Redis buys two things that matter
more here than throughput:

**No third piece of infrastructure.** Redis would be another service, another
bill, and another process holding payroll-adjacent data.

**No dual-write problem.** A job's state and the findings it produces commit in
the same transaction. With a separate broker they cannot, so a crash between
the two leaves a job marked done with nothing written — which is worse than a
job that simply ran twice.

Redis earns its place at thousands of jobs a minute. This is tens a day,
concentrated in one week a month.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ACTIVE_STATES,
    CHUNK_SIZE,
    LEASE_SECONDS,
    TERMINAL_STATES,
    ValidationJob,
)

__all__ = [
    "CHUNK_SIZE",
    "AlreadyQueued",
    "claim",
    "enqueue",
    "fail",
    "heartbeat",
    "mark_cancelled",
    "succeed",
]


class AlreadyQueued(Exception):
    """This entity already has live work for this period."""

    def __init__(self, job: ValidationJob):
        super().__init__("A validation is already queued or running for this period.")
        self.job = job


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    """
    A timestamp that can be compared.

    SQLite hands back naive datetimes even for a timezone-aware column, so a
    direct comparison against an aware ``now`` raises. A naive value is treated
    as UTC, which is what it was written as.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def lease_expired(job: ValidationJob, at: datetime | None = None) -> bool:
    """
    Has the worker holding this job gone quiet for too long?

    Derived from the stored heartbeat rather than swept, so a job abandoned
    overnight is reclaimable the moment anyone looks, without a cleanup task
    having run.
    """
    if job.state != "running":
        return False
    beat = _aware(job.heartbeat_at) or _aware(job.started_at)
    if beat is None:
        return True
    return beat <= (at or _now()) - timedelta(seconds=LEASE_SECONDS)


# ---------------------------------------------------------------------------
# Enqueuing
# ---------------------------------------------------------------------------
def active_for(db: Session, entity_id: uuid.UUID, period_month: date) -> ValidationJob | None:
    return (
        db.query(ValidationJob)
        .filter(
            ValidationJob.entity_id == entity_id,
            ValidationJob.period_month == period_month,
            ValidationJob.state.in_(ACTIVE_STATES),
        )
        .first()
    )


def enqueue(
    db: Session,
    *,
    entity_id: uuid.UUID,
    user_id: uuid.UUID,
    period_month: date,
    register_id: uuid.UUID | None = None,
    run_type: str = "regular",
    params: dict | None = None,
) -> ValidationJob:
    """
    Queue one validation, or refuse because one is already live.

    Checked in Python *and* enforced by a partial unique index. The check gives
    a useful error; the index is what actually holds when two requests arrive
    at once, which is exactly what a double-click produces.
    """
    existing = active_for(db, entity_id, period_month)
    if existing is not None:
        raise AlreadyQueued(existing)

    job = ValidationJob(
        entity_id=entity_id,
        user_id=user_id,
        register_id=register_id,
        period_month=period_month,
        run_type=run_type,
        params=params or {},
        state="queued",
        queued_at=_now(),
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError as exc:
        # The index caught the race the check could not.
        db.rollback()
        live = active_for(db, entity_id, period_month)
        if live is not None:
            raise AlreadyQueued(live) from exc
        raise
    return job


# ---------------------------------------------------------------------------
# Claiming
# ---------------------------------------------------------------------------
_CLAIMABLE = """
    SELECT id FROM validation_jobs
    WHERE state = 'queued'
       OR (state = 'running' AND (
             heartbeat_at IS NULL OR heartbeat_at < :stale
           ))
    ORDER BY queued_at
    {locking}
    LIMIT 1
"""


def claim(db: Session, worker_id: str, at: datetime | None = None) -> ValidationJob | None:
    """
    Take the oldest piece of work nobody else holds, or return ``None``.

    Two things are being claimed: jobs waiting to start, and jobs whose worker
    stopped heartbeating. The second is crash recovery — a worker killed by a
    deploy or the OOM killer leaves its job behind, and without this it would
    sit in ``running`` forever.

    ``FOR UPDATE SKIP LOCKED`` is what lets several workers share one table
    without queueing behind each other. SQLite has no such clause; it also has
    no concurrent writers, so the plain statement is correct there. The branch
    exists because the tests run on SQLite and production runs on PostgreSQL,
    and a queue that is only exercised on one of them is not tested.
    """
    now = at or _now()
    stale = now - timedelta(seconds=LEASE_SECONDS)
    is_sqlite = db.bind.dialect.name == "sqlite"

    # The row lock taken by FOR UPDATE is held until this transaction ends,
    # so the UPDATE below cannot race another worker that skipped past it.
    sql = _CLAIMABLE.format(locking="" if is_sqlite else "FOR UPDATE SKIP LOCKED")
    row = db.execute(text(sql), {"stale": stale}).first()
    if row is None:
        return None

    # Raw SQL hands the id back the way the dialect stores it: a UUID on
    # PostgreSQL, a 32-character hex string on SQLite. Coerce before looking it
    # up, or the ORM tries to read `.hex` off a str.
    raw = row[0]
    job = db.get(ValidationJob, raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw)))
    if job is None:
        return None

    job.state = "running"
    job.locked_by = worker_id[:64]
    job.started_at = job.started_at or now
    job.heartbeat_at = now
    job.attempts = (job.attempts or 0) + 1
    db.flush()
    return job


# ---------------------------------------------------------------------------
# Progress and completion
# ---------------------------------------------------------------------------
def heartbeat(db: Session, job: ValidationJob, *, done: int | None = None) -> ValidationJob:
    """Renew the lease, and publish progress while we are here."""
    job.heartbeat_at = _now()
    if done is not None:
        # Never claim more progress than there is work; a UI showing 11,000 of
        # 10,000 is a UI nobody trusts again.
        job.employee_done = max(0, min(done, job.employee_total or done))
    return job


def succeed(db: Session, job: ValidationJob, *, run_id: uuid.UUID | None) -> ValidationJob:
    job.state = "succeeded"
    job.run_id = run_id
    job.error = None
    job.finished_at = _now()
    job.locked_by = None
    if job.employee_total:
        job.employee_done = job.employee_total
    return job


def fail(db: Session, job: ValidationJob, *, error: str) -> ValidationJob:
    """
    Record a failure, and decide whether it is worth another go.

    Retries are for the transient — a dropped connection, a worker that died.
    Once the attempts are spent the job stops, because a rule that raises on one
    employee's data will raise every time, and an endless loop is a worse
    failure than a visible one.
    """
    job.error = (error or "")[:2000]
    job.locked_by = None
    job.heartbeat_at = None
    if (job.attempts or 0) >= (job.max_attempts or 1):
        job.state = "failed"
        job.finished_at = _now()
    else:
        job.state = "queued"
    return job


def mark_cancelled(db: Session, job: ValidationJob) -> ValidationJob:
    if job.state in TERMINAL_STATES:
        return job
    job.state = "cancelled"
    job.finished_at = _now()
    job.locked_by = None
    job.heartbeat_at = None
    return job


def describe(job: ValidationJob) -> dict:
    """What a caller polling this job is entitled to know."""
    total = job.employee_total or 0
    done = job.employee_done or 0
    return {
        "id": str(job.id),
        "state": job.state,
        "period_month": job.period_month.isoformat() if job.period_month else None,
        "run_type": job.run_type,
        "employee_total": total,
        "employee_done": done,
        "percent": round(done * 100 / total) if total else 0,
        "run_id": str(job.run_id) if job.run_id else None,
        "error": job.error,
        "attempts": job.attempts or 0,
        "queued_at": job.queued_at.isoformat() if job.queued_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
