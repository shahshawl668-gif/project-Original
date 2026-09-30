"""Durable history and bounded artifacts for aggregate PeopleOps Reports.

A generated file is immutable. The job keeps the exact definition version and
source references used to make it. Payroll employee detail exports must move to
object storage before this bounded database artifact is extended to them.
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReportJob(Base):
    __tablename__ = "report_jobs"
    __table_args__ = (
        Index("ix_report_jobs_claim", "state", "queued_at"),
        Index("ux_report_jobs_active_request", "entity_id", "definition_id", "requester_id",
              unique=True, postgresql_where=text("state IN ('queued','running')"),
              sqlite_where=text("state IN ('queued','running')")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    definition_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("report_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    requester_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_name: Mapped[str] = mapped_column(String(120), nullable=False)
    specification: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancel_requested: Mapped[bool] = mapped_column(default=False, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(60))
    error_message: Mapped[str | None] = mapped_column(Text)
    source_references: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    control_totals: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    record_count: Mapped[int | None] = mapped_column(Integer)
    artifact: Mapped[bytes | None] = mapped_column(LargeBinary)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    artifact_bytes: Mapped[int | None] = mapped_column(Integer)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # "xlsx" or "pdf" — the file this job makes.
    format: Mapped[str] = mapped_column(String(8), nullable=False, default="xlsx", server_default="xlsx")
    # "person" when someone pressed Generate; "schedule" when a report schedule did.
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="person", server_default="person")


class ReportSchedule(Base):
    """A saved report generated for its owner on a timetable.

    Delivery is to the owner's Generated files in the product: the platform
    sends no email. The file covers a rolling window of complete months ending
    with the month before the run, so a monthly schedule on the 5th makes last
    month's report once last month has closed.
    """

    __tablename__ = "report_schedules"
    __table_args__ = (
        Index("ux_report_schedules_owner", "definition_id", "owner_user_id", unique=True),
        Index("ix_report_schedules_due", "enabled", "next_run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    definition_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("report_definitions.id", ondelete="CASCADE"), nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    frequency: Mapped[str] = mapped_column(String(8), nullable=False)  # monthly | weekly
    day: Mapped[int] = mapped_column(Integer, nullable=False)  # 1–28, or 0 (Mon)–6 (Sun)
    hour: Mapped[int] = mapped_column(Integer, nullable=False, default=9)  # India time
    months: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    format: Mapped[str] = mapped_column(String(8), nullable=False, default="xlsx")
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())
