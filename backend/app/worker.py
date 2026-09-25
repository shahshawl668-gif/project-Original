"""Run the validation worker as its own process.

    python -m app.worker

Phase 2 of the background-jobs plan: the same ``run_once`` the API thread uses,
started from a separate Render Worker service with
``VALIDATION_WORKER_ENABLED=false`` on the API. Scale during close week, scale
back after. Nothing in the queue changes — which is what putting it in
PostgreSQL rather than the web process bought.

This entrypoint ignores ``VALIDATION_WORKER_ENABLED``. That flag exists to stop
the API container starting a worker it was not asked for; a process whose only
job is to be a worker has already answered that question by existing.
"""
from __future__ import annotations

import logging
import signal
import sys
import threading

from app.database import Base, SessionLocal, apply_column_patches, engine
from app.migrations import run_migrations
from app.services import validation_worker

logger = logging.getLogger("payroll.worker")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    # The worker can legitimately start before the API in a fresh environment,
    # so it must not assume the schema is already there.
    Base.metadata.create_all(bind=engine)
    apply_column_patches()
    run_migrations(engine)

    stopping = threading.Event()

    def handle(signum, _frame):
        # One signal asks politely; the platform's own SIGKILL is the backstop,
        # and the lease is what makes that safe.
        logger.info("signal %s received, finishing the current job", signum)
        stopping.set()
        validation_worker.stop()

    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)

    validation_worker.loop(stop_event=stopping)
    return 0


if __name__ == "__main__":
    sys.exit(main())
