"""
Organizations, entities and membership.

The unit of payroll validation is an **Entity** — one legal employer with its own
PF/ESIC codes, its own statutory configuration and its own monthly registers.

An **Organization** owns entities:

* a *practice* (payroll bureau, CA firm, consulting outfit) has many entities,
  one per client company;
* an *enterprise* is simply an organization that happens to have one entity —
  or several, when the group runs multiple legal employers.

Modelling both as the same shape means an enterprise never has to migrate when
it acquires a second entity, and a practice never has to bolt client separation
on afterwards. Row-level data is scoped by ``entity_id``; ``user_id`` survives on
those tables as authorship provenance, not as the access boundary.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Organization roles, widest first. Used for ordering comparisons, so keep ranked.
ORG_ROLES = ("owner", "manager", "analyst", "viewer")
ORG_ROLE_RANK = {role: idx for idx, role in enumerate(ORG_ROLES)}


class Organization(Base):
    """The account boundary — a practice or a single enterprise."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # practice | enterprise — affects defaults and UI copy, never access control.
    org_type: Mapped[str] = mapped_column(String(32), nullable=False, default="enterprise")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    entities = relationship("Entity", back_populates="org", cascade="all, delete-orphan")
    memberships = relationship("OrgMembership", back_populates="org", cascade="all, delete-orphan")


class Entity(Base):
    """A legal employer whose payroll is validated — the data scope for everything."""

    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("org_id", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    # Short human handle used in exports and the entity switcher, e.g. "ACME-MH".
    code: Mapped[str] = mapped_column(String(64), nullable=False)

    # Statutory registrations — these drive exposure reporting and evidence packs.
    pf_establishment_code: Mapped[str | None] = mapped_column(String(64))
    esic_employer_code: Mapped[str | None] = mapped_column(String(64))
    tan: Mapped[str | None] = mapped_column(String(16))
    pan: Mapped[str | None] = mapped_column(String(16))
    cin: Mapped[str | None] = mapped_column(String(32))
    # Registered state — the fallback for PT/LWF when a row carries no work state.
    primary_state: Mapped[str | None] = mapped_column(String(100))

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    org = relationship("Organization", back_populates="entities")


class OrgMembership(Base):
    """A user's seat in an organization, carrying their role across all entities."""

    __tablename__ = "org_memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    org = relationship("Organization", back_populates="memberships")


class EntityAccess(Base):
    """
    Narrows a member to specific entities.

    A member with **no** rows here sees every entity in the org — the common case
    for an enterprise, and for a practice's partners. Rows are added when a
    practice assigns an analyst to a named subset of its client book.
    """

    __tablename__ = "entity_access"
    __table_args__ = (UniqueConstraint("user_id", "entity_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
