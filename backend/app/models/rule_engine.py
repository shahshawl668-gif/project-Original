import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Formula(Base):
    """User-authored PF / ESIC formula. Each save creates a new version."""

    __tablename__ = "rule_formulas"
    __table_args__ = (UniqueConstraint("user_id", "rule_type", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_type: Mapped[str] = mapped_column(String(16), nullable=False)  # PF | ESIC
    name: Mapped[str | None] = mapped_column(String(120))
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SlabRule(Base):
    """Tenant-managed PT / LWF slab. Replaces seeded reference data when present."""

    __tablename__ = "slab_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(16), nullable=False)  # PT | LWF
    min_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    max_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # For PT: employee deduction. For LWF: employee contribution.
    deduction_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # LWF only: employer contribution per period (NULL/0 for PT rows).
    employer_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    frequency: Mapped[str] = mapped_column(String(16), nullable=False, default="monthly")
    # Gender filter: "ALL" | "MALE" | "FEMALE". States like Maharashtra publish
    # different slabs by gender; "ALL" means slab applies regardless of gender.
    gender: Mapped[str] = mapped_column(String(8), nullable=False, default="ALL")
    # Optional list of month numbers (1-12) the slab applies to. NULL / empty
    # means "every month". Used for Feb-only top-up rows in Maharashtra,
    # Karnataka, etc. that round annual PT up to the legal cap.
    applicable_months: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
