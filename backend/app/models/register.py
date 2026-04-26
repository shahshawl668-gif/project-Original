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
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SalaryRegister(Base):
    __tablename__ = "salary_registers"
    __table_args__ = (UniqueConstraint("user_id", "period_month"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    filename: Mapped[str | None] = mapped_column(String(512))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rows = relationship("SalaryRegisterRow", back_populates="register", cascade="all, delete-orphan")


class SalaryRegisterRow(Base):
    __tablename__ = "salary_register_rows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    register_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("salary_registers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    employee_id: Mapped[str] = mapped_column(String(64), nullable=False)
    employee_name: Mapped[str | None] = mapped_column(String(255))
    paid_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    lop_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    components: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    arrears: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    increment_arrear_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    register = relationship("SalaryRegister", back_populates="rows")
