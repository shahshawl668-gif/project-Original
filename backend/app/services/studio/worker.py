"""
Draining Studio runs.

Runs inside the existing validation worker loop — the same thread, the same
process, the same switch (``VALIDATION_WORKER_ENABLED``) — so a deployment
that validates also imports, and there is no second worker to forget to start.
Each loop turn tries a validation job first, then a Studio run.

Housekeeping rides along at most once every ten minutes: expired idempotency
keys are deleted and retained copies of rejected records past their date are
dropped (the rejection itself, with its reason, stays with the run).
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.models import StudioRun
from app.services.studio import idempotency, imports, runs

logger = logging.getLogger("payroll.studio")

_HOUSEKEEPING_EVERY = 600.0
_last_housekeeping = 0.0


def housekeeping(db: Session, force: bool = False) -> None:
    global _last_housekeeping
    now = time.monotonic()
    if not force and now - _last_housekeeping < _HOUSEKEEPING_EVERY:
        return
    _last_housekeeping = now
    try:
        idempotency.purge_expired(db)
        runs.purge_expired_payloads(db)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("studio housekeeping failed")


def _dispatch(db: Session, run: StudioRun) -> None:
    if run.kind == "import":
        imports.process(db, run)
        return
    runs.finish(db, run, "failed", error_category="internal",
                error_message=f"No processor for runs of kind '{run.kind}'.")
    db.commit()


def run_once(db: Session, worker: str) -> bool:
    """Process one Studio run if one is waiting. True when there was work."""
    housekeeping(db)
    run = runs.claim(db, worker)
    if run is None:
        return False
    run_id = run.id
    try:
        _dispatch(db, run)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        run = db.get(StudioRun, run_id)
        if run is None:
            return True
        if run.attempts < run.max_attempts:
            # Transient until proven otherwise: back in the queue, and the
            # attempt is counted so it cannot loop forever.
            run.status = "queued"
            run.stage = "queued"
            run.error_category = "transient"
            run.error_message = f"Attempt {run.attempts} failed: {type(exc).__name__}"
            run.recommended_action = runs.RECOMMENDED["transient"]
            run.heartbeat_at = None
        else:
            runs.finish(db, run, "failed", error_category="internal",
                        error_message=f"Failed after {run.attempts} attempts: {type(exc).__name__}")
        db.commit()
        logger.exception("studio run %s failed (attempt %s/%s)", run_id, run.attempts, run.max_attempts)
    return True


def drain(db: Session, worker: str = "test-worker", limit: int = 100) -> int:
    done = 0
    while done < limit and run_once(db, worker):
        done += 1
    return done
