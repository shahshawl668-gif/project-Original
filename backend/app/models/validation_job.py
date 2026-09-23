"""
One queued validation, and everything needed to run it without the caller.

Validation used to happen inside the HTTP request. That is fine for ten
employees and a gateway timeout for five thousand, and a larger server does not
change it — the request still times out. This table is the handover point: the
API records what should be validated, and a worker does it.

**The job references the register; it does not carry it.** The rows are already
stored by the upload. Carrying them again would mean a job row of tens of
megabytes, a retry that needs a payload nobody kept, and validation running
against whatever a client posted rather than against what was recorded.

**Results are not stored here.** On success the job points at the
``ValidationRun`` the existing code already writes. Two copies of the findings
would be two truths, and the register of findings is the one that counts.

**The lease is what makes a crash survivable.** A worker renews ``heartbeat_at``
as it goes; if it dies — a deploy, an OOM — the lease goes stale and another
worker reclaims the job. Without that, a deploy during close week loses a
client's month with no record it ever started.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Terminal states are final. A job that failed is never quietly retried later —
# someone looks at it and decides.
JOB_STATES = ("queued", "running", "succeeded", "failed", "cancelled")
ACTIVE_STATES = ("queued", "running")
TERMINAL_STATES = ("succeeded", "failed", "cancelled")

DEFAULT_MAX_ATTEMPTS = 3

# How long a worker may go silent before its job is considered abandoned. Long
# enough that a slow chunk is not mistaken for a death, short enough that a
# deploy does not strand a job for the rest of the close.
LEASE_SECONDS = 120

# Employees per commit. Each commit publishes progress, renews the lease and
# bounds the transaction — one transaction spanning ten thousand employees
# would hold locks for minutes and bloat the write-ahead log.
CHUNK_SIZE = 200

# The predicate both partial indexes share. Written as SQL rather than as a
# mapped expression because __table_args__ is evaluated before the class
# exists, so there is no ValidationJob.state to refer to yet.
_ACTIVE = text("state IN ('queued', 'running')")


class ValidationJob(Base):
    __tablename__ = "validation_jobs"
    __table_args__ = (
        # The claim query orders queued work by age and also sweeps running jobs
        # whose lease has expired, so both states belong in the index.
        Index(
            "ix_validation_jobs_claimable",
            "state",
            "queued_at",
            postgresql_where=_ACTIVE,
            sqlite_where=_ACTIVE,
        ),
        # A double-click must not validate the month twice. Partial, so the
        # constraint applies to live work only — a period may be validated again
        # once the previous run has finished.
        Index(
            "ux_validation_jobs_active",
            "entity_id",
            "period_month",
            unique=True,
            postgresql_where=_ACTIVE,
            sqlite_where=_ACTIVE,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable so a job survives the register being replaced mid-flight; the
    # worker treats a missing register as a reason to stop, not to crash.
    register_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("salary_registers.id", ondelete="CASCADE"), index=True
    )

    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False, default="regular")
    # effective_month_from / effective_month_to / as_of_date — the rest of what
    # the endpoint took, kept together rather than as four nullable columns.
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    employee_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    employee_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # The handover: where the findings actually live once this succeeds.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("validation_runs.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(Text)

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_MAX_ATTEMPTS
    )

    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(64))
