import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ComponentConfig(Base):
    __tablename__ = "components_config"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    component_name: Mapped[str] = mapped_column(String(100), nullable=False)
    pf_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    esic_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    pt_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    lwf_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    bonus_applicable: Mapped[bool] = mapped_column(Boolean, default=False)
    included_in_wages: Mapped[bool] = mapped_column(Boolean, default=False)
    taxable: Mapped[bool] = mapped_column(Boolean, default=False)
    tax_exemption_type: Mapped[str] = mapped_column(String(20), default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="components")
