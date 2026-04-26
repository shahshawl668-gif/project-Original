import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StatutorySettings(Base):
    __tablename__ = "statutory_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # PF
    pf_wage_ceiling: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("15000"))
    pf_employee_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=Decimal("0.12"))
    pf_employer_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=Decimal("0.12"))
    pf_eps_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=Decimal("0.0833"))
    pf_edli_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=Decimal("0.0050"))
    pf_admin_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=Decimal("0.0050"))
    pf_restrict_to_ceiling: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ESIC
    esic_wage_ceiling: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("21000"))
    esic_employee_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=Decimal("0.0075"))
    esic_employer_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False, default=Decimal("0.0325"))
    esic_round_mode: Mapped[str] = mapped_column(String(8), nullable=False, default="up")

    # PT and LWF can apply across multiple states for one tenant.
    # Per-employee state comes from the salary register row (column "state");
    # these lists are the allowed states for the tenant and the fallback default
    # when a row has no state.
    pt_states: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    lwf_states: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
