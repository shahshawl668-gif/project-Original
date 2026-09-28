"""
Every register upload, kept exactly as it was parsed.

``salary_registers`` holds one register per period and a re-upload replaces its
rows. That is right for reporting — a cost dashboard wants the month's current
figures — and wrong for evidence: once a corrected file replaces the first one,
nothing can say what the earlier validation actually looked at.

So each upload is also written here, once, and never changed:

* the **file's own hash**, so "is this the file we validated?" has an answer
  that does not depend on anyone's memory;
* the **rows exactly as parsed and mapped**, compressed. Not the decomposed
  register rows: those keep only what the cost model reads, and validation reads
  more — PAN, UAN, bank details, dates, payment mode. A background job that
  validated the decomposed rows would silently skip the identity checks the
  upload itself would have run. Validating this copy runs the same checks on the
  same values, every time, however many times the month is re-uploaded;
* the **mapping** that turned the file's columns into the product's.

A validation run points at the upload it validated. That pointer, plus this
row, is what makes a signed-off month reproducible after the register has been
replaced three times.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RegisterUpload(Base):
    __tablename__ = "register_uploads"
    __table_args__ = (Index("ix_register_uploads_entity_period", "entity_id", "period_month"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    # Nullable: a file uploaded before a period was chosen, or one refused for
    # missing columns, is still a fact worth keeping.
    period_month: Mapped[date | None] = mapped_column(Date)
    # The period's register as it stood after this upload, when it was stored.
    register_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("salary_registers.id", ondelete="SET NULL")
    )
    # 1 for the first upload of a period, 2 for its first correction, and so on.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False, default="regular")

    filename: Mapped[str | None] = mapped_column(String(512))
    sheet_name: Mapped[str | None] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    source_columns: Mapped[list[str] | None] = mapped_column(JSON)
    column_mapping: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    missing_required: Mapped[list[str] | None] = mapped_column(JSON)
    warnings: Mapped[list[str] | None] = mapped_column(JSON)

    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Digest of the parsed rows in canonical form. Two uploads with the same
    # rows digest validate identically even if the files differ byte-for-byte
    # (a re-saved spreadsheet, a different column order).
    rows_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # gzip(JSON(list of employee dicts)) — the rows exactly as validation reads them.
    rows_gz: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
