"""
Minimum wage rates.

Rates vary by state, by zone within a state, by scheduled employment, and by
skill category — and the VDA component is revised twice a year. No shipped
dataset stays correct, so these are **tenant-maintained**: a practice loads and
maintains the schedules its clients are covered by, the same way it already does.

What the product owes the user in return is that a missing rate is *visible*.
An employee whose applicable rate is not on file produces a finding saying so,
because "no rate configured" and "paid correctly" must never look alike.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Skill categories used across most state schedules.
SKILL_CATEGORIES = ("unskilled", "semi-skilled", "skilled", "highly-skilled")

# A rate row with this scheduled employment applies to any employment for which
# no more specific row exists.
ANY_SCHEDULE = "*"
ANY_ZONE = "*"


class MinimumWageRate(Base):
    """
    One applicable rate, effective-dated.

    Rates are held per entity rather than globally: two clients of the same
    practice in the same state can be covered by different scheduled
    employments, and a shared table would force one of them to be wrong.
    """

    __tablename__ = "minimum_wage_rates"
    __table_args__ = (
        Index("ix_min_wage_lookup", "entity_id", "state", "skill_category", "effective_from"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )

    state: Mapped[str] = mapped_column(String(100), nullable=False)
    # Zone / area classification, where the state uses one. "*" matches any.
    zone: Mapped[str] = mapped_column(String(64), nullable=False, default=ANY_ZONE)
    # Scheduled employment (the industry schedule). "*" is the fallback row.
    scheduled_employment: Mapped[str] = mapped_column(String(255), nullable=False, default=ANY_SCHEDULE)
    skill_category: Mapped[str] = mapped_column(String(64), nullable=False)

    # Held apart because the VDA half is what gets revised, and because some
    # schedules express the floor as basic + VDA rather than a single figure.
    basic_per_month: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    vda_per_month: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))

    # Days used to convert a monthly floor to a daily one. 26 is the usual
    # basis, but some schedules and some states differ.
    working_days_basis: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=Decimal("26")
    )

    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)

    # Where this figure came from — a notification number, a circular, a URL.
    # Without it a rate is an assertion; with it, it is evidence.
    source_reference: Mapped[str | None] = mapped_column(String(512))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def total_per_month(self) -> Decimal:
        return (self.basic_per_month or Decimal("0")) + (self.vda_per_month or Decimal("0"))
