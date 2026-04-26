import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PtSlab(Base):
    __tablename__ = "pt_slabs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    state: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    slab_min: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    slab_max: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LwfRate(Base):
    __tablename__ = "lwf_rates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    state: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    wage_band_min: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    wage_band_max: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    employee_rate: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    employer_rate: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
