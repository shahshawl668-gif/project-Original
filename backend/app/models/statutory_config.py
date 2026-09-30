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

from datetime import date

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, Uuid, func
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


class StatutoryConfigVersion(Base):
    """A dated change to the PF, ESIC and component-mapping configuration.

    ``statutory_config`` is the base: what applies to any month no published
    version covers. A version takes effect from the first of a month and holds
    the whole configuration from then until the next version's month. It is
    drafted, published — by someone other than its author when the organisation
    requires independence — and can be withdrawn; nothing is edited once
    published. The months it covers read it when they are validated or costed,
    so publishing one marks exactly those months as needing revalidation.

    Income tax is not here: it is already kept per financial year.
    """

    __tablename__ = "statutory_config_versions"
    __table_args__ = (Index("ix_statutory_versions_entity", "entity_id", "status", "effective_from"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")  # draft|published|withdrawn|discarded
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdraw_reason: Mapped[str | None] = mapped_column(Text)
