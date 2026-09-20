"""
StatutoryConfig — config-driven statutory engine table.

Stores PF, ESIC and component-mapping configs as JSON so they can evolve
without schema migrations.  For PostgreSQL the column type is JSONB; for
SQLite it falls back to TEXT (SQLAlchemy JSON type handles both).

One row per entity (entity_id PK).  ConfigService reads and writes this table
via typed Pydantic schemas — callers never touch raw JSON.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StatutoryConfig(Base):
    __tablename__ = "statutory_config"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("entities.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Stored as serialised Pydantic models (JSON/JSONB).
    # ConfigService is responsible for parsing/dumping.
    pf_config:               Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    esic_config:             Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    component_mapping_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # FY-versioned income-tax parameters (slabs, rebate, surcharge, cess, …)
    # and tunable rule-engine thresholds. Nullable so existing rows patch in
    # cleanly; None is treated as "use seeded defaults" by ConfigService.
    income_tax_config:       Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    rule_thresholds_config:  Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    # Interest and damages rates used to size accumulated statutory exposure.
    exposure_config:         Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
