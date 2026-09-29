"""
PeopleOps Studio: machine identities, their credentials, and the record of
every integration run.

**A machine is not a person.** A service account has its own row here and a
shadow ``users`` row with ``role = "machine"`` that exists only because upload,
job and audit tables carry a ``user_id`` for authorship. That row has no
password, no organisation membership and no role, so it can never sign in and
never passes a human permission check. Everything it may do is the explicit
list of scopes and companies on the service account.

**A credential is shown once.** Only a SHA-256 of the secret is stored; the
prefix is kept in clear so a leaked key found in a log can be identified and
revoked without anyone holding the secret.

**A run is the unit of evidence.** Every import, sync, workflow execution and
webhook delivery writes one ``StudioRun`` with who started it, what it received,
what it accepted and rejected, and which versions of mapping and workflow it
used. Rejected records are kept apart, with a restricted payload and a
retention date, so they can be inspected and retried without resending what
already succeeded.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

#: The environments configuration and credentials are separated into.
ENVIRONMENTS = ("development", "test", "production")

#: What a run can be. Clear words, the same on every screen.
RUN_STATUSES = (
    "queued", "running", "completed", "partially_completed", "failed", "cancelled",
    "awaiting_approval",
)
ACTIVE_RUN_STATUSES = ("queued", "running")


class ServiceAccount(Base):
    """A machine identity inside one organisation."""

    __tablename__ = "studio_service_accounts"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_studio_sa_org_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The shadow users row (role "machine") used only for authorship columns.
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="production")
    #: Company ids this identity may act on. Never "all": each is named.
    entity_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IntegrationCredential(Base):
    """One API key of a service account. The secret itself is never stored."""

    __tablename__ = "studio_credentials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    service_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studio_service_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    #: Public, unique handle: "pol_live_<8 hex>". Enough to find and revoke.
    prefix: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    rotated_from_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    rotated_to_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdempotencyRecord(Base):
    """The stored answer to a retryable write, keyed by caller and key."""

    __tablename__ = "studio_idempotency"
    __table_args__ = (UniqueConstraint("principal", "key", name="uq_studio_idem_principal_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    principal: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class StudioRun(Base):
    """One integration run: an import, a sync, a workflow, a delivery."""

    __tablename__ = "studio_runs"
    __table_args__ = (
        Index("ix_studio_runs_entity_created", "entity_id", "created_at"),
        Index("ix_studio_runs_status", "status", "queued_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    #: import | sync | workflow | webhook_delivery | validation
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    #: employee_master | ctc | attendance | salary_register | …
    object_type: Mapped[str | None] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    stage: Mapped[str | None] = mapped_column(String(48))
    #: api | ui | schedule | workflow | webhook | retry
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="api")
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)  # user | machine
    actor_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(255), nullable=False)
    service_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    credential_prefix: Mapped[str | None] = mapped_column(String(32))
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="production")
    source_system: Mapped[str | None] = mapped_column(String(100))
    source_object: Mapped[str | None] = mapped_column(String(255))
    batch_id: Mapped[str | None] = mapped_column(String(100))
    period_month: Mapped[date | None] = mapped_column(Date)
    effective_from: Mapped[date | None] = mapped_column(Date)
    #: Mode and options the run was started with (never secrets).
    options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: received / accepted / rejected / skipped / created / updated / unchanged
    counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: mapping / workflow / script versions in force when it ran
    versions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: Staged input for asynchronous processing, gzip JSON. Cleared once done.
    payload_gz: Mapped[bytes | None] = mapped_column(LargeBinary)
    payload_sha256: Mapped[str | None] = mapped_column(String(64))
    error_category: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
    recommended_action: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    retry_of_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    #: What the run produced downstream.
    result_ref: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    validation_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    request_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    worker_id: Mapped[str | None] = mapped_column(String(100))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StudioRunRejection(Base):
    """A record a run did not accept, with why and where it came from."""

    __tablename__ = "studio_run_rejections"
    __table_args__ = (Index("ix_studio_rejections_run", "run_id", "row_number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studio_runs.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    #: 1-based position in the batch as received.
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    record_key: Mapped[str | None] = mapped_column(String(100))
    #: rejected | skipped
    disposition: Mapped[str] = mapped_column(String(16), nullable=False, default="rejected")
    code: Mapped[str] = mapped_column(String(48), nullable=False)
    field: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    #: system, object, record id — where it came from outside.
    source_ref: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: The record as received, gzip JSON. Restricted to manager and above, and
    #: cleared after ``retain_until``.
    payload_gz: Mapped[bytes | None] = mapped_column(LargeBinary)
    retain_until: Mapped[date | None] = mapped_column(Date)
    retried_in_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
