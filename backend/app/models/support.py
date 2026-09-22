"""
Break-glass support access.

A platform administrator deliberately cannot read a client's payroll: entity
access is decided by organization membership, which never consults the platform
role. That is the right default — a standing developer login over every
client's salary, PAN and bank data is the most attractive single target in the
system — and it leaves no way in when a client reports a bug they cannot
reproduce for you.

This is that way in, built so that using it is never quiet.

**Time-boxed.** A grant carries an expiry and dies on its own. Nothing here
depends on someone remembering to close a session.

**Reason-required.** A free-text reason is mandatory and stored. "Investigating
ticket 412" is an answer; an empty box is not.

**Read-only and masked, always.** Not flags — columns, recorded per grant, so a
later change of policy cannot rewrite what a past session was allowed to see.
Almost no bug lives in an individual salary; they live in configuration,
findings and totals, which masking leaves entirely legible.

**Visible to the client.** Every grant, and every use of one, writes to the
organization's own audit trail. The client can revoke instantly, and can
require approval or refuse support access altogether.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# What a client allows. Stored on the organization.
SUPPORT_POLICIES = ("break_glass", "approval_required", "disabled")

# "expired" is not stored — it is derived from ``expires_at``, so a grant that
# lapsed overnight does not need a sweeper to have run to stop working.
GRANT_STATES = ("pending", "active", "ended", "revoked")

DEFAULT_MINUTES = 60
MAX_MINUTES = 480  # eight hours; longer is a conversation, not an incident


class SupportAccessGrant(Base):
    """One episode of platform staff being able to read one client's data."""

    __tablename__ = "support_access_grants"
    __table_args__ = (
        Index("ix_support_grants_org_state", "org_id", "state"),
        Index("ix_support_grants_user_state", "admin_user_id", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Kept as text as well: the account may be deleted, and "who looked at our
    # payroll in March" must still have an answer afterwards.
    admin_email: Mapped[str | None] = mapped_column(String(255))

    reason: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    # The policy in force when this grant was made, copied rather than joined.
    # A client who switches to approval_required next month has not changed what
    # this grant was.
    policy_at_grant: Mapped[str] = mapped_column(String(24), nullable=False, default="break_glass")

    # Both are always true today. Stored per grant so that if the product ever
    # gains a wider mode, the record of what this session could see stays true.
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    identity_masked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    approved_by_email: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Who closed it, and whether they were the client revoking or the engineer
    # finishing — different facts, and the client cares which.
    ended_by_email: Mapped[str | None] = mapped_column(String(255))
    ended_reason: Mapped[str | None] = mapped_column(String(255))

    # Bumped on each request that used this grant, so a session that was opened
    # and never used is distinguishable from one that read the whole book.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    use_count: Mapped[int] = mapped_column(nullable=False, default=0)
