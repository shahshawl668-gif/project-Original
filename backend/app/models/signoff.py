"""
Period sign-off.

At some point a person says "this month is fine, pay it" — and that moment is
the one nobody can evidence afterwards. Six months later, in a due diligence or
an inspection, the questions are: who approved it, what did they see when they
approved it, and what was still outstanding that they accepted.

So a sign-off freezes a snapshot: the counts, the exposure, and every finding
that was open at the moment of signing, with the reasons attached. The snapshot
is written once and never recomputed, because a record that changes when the
underlying data changes is not a record.

Reopening is allowed — corrections happen — but it is an event, not an erasure.
The superseded snapshot stays.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
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

SIGNOFF_STATES = ("draft", "pending_approval", "signed", "reopened")


class PeriodSignOff(Base):
    __tablename__ = "period_signoffs"
    __table_args__ = (UniqueConstraint("entity_id", "period_month"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")

    prepared_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    signed_by_email: Mapped[str | None] = mapped_column(String(255))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # What the signer was looking at. Frozen at signing; never recomputed.
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Digest of the snapshot, so a later reader can tell whether the record
    # they are holding is the one that was signed.
    snapshot_digest: Mapped[str | None] = mapped_column(String(64))

    employee_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_findings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_exposure: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=Decimal("0")
    )

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    events = relationship("SignOffEvent", back_populates="signoff", cascade="all, delete-orphan")


class SignOffEvent(Base):
    """Append-only history of a period's approval, including reopenings."""

    __tablename__ = "signoff_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    signoff_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("period_signoffs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    # The snapshot as it stood when this event occurred, so a reopening does
    # not destroy what the previous signer saw.
    snapshot_digest: Mapped[str | None] = mapped_column(String(64))
    superseded_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    signoff = relationship("PeriodSignOff", back_populates="events")
