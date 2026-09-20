"""
What happened, who did it, and when.

Payroll data arrives from a file someone chose to upload. Months later, when a
figure is challenged, the only useful answer is "this register was uploaded by
this person on this date, from this file, and approved by that person" — so
every upload, approval and configuration change writes a row here.

The log is append-only by construction: there is no update path and no delete
path in the service that writes it. An audit trail that can be edited is not one.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    # Kept as text as well as a foreign key: a user row can be deleted, and the
    # question "who did this" must still have an answer afterwards.
    user_email: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(128))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Set in Python, with microseconds, rather than by the database clock:
    # SQLite's now() is second-resolution, so two events written in the same
    # request would tie and the trail would order them by a random UUID.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
