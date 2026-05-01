"""Tenant-level rule toggles — suppress findings by rule_id in validation output."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TenantRulePreference(Base):
    """When suppressed=True, findings with matching rule_id are hidden for this tenant."""

    __tablename__ = "tenant_rule_preferences"
    __table_args__ = (UniqueConstraint("user_id", "rule_id", name="uq_tenant_rule"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[str] = mapped_column(String(32), nullable=False)
    suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
