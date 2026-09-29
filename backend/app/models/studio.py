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


# ---------------------------------------------------------------------------
# Phase 2: destinations, connections, mappings
# ---------------------------------------------------------------------------
class StudioAllowedHost(Base):
    """A host an organisation's connections and webhooks may reach."""

    __tablename__ = "studio_allowed_hosts"
    __table_args__ = (UniqueConstraint("org_id", "host", name="uq_studio_host_org"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    added_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StudioConnection(Base):
    """An external system one company exchanges data with."""

    __tablename__ = "studio_connections"
    __table_args__ = (UniqueConstraint("entity_id", "environment", "name", name="uq_studio_conn_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    #: hrms | attendance | finance | payroll | file_transfer | other
    system_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="hrms")
    #: rest (generic REST connector) | file (uploads through Studio)
    provider: Mapped[str] = mapped_column(String(24), nullable=False, default="rest")
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="production")
    base_url: Mapped[str | None] = mapped_column(String(1000))
    #: none | api_key_header | bearer | basic | oauth2_client_credentials | oauth2_authorization_code
    auth_method: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    #: Non-secret settings: header name, token URL, client id, scopes, headers.
    auth_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: Fernet ciphertext of the secret values; never returned.
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    secret_hint: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    secret_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The external system is the source of truth for the fields it sends.
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="inbound")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    health: Mapped[str] = mapped_column(String(16), nullable=False, default="untested")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_result: Mapped[dict | None] = mapped_column(JSON)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StudioStream(Base):
    """One source object a connection syncs: where it is, how to page, how to map."""

    __tablename__ = "studio_streams"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studio_connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    #: employee_master | ctc | attendance | salary_register
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    #: Dotted path to the list of records in each response ("" = the body is the list).
    records_path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    #: none | page | offset | cursor
    pagination: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: full | incremental
    sync_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="full")
    watermark_field: Mapped[str | None] = mapped_column(String(100))
    watermark_param: Mapped[str | None] = mapped_column(String(100))
    #: The last committed position: {"watermark": "...", "run_id": "..."}.
    checkpoint: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: Import options: mode, effective_from / period rules, deletion policy.
    import_options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    mapping_key: Mapped[str | None] = mapped_column(String(100))
    #: A pinned mapping version, or null for "the version in force".
    mapping_version: Mapped[int | None] = mapped_column(Integer)
    #: {"every": "hour|day|week", "at": "02:30", "weekday": 0, "timezone": "Asia/Kolkata"} or {}
    schedule: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    max_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StudioMapping(Base):
    """One version of a mapping profile: external fields → product fields."""

    __tablename__ = "studio_mappings"
    __table_args__ = (UniqueConstraint("entity_id", "key", "version", name="uq_studio_mapping_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Stable identifier across versions, e.g. "hrms-employees".
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: draft | published | retired
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    spec: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    effective_from: Mapped[date | None] = mapped_column(Date)
    change_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    published_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StudioOAuthState(Base):
    """A pending OAuth authorisation: state and PKCE verifier, single use, short-lived."""

    __tablename__ = "studio_oauth_states"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studio_connections.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    verifier_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Phase 2b: events, webhooks
# ---------------------------------------------------------------------------
class StudioEvent(Base):
    """
    The outbox. One row per business event, written in the same transaction as
    the change it announces — so the change and its event commit together or
    not at all. Fanned out to webhook deliveries by the worker afterwards.
    """

    __tablename__ = "studio_events"
    __table_args__ = (Index("ix_studio_events_pending", "dispatched_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="2026-10-01")
    #: Identifiers and states only — never pay, never identity data.
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    #: What caused it (a workflow run, a depth), so automation cannot loop.
    causation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Only these webhook ids receive it (a test event); empty = every subscriber.
    only_webhook_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StudioWebhook(Base):
    """An outbound subscription: these events, to this URL, signed with this secret."""

    __tablename__ = "studio_webhooks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    payload_version: Mapped[str] = mapped_column(String(16), nullable=False, default="2026-10-01")
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="production")
    #: {"current": "...", "previous": "...", "previous_until": iso} sealed.
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    secret_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_delivery_status: Mapped[str | None] = mapped_column(String(16))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StudioDelivery(Base):
    """One attempt series to deliver one event to one webhook."""

    __tablename__ = "studio_deliveries"
    __table_args__ = (Index("ix_studio_deliveries_due", "status", "next_attempt_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    webhook_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studio_webhooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("studio_events.id", ondelete="CASCADE"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    #: pending | delivered | failed (in the failed queue after the last attempt)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_response_ms: Mapped[int | None] = mapped_column(Integer)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replay_of_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    replayed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StudioInboundEndpoint(Base):
    """A signed URL another system pushes records to."""

    __tablename__ = "studio_inbound_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The machine identity its runs are attributed to (users.role = machine).
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    #: Routing token in the URL. Not a secret on its own: every call is signed.
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    #: {"type": "import", "object_type": ..., "mapping_key": ..., "options": {...}}
    action: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="production")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StudioInboundReceipt(Base):
    """Every call an inbound endpoint accepted, keyed by the sender's event id."""

    __tablename__ = "studio_inbound_receipts"
    __table_args__ = (UniqueConstraint("endpoint_id", "event_id", name="uq_studio_receipt_event"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("studio_inbound_endpoints.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
