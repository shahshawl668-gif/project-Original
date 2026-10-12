"""
Data protection: how long a company's payroll data is kept, and the erasure of
one person's data on request.

Under the DPDP Act the client is the Data Fiduciary and this product processes
its employees' data on its behalf. Two duties land on the processor's side of
that line: keep data no longer than the purpose needs, and erase a person's
data when the fiduciary asks. Both are decisions the company makes and the
product carries out, so both are recorded here and in the company's audit
trail.

A retention policy is written per company. Without one, nothing is deleted —
and the page says so in those words, because "no policy" is not the same
claim as "a policy that has deleted nothing yet".

An erasure request is written once and never edited. It records whose data was
erased (the employee code the company gave), why, by whom, and how many rows
in each store it changed — and what it could not change, by name. It does not
record the pseudonym the data now carries: keeping that would keep the link.
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RetentionPolicy(Base):
    """One company's retention period for payroll data."""

    __tablename__ = "retention_policies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, unique=True)
    # Months of payroll periods kept, counting back from the current month.
    # None: no period set, nothing is deleted.
    payroll_months: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    set_by_email: Mapped[str | None] = mapped_column(String(255))
    set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_applied_counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class ErasureRequest(Base):
    """One person's data erased at the company's request. Written once; never edited."""

    __tablename__ = "erasure_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    requested_by_email: Mapped[str] = mapped_column(String(255), nullable=False)
    # Rows changed or removed, per store.
    counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # What still names the person, and why: [{"store", "count", "why"}].
    retained: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
