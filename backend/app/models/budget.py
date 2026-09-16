"""
Approved payroll budget, and the trail of who changed it.

A budget is a *decision*, not a measurement, so it is stored with who approved
it and when. Two consequences are deliberate:

* a budget line is **scoped** — an entity-wide figure, or one per department,
  cost centre or business unit. Finance approves at whatever level it approves
  at, and the product must not force a granularity the company does not use;
* a budget is **versioned by approval**, not overwritten. A re-forecast approved
  in September does not erase what was approved in April, because the variance
  everyone argues about is against the number that was approved *then*.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# An entity-wide line carries this as its scope, so "the whole company" is a
# value in the same column rather than a null that every query has to special-case.
ENTITY_SCOPE = "entity"


class BudgetVersion(Base):
    """One approved budget: a named set of lines, with its approval recorded."""

    __tablename__ = "budget_versions"
    __table_args__ = (UniqueConstraint("entity_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    financial_year: Mapped[str | None] = mapped_column(String(9))
    # "draft" until someone with authority approves it. Only an approved version
    # is used as the comparison on a management dashboard — a draft budget
    # presented as the approved one is how a board gets misled.
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    scope_key: Mapped[str] = mapped_column(String(32), nullable=False, default=ENTITY_SCOPE)
    measure: Mapped[str] = mapped_column(String(32), nullable=False, default="ctc")
    note: Mapped[str | None] = mapped_column(Text)
    source_filename: Mapped[str | None] = mapped_column(String(512))

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by_email: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BudgetLine(Base):
    """One month, one scope, one approved number."""

    __tablename__ = "budget_lines"
    __table_args__ = (
        UniqueConstraint("version_id", "period_month", "scope_value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("budget_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # The dimension value this line budgets for, or ENTITY_SCOPE for the whole
    # entity. The dimension itself is on the version, so one version cannot mix
    # department lines with cost-centre lines and silently double-count.
    scope_value: Mapped[str] = mapped_column(String(255), nullable=False, default=ENTITY_SCOPE)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False, default=Decimal("0"))
    headcount: Mapped[int | None] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text)
    # Whatever else the uploaded row carried, kept rather than dropped so a
    # finance team's own annotations survive the round trip.
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
