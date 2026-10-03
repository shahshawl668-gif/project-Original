"""
Disbursement validation: a company's settings, each check of a salary payment
file, and the approval of its release.

What is kept, and for how long, is deliberate:

* the **report** — verdict, findings, bridge, settings and the fingerprint of
  every input — is the record of what was checked, and stays with the run;
* the **clean file** and the **paid list** (employee, amount, account, IFSC of
  each payment in the clean file) carry bank details in full. They are kept for
  ``disbursement_file_retention_days`` and then cleared; the run keeps their
  fingerprints. The paid list is what lets next month's check compare against
  this month without uploading it again.

The uploaded inputs themselves are not stored: only their names, row counts
and SHA-256.

An approval is written once and never edited. Nothing here pays anyone or
sends a file anywhere.
"""
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DisbursementSettings(Base):
    """One company's thresholds, severities, chosen layout, and any layouts of its own."""

    __tablename__ = "disbursement_settings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, unique=True)
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False, default="generic")
    template_key: Mapped[str | None] = mapped_column(String(64))
    # Overrides of config.DEFAULTS — only what the company changed.
    overrides: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    custom_profiles: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    custom_templates: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_by_email: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DisbursementRun(Base):
    """One check of one payment file."""

    __tablename__ = "disbursement_runs"
    __table_args__ = (Index("ix_disbursement_runs_entity_period", "entity_id", "period_month", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    value_date: Mapped[date | None] = mapped_column(Date)
    verdict: Mapped[str] = mapped_column(String(24), nullable=False)
    # "checked" until approved; "approved" once; never back.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="checked")
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    bank_filename: Mapped[str | None] = mapped_column(String(255))
    # The headline figures, for the history list without opening the report.
    totals: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    rule_status: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    report_gz: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    clean_file: Mapped[bytes | None] = mapped_column(LargeBinary)
    clean_filename: Mapped[str | None] = mapped_column(String(255))
    clean_sha256: Mapped[str | None] = mapped_column(String(64))
    clean_bytes: Mapped[int | None] = mapped_column(Integer)
    paid_gz: Mapped[bytes | None] = mapped_column(LargeBinary)
    files_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    files_cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    run_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    run_by_email: Mapped[str] = mapped_column(String(255), nullable=False)
    # Set here, to the microsecond: two checks in the same second must still have an order.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC),
                                                 server_default=func.now())


class DisbursementApproval(Base):
    """A person's approval to release one clean file. Written once; never edited."""

    __tablename__ = "disbursement_approvals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("disbursement_runs.id", ondelete="CASCADE"), nullable=False, unique=True)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    approver_email: Mapped[str] = mapped_column(String(255), nullable=False)
    approver_name: Mapped[str] = mapped_column(String(120), nullable=False)
    approver_role: Mapped[str | None] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    verdict: Mapped[str] = mapped_column(String(24), nullable=False)
    release_amount: Mapped[str] = mapped_column(String(32), nullable=False)
    release_employees: Mapped[int] = mapped_column(Integer, nullable=False)
    acknowledged: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    independent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    independence_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
