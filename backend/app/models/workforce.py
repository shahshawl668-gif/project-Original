"""
Employee master and attendance — the payroll *inputs*.

The salary register is what payroll produced. On its own it only supports
internal-consistency checks: a wrong input processed consistently every month
looks perfectly valid. These two datasets are what make independent judgement
possible —

* the **master** says who the person is and whether they should have been paid
  at all (joined yet? already exited? which state, which PF status?);
* **attendance** says how much they should have been paid for.

Master records are effective-dated, following the same shape as ``CtcRecord``:
each upload writes a new row when something changed, so history is preserved
and a March validation reads March's version of the truth rather than today's.
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
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EmployeeMasterUpload(Base):
    __tablename__ = "employee_master_uploads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    filename: Mapped[str | None] = mapped_column(String(512))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    records = relationship("EmployeeRecord", back_populates="upload", cascade="all, delete-orphan")


class EmployeeRecord(Base):
    """One version of one employee's master data, valid from ``effective_from``."""

    __tablename__ = "employee_records"
    __table_args__ = (UniqueConstraint("entity_id", "employee_id", "effective_from"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    upload_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employee_master_uploads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)

    employee_name: Mapped[str | None] = mapped_column(String(255))
    # Service dates — these decide "paid before joining" / "paid after exit",
    # and make gratuity service-years checkable rather than assumed.
    date_of_joining: Mapped[date | None] = mapped_column(Date)
    date_of_exit: Mapped[date | None] = mapped_column(Date)
    date_of_birth: Mapped[date | None] = mapped_column(Date)

    gender: Mapped[str | None] = mapped_column(String(16))
    # Where the person works, which drives PT and LWF — not where the entity is
    # registered. A Karnataka employee of a Maharashtra company owes Karnataka PT.
    work_state: Mapped[str | None] = mapped_column(String(100))
    work_location: Mapped[str | None] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(255))
    designation: Mapped[str | None] = mapped_column(String(255))
    grade: Mapped[str | None] = mapped_column(String(64))
    # permanent | contract | apprentice | intern | consultant — affects which
    # statutes apply at all.
    employment_type: Mapped[str | None] = mapped_column(String(64))
    # Minimum-wage classification: unskilled | semi-skilled | skilled | highly-skilled.
    skill_category: Mapped[str | None] = mapped_column(String(64))

    # Statutory identifiers, validated against their own check rules.
    pan: Mapped[str | None] = mapped_column(String(16))
    aadhaar: Mapped[str | None] = mapped_column(String(16))
    uan: Mapped[str | None] = mapped_column(String(16))
    pf_number: Mapped[str | None] = mapped_column(String(64))
    esic_ip_number: Mapped[str | None] = mapped_column(String(32))
    bank_account: Mapped[str | None] = mapped_column(String(32))
    ifsc: Mapped[str | None] = mapped_column(String(16))

    # Anything the client's own master carries that this schema doesn't name.
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    upload = relationship("EmployeeMasterUpload", back_populates="records")


class AttendanceRegister(Base):
    __tablename__ = "attendance_registers"
    __table_args__ = (UniqueConstraint("entity_id", "period_month"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    filename: Mapped[str | None] = mapped_column(String(512))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rows = relationship("AttendanceRow", back_populates="register", cascade="all, delete-orphan")


class AttendanceRow(Base):
    """One employee's attendance for one month, as the client's system recorded it."""

    __tablename__ = "attendance_rows"
    __table_args__ = (UniqueConstraint("register_id", "employee_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    register_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("attendance_registers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    employee_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    employee_name: Mapped[str | None] = mapped_column(String(255))

    calendar_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    present_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    paid_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    lop_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    paid_leave_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    weekly_off_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    holiday_days: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    overtime_hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))

    extra: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    register = relationship("AttendanceRegister", back_populates="rows")
