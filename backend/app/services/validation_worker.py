"""What actually drains the queue.

PR 1 built the queue and nothing called it. This is the thing that does: claim a
job, validate the register it names, record the run, mark the job done. It runs
either as a thread inside the API container or as its own process — the same
``run_once`` either way, which is the whole reason the queue lives in the
database rather than in the web process.

**Why the register is not validated in batches.** The design sketched chunking
the validation call itself, 200 employees at a time, committing between chunks.
That is wrong for this codebase: findings such as "this person is on the
attendance register but on no payslip" are computed by comparing against the
whole register, so a batch of 200 would report the other 9,800 as missing.
Instead ``validate_employees`` takes a progress callback and the worker renews
its lease from inside the single call. Progress and a live lease, without
changing what gets reported.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import ComponentConfig, Entity, User
from app.services import finding_store
from app.services import validation_jobs as jobs
from app.services.register_rows import count_employees, load_employees
from app.services.validation import (
    _component_key_map,
    apply_suppressed_rules,
    validate_employees,
)

logger = logging.getLogger("payroll.worker")

#: How long to wait before asking for work again when the queue was empty.
IDLE_SLEEP_SECONDS = float(os.environ.get("VALIDATION_WORKER_IDLE_SECONDS", "2.0"))


def worker_id() -> str:
    """Identifies which worker holds a job, in a way that survives a restart usefully.

    Host plus process plus a short random suffix: two workers in one container
    are distinguishable, and a stale lock names a process someone can go and
    look for.
    """
    return f"{socket.gethostname()[:30]}/{os.getpid()}/{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
def _suppressed_rule_ids(db: Session, entity_id: uuid.UUID) -> set[str]:
    """Mirrors the endpoint's own suppression lookup."""
    from app.routers.payroll import _suppressed_rule_ids as endpoint_lookup

    return endpoint_lookup(db, entity_id)


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def execute(db: Session, job) -> uuid.UUID | None:
    """Run one claimed job to completion. Returns the run id it recorded.

    Raises on anything it cannot finish; the caller decides whether that is a
    retry or a terminal failure.
    """
    entity = db.get(Entity, job.entity_id)
    user = db.get(User, job.user_id)
    if entity is None or user is None:
        raise RuntimeError("the job's entity or user no longer exists")

    comps = db.query(ComponentConfig).filter(ComponentConfig.entity_id == entity.id).all()
    if not comps:
        raise RuntimeError("no salary components are configured for this entity")

    if job.register_id is None:
        raise RuntimeError("the job names no register to validate")

    job.employee_total = count_employees(db, job.register_id)
    jobs.heartbeat(db, job, done=0)
    db.commit()

    comp_by_key = _component_key_map(comps)
    employees = load_employees(db, job.register_id, comp_by_key)
    if not employees:
        raise RuntimeError("the register this job names has no rows")

    params = job.params or {}

    def progress(done: int) -> None:
        # Renewing the lease is the point; the number is the bonus. Its own
        # transaction, so a later failure does not roll the progress back and
        # leave the UI stuck at zero while the job is plainly running.
        jobs.heartbeat(db, job, done=done)
        db.commit()

    rows, findings_summary = validate_employees(
        db,
        entity,
        comps,
        employees,
        job.run_type,
        _as_date(params.get("effective_month_from")),
        _as_date(params.get("effective_month_to")),
        _as_date(params.get("as_of_date")),
        period_month=job.period_month,
        on_progress=progress,
    )

    findings_summary = apply_suppressed_rules(
        rows, _suppressed_rule_ids(db, entity.id),
        findings_summary.get("unmatched_findings"),
    )

    all_findings = [f for row in rows for f in row.get("findings", [])]
    all_findings.extend(findings_summary.get("unmatched_findings", []))

    run = finding_store.record_run(
        db,
        entity_id=entity.id,
        user_id=user.id,
        period_month=job.period_month,
        findings=all_findings,
        employee_count=len(rows),
        summary=findings_summary,
    )
    jobs.heartbeat(db, job, done=len(rows))
    return run.id


def run_once(db: Session, worker: str) -> bool:
    """Claim and run at most one job. ``False`` means the queue was empty."""
    job = jobs.claim(db, worker)
    if job is None:
        db.rollback()
        return False
    db.commit()

    job_id, entity_id = job.id, job.entity_id
    logger.info("job %s claimed by %s (entity=%s)", job_id, worker, entity_id)

    try:
        run_id = execute(db, job)
    except Exception as exc:  # noqa: BLE001 — every failure is recorded, not swallowed
        db.rollback()
        # Re-read: the rollback detached whatever state the failed attempt left.
        job = db.get(type(job), job_id)
        if job is None:
            # The register, and with it the job, was deleted while we worked.
            logger.info("job %s disappeared mid-run", job_id)
            return True
        jobs.fail(db, job, error=f"{type(exc).__name__}: {exc}")
        db.commit()
        logger.exception("job %s failed (attempt %s/%s)", job_id, job.attempts, job.max_attempts)
        return True

    jobs.succeed(db, job, run_id=run_id)
    db.commit()
    logger.info("job %s succeeded, run=%s, employees=%s", job_id, run_id, job.employee_done)
    return True


def drain(db: Session, worker: str, limit: int = 100) -> int:
    """Run queued jobs until there are none left. Returns how many ran.

    ``limit`` is a guard, not a policy: without it a job that requeues itself on
    every attempt would spin here forever instead of returning to the loop.
    """
    done = 0
    while done < limit and run_once(db, worker):
        done += 1
    return done


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------
_stop = threading.Event()


def stop() -> None:
    """Ask the loop to finish its current job and exit."""
    _stop.set()


def loop(worker: str | None = None, stop_event: threading.Event | None = None) -> None:
    """Poll for work until asked to stop.

    Every iteration gets its own session. A long-lived session would hold one
    connection open across an idle night and hand back whatever it had cached
    when work finally arrived.
    """
    worker = worker or worker_id()
    stopper = stop_event or _stop
    logger.info("validation worker %s started", worker)

    while not stopper.is_set():
        db = SessionLocal()
        try:
            worked = run_once(db, worker)
        except Exception:  # noqa: BLE001
            # run_once records job failures itself, so reaching here means the
            # queue machinery failed — most likely the database went away.
            # Backing off and retrying is better than killing the only worker.
            logger.exception("worker %s could not reach the queue", worker)
            worked = False
        finally:
            db.close()

        if not worked:
            stopper.wait(IDLE_SLEEP_SECONDS)

    logger.info("validation worker %s stopped", worker)


def start_in_thread() -> list[threading.Thread]:
    """Start the configured number of worker threads. Returns them, for tests.

    Off unless ``VALIDATION_WORKER_ENABLED`` says otherwise. A worker that
    starts by default would begin draining a queue on every deploy of every
    environment, including ones nobody is watching.
    """
    if not settings.validation_worker_enabled:
        return []

    threads: list[threading.Thread] = []
    for _ in range(max(1, settings.validation_worker_concurrency)):
        thread = threading.Thread(target=loop, name="validation-worker", daemon=True)
        thread.start()
        threads.append(thread)
    logger.info("started %d validation worker thread(s)", len(threads))
    return threads
