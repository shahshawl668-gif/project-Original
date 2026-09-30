"""
Security events: sign-ins, lockouts, session revocations, MFA changes.

Kept apart from the client audit trail (``audit_events``) on purpose. A failed
sign-in for an address that has no account belongs to no company, and the
platform team needs to read these without being granted any client's trail.
Where an event concerns a client session it is *also* written to that client's
trail by the code that raises it.

What is never written here: a password, a token, a one-time code, a recovery
code, or any payroll figure. ``subject`` is the sign-in identifier as typed,
lower-cased, because an attack on an account is investigated by that name.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True)
    # login | platform_login | mfa | refresh | password_reset | sessions_revoked | mfa_enrolled | ...
    kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    # success | failure | blocked | detected | changed
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    # No foreign key: the record of an attack on an account outlives the account.
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    subject: Mapped[str | None] = mapped_column(String(255), index=True)
    # Unverified: whatever the nearest proxy reported. Useful for correlation,
    # never proof of origin.
    client_ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class LoginThrottle(Base):
    """Failed sign-ins per identifier, shared by every API process through the database."""

    __tablename__ = "login_throttles"

    key: Mapped[str] = mapped_column(String(300), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
