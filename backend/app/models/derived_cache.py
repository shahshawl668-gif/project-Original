"""
Work the product would otherwise redo on every page load, kept with the exact
basis it was computed from.

Two things were recomputed per request and grew with headcount:

* **costing** — every register row run through the cost taxonomy (PF, ESI,
  gratuity, PT, LWF). At 8,000 employees and two months that was seconds of
  CPU for each cost page, month close and Control Centre view;
* **input digests** — whether a run is still current is decided by hashing the
  master, CTC, attendance and previous register it read, and that was redone
  every time the run page or the month's status was opened.

Neither cache is trusted on its own say-so. A stored costing names the basis it
was computed under — the configuration, the PF flags from the master, and the
code that did the arithmetic — and is used only when today's basis is the same.
A stored digest names the *revision* of its input, and every write to that input
moves the revision (services/input_revisions.py). Anything that cannot show it
still matches is recomputed, so the worst a stale entry can cost is time.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InputRevision(Base):
    """The current revision of one validation input for one company.

    ``scope`` is the entity id, or ``*`` for a change that could not be tied to
    one company (a bulk statement, a deleted user); a digest is valid only while
    both its company's revision and the ``*`` revision are unchanged.
    """

    __tablename__ = "input_revisions"

    scope: Mapped[str] = mapped_column(String(36), primary_key=True)
    input_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    token: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InputDigestCache(Base):
    """A digest of one input selection, valid for the revision it names."""

    __tablename__ = "input_digest_cache"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    input_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Which rows: the period or cut-off date the selection was made on.
    selection: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[str] = mapped_column(String(200), nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RegisterCosting(Base):
    """Every row of one stored register, costed, and the basis it was costed on.

    ``payload`` is compressed JSON: the measure keys once, then per register row
    its measures in that order and which of them the register itself reported.
    Rows are keyed by their id; a re-upload replaces a register's rows with new
    ids, so a costing that lacks a row is simply out of date.
    """

    __tablename__ = "register_costings"

    register_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("salary_registers.id", ondelete="CASCADE"), primary_key=True
    )
    basis_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
