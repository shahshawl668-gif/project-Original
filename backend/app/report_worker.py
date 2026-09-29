"""Run PeopleOps report jobs in a dedicated process when provisioned.

    python -m app.report_worker

Set REPORT_WORKER_ENABLED=false on API replicas when a dedicated worker service
is available. Both modes use the same PostgreSQL queue.
"""
from __future__ import annotations

import logging
import signal
import threading

from app.database import Base, apply_column_patches, engine
from app.migrations import run_migrations
from app.services import report_jobs

logger = logging.getLogger("payroll.report_worker")


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    Base.metadata.create_all(bind=engine)
    apply_column_patches()
    run_migrations(engine)
    stopping = threading.Event()

    def handle(signum, _frame):
        logger.info("signal %s received", signum)
        stopping.set()

    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)
    while not stopping.is_set():
        try:
            if not report_jobs.run_once():
                report_jobs.cleanup_expired()
                stopping.wait(2)
        except Exception:
            logger.exception("Report worker failed")
            stopping.wait(5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
