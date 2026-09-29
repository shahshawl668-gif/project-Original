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
