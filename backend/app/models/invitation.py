"""
Invitations to join an organization.

Before this, an organization could only ever have the one member that signup
created. Adding a second person meant an INSERT by whoever had the database
password — which is not a product, and leaves no record of who granted access
to a month of salary data.

Three decisions here are security decisions rather than schema ones.

**Only a hash of the token is stored.** The raw token is returned exactly once,
at creation, and is never retrievable afterwards. A database that leaks must not
hand the reader a set of working invitations into other people's payroll — the
same reason passwords are not stored either.

**The invited email is part of acceptance.** A token alone is not enough: the
account accepting must be, or become, that address. A link forwarded to the
wrong person, or pulled out of a mailbox, is then worth nothing on its own.

**Invitations expire.** An unaccepted invitation is an outstanding key to
someone's payroll, and one that sat in an inbox for a year is not a key anybody
still intends to exist.
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# An invitation is one of these at any moment. "expired" is not stored — it is
# derived from ``expires_at``, because a row that went stale while nobody was
# looking should not need a sweeper to tell the truth about itself.
INVITATION_STATES = ("pending", "accepted", "revoked")

# How long an unaccepted invitation stays usable.
DEFAULT_EXPIRY_DAYS = 7


class OrgInvitation(Base):
    """One outstanding offer of a seat in an organization."""

    __tablename__ = "org_invitations"
    __table_args__ = (
        # Finding the invitation for a presented token is the hot path, and it
        # must not degrade into a table scan as invitations accumulate.
        Index("ix_org_invitations_token_hash", "token_hash"),
        Index("ix_org_invitations_org_email", "org_id", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Stored lower-cased and trimmed, because that is how it will be compared
    # at acceptance and how the recipient will type it.
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")

    # SHA-256 of the token. The token itself is shown once and never stored.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Entity ids this member will be narrowed to on acceptance. Empty means the
    # whole organization, matching how EntityAccess already reads.
    entity_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)

    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    note: Mapped[str | None] = mapped_column(String(500))

    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    invited_by_email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_email: Mapped[str | None] = mapped_column(String(255))
