"""
Persisted findings and their lifecycle.

Findings were previously computed, returned, and forgotten. That works for a
one-off audit and fails as a monthly habit: the same forty legitimate exceptions
come back every month, HR re-explains each one, and by month three nobody reads
the report.

So a finding gets an identity that outlives the run. ``fingerprint`` is stable
across periods — same entity, same employee, same rule, same component — which
is what lets an explanation given once in April still apply in May, and what
makes "this has now recurred for six months" a fact the system knows.

One distinction is deliberate and load-bearing: **waiving a finding removes it
from the worklist, not from the exposure.** An accepted risk is still a risk. A
tool that lets a number be silenced is a tool that will eventually be blamed for
the notice nobody saw coming.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Lifecycle states for a fingerprint.
FINDING_STATES = ("open", "acknowledged", "waived", "resolved")


class ValidationRun(Base):
    """One validation of one period, and the totals it produced."""

    __tablename__ = "validation_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    register_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("salary_registers.id", ondelete="SET NULL")
    )

    employee_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_findings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    critical_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Gross exposure, before any waiver is applied — see the module note.
    total_financial_impact: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )
    # Exposure that remains on the worklist once waivers are honoured.
    open_financial_impact: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )

    summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    findings = relationship("FindingRecord", back_populates="run", cascade="all, delete-orphan")


class FindingRecord(Base):
    """One finding, as observed in one run."""

    __tablename__ = "finding_records"
    __table_args__ = (
        Index("ix_finding_records_entity_period", "entity_id", "period_month"),
        Index("ix_finding_records_fingerprint", "entity_id", "fingerprint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("validation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False)

    # Stable across periods: entity + employee + rule + component.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    employee_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    employee_name: Mapped[str | None] = mapped_column(String(255))
    rule_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    component: Mapped[str | None] = mapped_column(String(255))

    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_value: Mapped[str | None] = mapped_column(String(255))
    actual_value: Mapped[str | None] = mapped_column(String(255))
    difference: Mapped[str | None] = mapped_column(String(255))
    financial_impact: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    suggested_fix: Mapped[str | None] = mapped_column(Text)

    # Denormalised from FindingState at write time so a historical run can be
    # read back exactly as it was presented, without re-deriving lifecycle.
    was_waived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run = relationship("ValidationRun", back_populates="findings")


class FindingState(Base):
    """
    The lifecycle of one fingerprint — the part a human curates.

    Rows are created on first sighting and updated by runs and by people.
    Nothing here changes what a rule computes; it changes what the worklist
    shows and what the audit trail records about a decision.
    """

    __tablename__ = "finding_states"
    __table_args__ = (UniqueConstraint("entity_id", "fingerprint"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    # Carried for display and filtering without joining a run.
    employee_id: Mapped[str] = mapped_column(String(64), nullable=False)
    employee_name: Mapped[str | None] = mapped_column(String(255))
    rule_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    component: Mapped[str | None] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(16), nullable=False)

    state: Mapped[str] = mapped_column(String(16), nullable=False, default="open")

    first_seen_period: Mapped[date] = mapped_column(Date, nullable=False)
    last_seen_period: Mapped[date] = mapped_column(Date, nullable=False)
    # How many distinct periods this has been observed in. A finding in its
    # first month is a mistake; one in its ninth is a process problem.
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_financial_impact: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )
    # Period in which it stopped appearing, if it has.
    resolved_period: Mapped[date | None] = mapped_column(Date)

    # --- human decision -----------------------------------------------------
    note: Mapped[str | None] = mapped_column(Text)
    waiver_reason: Mapped[str | None] = mapped_column(Text)
    # Waivers expire by default so that "accepted once" does not become
    # "invisible forever" across a change of staff or of law.
    waived_until: Mapped[date | None] = mapped_column(Date)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    events = relationship(
        "FindingStateEvent", back_populates="state", cascade="all, delete-orphan"
    )

    def is_waived_for(self, period: date) -> bool:
        """Whether a waiver covers ``period``, honouring its expiry."""
        if self.state != "waived":
            return False
        if self.waived_until is None:
            return True
        return period <= self.waived_until


class FindingStateEvent(Base):
    """
    An append-only record of every lifecycle decision.

    This is the audit trail: who accepted what, when, and on what stated
    grounds. It is never updated or deleted, because its whole value is that it
    cannot be tidied up after the fact.
    """

    __tablename__ = "finding_state_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    state_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("finding_states.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_state: Mapped[str | None] = mapped_column(String(16))
    to_state: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    waived_until: Mapped[date | None] = mapped_column(Date)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    state = relationship("FindingState", back_populates="events")
