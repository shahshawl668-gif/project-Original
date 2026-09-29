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
    "request_cancel",
    "set_stage",
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
    upload_id: uuid.UUID | None = None,
    retry_of_job_id: uuid.UUID | None = None,
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
        upload_id=upload_id,
        retry_of_job_id=retry_of_job_id,
        state="queued",
        stage="queued",
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


def _bind_id(db: Session, value: uuid.UUID) -> object:
    """A UUID in the form this dialect stores it.

    SQLite keeps them as 32-character hex with no dashes; PostgreSQL has a real
    UUID type. Passing the wrong one silently matches no rows, which in a claim
    query looks exactly like "another worker got there first".
    """
    return value if db.bind.dialect.name != "sqlite" else value.hex


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
    job_id = raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))

    # Take it with a guarded UPDATE rather than by assigning to the ORM object.
    # On PostgreSQL the row lock above already made this safe; on SQLite there
    # is no such lock, and two workers selecting the same id would both proceed
    # to run the job. The WHERE clause repeats the claimable condition, so
    # whichever UPDATE lands second matches no rows and that worker backs off.
    # A queue that is only correct on the production dialect is a queue whose
    # concurrency is never actually tested.
    claimed = db.execute(
        text(
            """
            UPDATE validation_jobs
            SET state = 'running',
                stage = 'loading',
                locked_by = :worker,
                started_at = COALESCE(started_at, :now),
                heartbeat_at = :now,
                attempts = attempts + 1
            WHERE id = :id
              AND (state = 'queued'
                   OR (state = 'running'
                       AND (heartbeat_at IS NULL OR heartbeat_at < :stale)))
            """
        ),
        {"worker": worker_id[:64], "now": now, "stale": stale,
         "id": _bind_id(db, job_id)},
    )
    if claimed.rowcount != 1:
        return None

    job = db.get(ValidationJob, job_id)
    if job is not None:
        # The UPDATE went round the ORM, so the in-session copy is stale.
        db.refresh(job)
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
    job.stage = "succeeded"
    job.error_code = None
    job.error_message = None
    job.run_id = run_id
    job.error = None
    job.finished_at = _now()
    job.locked_by = None
    if job.employee_total:
        job.employee_done = job.employee_total
    _announce(db, job, "validation.completed", {"job_id": str(job.id), "run_id": str(run_id) if run_id else None,
                                                "period_month": job.period_month.isoformat()})
    return job


def _announce(db: Session, job: ValidationJob, type_: str, data: dict) -> None:
    """Outbox event, in the same transaction as the job's final state."""
    from app.models import Entity
    from app.services.studio import events

    entity = db.get(Entity, job.entity_id)
    if entity is not None:
        events.emit(db, org_id=entity.org_id, entity_id=entity.id, type=type_, data=data)


def fail(
    db: Session,
    job: ValidationJob,
    *,
    error: str,
    permanent: bool = False,
    code: str | None = None,
    message: str | None = None,
) -> ValidationJob:
    """
    Record a failure, and decide whether it is worth another go.

    Retries are for the transient — a dropped connection, a worker that died.
    A ``permanent`` failure is one another attempt cannot fix: no components
    configured, a register missing required columns. Retrying those only makes
    the person wait three times as long for the same answer, so they stop at
    once and say what to fix.

    ``error`` is the raw exception, for whoever operates the platform.
    ``message`` is what the person is shown — never a traceback.
    """
    job.error = (error or "")[:2000]
    job.locked_by = None
    job.heartbeat_at = None
    attempts, limit = job.attempts or 0, job.max_attempts or 1
    if permanent or attempts >= limit:
        job.state = "failed"
        job.stage = "failed"
        job.finished_at = _now()
        job.error_code = code or ("retries_exhausted" if not permanent else "failed")
        job.error_message = message or (
            f"Validation stopped unexpectedly and failed on all {attempts} attempts. "
            f"Retry it; if it fails again, contact support quoting job {str(job.id)[:8]}."
        )
        _announce(db, job, "validation.failed", {"job_id": str(job.id), "period_month": job.period_month.isoformat(),
                                                 "error_code": job.error_code})
    else:
        job.state = "queued"
        job.stage = "queued"
        job.error_code = code or "retrying"
        job.error_message = message or (
            f"Validation stopped unexpectedly and will be retried automatically "
            f"(attempt {attempts + 1} of {limit})."
        )
    return job


def request_cancel(db: Session, job: ValidationJob, user_id: uuid.UUID | None) -> ValidationJob:
    """
    Stop a job, as far as that can be done safely.

    A queued job is cancelled outright — with a guarded UPDATE, because a
    worker may be claiming it at this instant. A running job cannot be stopped
    from outside without risking a half-written run, so it is *asked* to stop:
    the worker checks at its next progress point, rolls back, and nothing of
    the attempt is kept.
    """
    if job.state in TERMINAL_STATES:
        return job
    now = _now()
    cancelled = db.execute(
        text(
            "UPDATE validation_jobs SET state = 'cancelled', stage = 'cancelled', "
            "finished_at = :now, cancel_requested_at = :now, cancelled_by_user_id = :uid "
            "WHERE id = :id AND state = 'queued'"
        ),
        {"now": now, "uid": _bind_id(db, user_id) if user_id else None, "id": _bind_id(db, job.id)},
    )
    if cancelled.rowcount != 1:
        job.cancel_requested_at = now
        job.cancelled_by_user_id = user_id
    db.flush()
    db.refresh(job)
    return job


def mark_cancelled(db: Session, job: ValidationJob) -> ValidationJob:
    if job.state in TERMINAL_STATES:
        return job
    job.state = "cancelled"
    job.stage = "cancelled"
    job.finished_at = _now()
    job.locked_by = None
    job.heartbeat_at = None
    job.error_code = None
    job.error_message = None
    return job


def set_stage(db: Session, job: ValidationJob, stage: str) -> ValidationJob:
    job.stage = stage
    job.heartbeat_at = _now()
    return job


def queue_position(db: Session, job: ValidationJob) -> int | None:
    """How many jobs are ahead of this one. None once it has started."""
    if job.state != "queued":
        return None
    return (
        db.query(ValidationJob)
        .filter(ValidationJob.state == "queued", ValidationJob.queued_at < job.queued_at)
        .count()
    )


STAGE_LABELS = {
    "queued": "Waiting to start",
    "loading": "Reading the register and configuration",
    "validating": "Checking employees",
    "recording": "Saving results",
    "succeeded": "Finished",
    "failed": "Failed",
    "cancelled": "Cancelled",
}


def describe(job: ValidationJob, db: Session | None = None) -> dict:
    """What a caller polling this job is entitled to know.

    The raw exception (``job.error``) is deliberately absent: it is for whoever
    operates the platform. The person gets ``error_message``, written for them.
    """
    total = job.employee_total or 0
    done = job.employee_done or 0
    stage = job.stage or job.state
    if job.state in TERMINAL_STATES:
        stage = job.state
    return {
        "id": str(job.id),
        "state": job.state,
        "stage": stage,
        "stage_label": STAGE_LABELS.get(stage, stage),
        "period_month": job.period_month.isoformat() if job.period_month else None,
        "run_type": job.run_type,
        "upload_id": str(job.upload_id) if job.upload_id else None,
        "employee_total": total,
        "employee_done": done,
        "percent": round(done * 100 / total) if total else 0,
        "run_id": str(job.run_id) if job.run_id else None,
        "error": job.error_message if job.state != "succeeded" else None,
        "error_code": job.error_code if job.state != "succeeded" else None,
        "attempts": job.attempts or 0,
        "max_attempts": job.max_attempts or 0,
        "cancel_requested": job.cancel_requested_at is not None and job.state not in TERMINAL_STATES,
        "retry_of_job_id": str(job.retry_of_job_id) if job.retry_of_job_id else None,
        "queue_position": queue_position(db, job) if db is not None else None,
        "can_cancel": job.state in ACTIVE_STATES,
        "can_retry": job.state in ("failed", "cancelled"),
        "queued_at": job.queued_at.isoformat() if job.queued_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


class SubmitError(Exception):
    """A validation that cannot be queued, with the status and words to say so."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def submit_for_period(
    db: Session,
    *,
    entity_id: uuid.UUID,
    user_id: uuid.UUID,
    period_month: date,
    upload_id: uuid.UUID | None = None,
    run_type: str | None = None,
    params: dict | None = None,
) -> tuple[ValidationJob, bool]:
    """
    Queue validation of a month's named or latest upload.

    Shared by the screen and the integration API. Returns ``(job, already_queued)``;
    a live job for the month is returned rather than a second one started.
    Does not commit.
    """
    from app.models import RegisterUpload
    from app.services import register_uploads

    month = period_month.replace(day=1)
    if upload_id is not None:
        upload = db.get(RegisterUpload, upload_id)
        if upload is None or upload.entity_id != entity_id:
            raise SubmitError(404, "Upload not found")
        if upload.period_month != month:
            raise SubmitError(
                400,
                (f"That upload is for {upload.period_month:%b %Y}" if upload.period_month
                 else "That upload has no payroll month")
                + f", not {month:%b %Y}. Choose the matching month or upload again.",
            )
    else:
        upload = register_uploads.latest_for_period(db, entity_id, month, run_type or "regular")
        if upload is None:
            raise SubmitError(400, f"No register has been uploaded for {month:%b %Y}. Upload it first.")
    if upload.missing_required:
        raise SubmitError(
            400,
            "This register is missing required columns: "
            + ", ".join(upload.missing_required[:10])
            + ". Map or add them and upload again.",
        )
    try:
        job = enqueue(
            db, entity_id=entity_id, user_id=user_id, period_month=month,
            register_id=upload.register_id, upload_id=upload.id,
            run_type=run_type or upload.run_type or "regular", params=params or {},
        )
    except AlreadyQueued as exc:
        return exc.job, True
    job.employee_total = upload.row_count
    return job, False
