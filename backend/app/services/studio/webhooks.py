"""
Webhooks: signed events out, signed records in.

**Delivery is at least once.** Each event is delivered to each subscribed
webhook until it answers 2xx, retried with backoff (1 min, 5 min, 30 min, 2 h,
6 h, 12 h, 24 h …) up to the webhook's ``max_attempts``; after the last it
moves to the failed queue, where a person can replay it. A delivery that
succeeded but whose answer was lost will be sent again, and a replay sends the
same event again — so **consumers must de-duplicate on the event id**
(``X-PeopleOpsLab-Event-Id``, also ``id`` in the body). Exactly-once delivery
is not offered, because it cannot honestly be promised over HTTP.

**Signatures.** ``X-PeopleOpsLab-Signature: t=<unix seconds>,v1=<hex>`` where
``hex = HMAC-SHA256(secret, "<t>.<raw body>")``. During a secret rotation the
header carries a ``v1`` for the old secret too, until the overlap ends.
Consumers reject a timestamp more than five minutes from their clock.

**Inbound** endpoints verify the same scheme with their own secret, refuse
stale timestamps, and record each sender event id once: a second call with the
same id is answered as a duplicate and starts nothing.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets as pysecrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Entity,
    StudioDelivery,
    StudioEvent,
    StudioInboundEndpoint,
    StudioInboundReceipt,
    StudioWebhook,
    User,
)
from app.services import audit
from app.services.studio import egress, events
from app.services.studio import secrets as vault

BACKOFF = [60, 300, 1800, 7200, 21600, 43200, 86400]
TOLERANCE_SECONDS = 300
MAX_ROTATION_OVERLAP_HOURS = 168


class WebhookError(ValueError):
    def __init__(self, message: str, status: int = 400, code: str = "invalid_request"):
        super().__init__(message)
        self.status = status
        self.code = code


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def new_secret() -> str:
    return "whsec_" + pysecrets.token_urlsafe(32)


def sign(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def signature_header(secrets_: list[str], timestamp: int, body: bytes) -> str:
    return ",".join([f"t={timestamp}", *(f"v1={sign(s, timestamp, body)}" for s in secrets_)])


def verify(header: str | None, secret: str, body: bytes, now: float | None = None) -> None:
    """Raise ``WebhookError`` unless the signature is valid and fresh."""
    if not header:
        raise WebhookError("Missing X-PeopleOpsLab-Signature.", 401, "signature_invalid")
    parts = [p.strip() for p in header.split(",")]
    ts = next((p[2:] for p in parts if p.startswith("t=")), None)
    sigs = [p[3:] for p in parts if p.startswith("v1=")]
    if not ts or not ts.isdigit() or not sigs:
        raise WebhookError("The signature header is malformed.", 401, "signature_invalid")
    if abs((now or time.time()) - int(ts)) > TOLERANCE_SECONDS:
        raise WebhookError("The signature timestamp is more than five minutes off.", 401, "signature_expired")
    expected = sign(secret, int(ts), body)
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise WebhookError("The signature does not match.", 401, "signature_invalid")


# ---------------------------------------------------------------------------
# Outbound subscriptions
# ---------------------------------------------------------------------------
def _check_events(names: list[str]) -> list[str]:
    unknown = sorted(set(names) - set(events.CATALOGUE) - {"*"})
    if unknown:
        raise WebhookError(f"Unknown event(s): {', '.join(unknown)}.")
    if not names:
        raise WebhookError("Subscribe to at least one event.")
    return sorted(set(names))


def create(db: Session, entity: Entity, actor: User, *, name: str, url: str, event_names: list[str],
           environment: str = "production") -> tuple[StudioWebhook, str]:
    egress.check_url(db, entity.org_id, url)
    secret = new_secret()
    hook = StudioWebhook(org_id=entity.org_id, entity_id=entity.id, name=name.strip()[:100], url=url.strip(),
                         events=_check_events(event_names), environment=environment,
                         secret_ciphertext=vault.seal({"current": secret}), created_by=actor.id)
    db.add(hook)
    db.flush()
    audit.record(db, entity_id=entity.id, user=actor, action="studio.webhook.created", object_type="studio_webhook",
                 object_id=str(hook.id), summary=f"Created webhook “{hook.name}” to {hook.url} for {', '.join(hook.events)}")
    return hook, secret


def update(db: Session, entity: Entity, hook: StudioWebhook, actor: User, body: dict[str, Any]) -> StudioWebhook:
    if body.get("url"):
        egress.check_url(db, entity.org_id, body["url"])
        hook.url = body["url"].strip()
    if body.get("events") is not None:
        hook.events = _check_events(body["events"])
    if body.get("name"):
        hook.name = body["name"].strip()[:100]
    if body.get("status") in ("active", "disabled"):
        hook.status = body["status"]
    audit.record(db, entity_id=entity.id, user=actor, action="studio.webhook.updated", object_type="studio_webhook",
                 object_id=str(hook.id), summary=f"Changed webhook “{hook.name}”")
    return hook


def rotate_secret(db: Session, entity: Entity, hook: StudioWebhook, actor: User, overlap_hours: int) -> str:
    if not 0 <= overlap_hours <= MAX_ROTATION_OVERLAP_HOURS:
        raise WebhookError(f"The overlap can be at most {MAX_ROTATION_OVERLAP_HOURS} hours.")
    current = vault.unseal(hook.secret_ciphertext)["current"]
    secret = new_secret()
    sealed: dict[str, Any] = {"current": secret}
    if overlap_hours:
        sealed.update(previous=current, previous_until=(_now() + timedelta(hours=overlap_hours)).isoformat())
    hook.secret_ciphertext = vault.seal(sealed)
    hook.secret_rotated_at = _now()
    audit.record(db, entity_id=entity.id, user=actor, action="studio.webhook.secret_rotated",
                 object_type="studio_webhook", object_id=str(hook.id),
                 summary=f"Rotated the signing secret of “{hook.name}” ({overlap_hours} h overlap)")
    return secret


def signing_secrets(hook: StudioWebhook) -> list[str]:
    sealed = vault.unseal(hook.secret_ciphertext)
    out = [sealed["current"]]
    until = sealed.get("previous_until")
    if sealed.get("previous") and until and datetime.fromisoformat(until) > _now():
        out.append(sealed["previous"])
    return out


def send_test(db: Session, entity: Entity, hook: StudioWebhook, actor: User) -> StudioEvent:
    return events.emit(db, org_id=entity.org_id, entity_id=entity.id, type="webhook.test",
                       data={"webhook_id": str(hook.id), "sent_by": actor.email}, only_webhook_id=hook.id)


def describe(hook: StudioWebhook, stats: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "id": str(hook.id), "name": hook.name, "url": hook.url, "events": hook.events,
        "payload_version": hook.payload_version, "environment": hook.environment, "status": hook.status,
        "max_attempts": hook.max_attempts,
        "secret_rotated_at": hook.secret_rotated_at.isoformat() if hook.secret_rotated_at else None,
        "last_delivery_at": hook.last_delivery_at.isoformat() if hook.last_delivery_at else None,
        "last_delivery_status": hook.last_delivery_status, "deliveries": stats or {},
        "created_at": hook.created_at.isoformat() if hook.created_at else None,
    }


def describe_delivery(d: StudioDelivery, event: StudioEvent | None) -> dict[str, Any]:
    return {
        "id": str(d.id), "webhook_id": str(d.webhook_id), "event_id": str(d.event_id),
        "event_type": event.type if event else None, "status": d.status, "attempts": d.attempts,
        "next_attempt_at": _aware(d.next_attempt_at).isoformat() if d.next_attempt_at else None,
        "last_status_code": d.last_status_code, "last_error": d.last_error, "last_response_ms": d.last_response_ms,
        "delivered_at": _aware(d.delivered_at).isoformat() if d.delivered_at else None,
        "replay_of_id": str(d.replay_of_id) if d.replay_of_id else None,
        "created_at": _aware(d.created_at).isoformat() if d.created_at else None,
        "payload": events.envelope(event) if event else None,
    }


def replay(db: Session, entity: Entity, delivery: StudioDelivery, actor: User) -> StudioDelivery:
    """Send the same event again, as a new delivery. Same event id: consumers de-duplicate."""
    again = StudioDelivery(webhook_id=delivery.webhook_id, event_id=delivery.event_id, entity_id=delivery.entity_id,
                           status="pending", next_attempt_at=_now(), replay_of_id=delivery.id, replayed_by=actor.id)
    db.add(again)
    db.flush()
    audit.record(db, entity_id=entity.id, user=actor, action="studio.webhook.replayed", object_type="studio_delivery",
                 object_id=str(again.id), summary=f"Replayed event {str(delivery.event_id)[:8]} to webhook {str(delivery.webhook_id)[:8]}")
    return again


# ---------------------------------------------------------------------------
# The dispatcher (worker)
# ---------------------------------------------------------------------------
def _locked(db: Session, sql: str, params: dict[str, Any]) -> list[uuid.UUID]:
    locking = "FOR UPDATE SKIP LOCKED" if db.bind.dialect.name == "postgresql" else ""
    rows = db.execute(text(sql.format(locking=locking)), params).all()  # nosec B608
    return [r[0] if isinstance(r[0], uuid.UUID) else uuid.UUID(str(r[0])) for r in rows]


def fan_out(db: Session, limit: int = 200) -> int:
    """Turn new events into one pending delivery per subscribed webhook."""
    ids = _locked(db, "SELECT id FROM studio_events WHERE dispatched_at IS NULL ORDER BY created_at LIMIT :n {locking}",
                  {"n": limit})
    if not ids:
        db.rollback()
        return 0
    now = _now()
    from app.services.studio import workflows

    for event in db.query(StudioEvent).filter(StudioEvent.id.in_(ids)).order_by(StudioEvent.created_at).all():
        # Workflows first, in the same transaction that marks the event
        # dispatched: an event starts its workflows once, or — if this
        # rolls back — is picked up again, and the fire keys stop a double start.
        workflows.on_event(db, event)
        hooks = db.query(StudioWebhook).filter(StudioWebhook.entity_id == event.entity_id,
                                               StudioWebhook.status == "active").all()
        for hook in hooks:
            if event.only_webhook_id is not None and hook.id != event.only_webhook_id:
                continue
            if event.only_webhook_id is None and event.type not in hook.events and "*" not in hook.events:
                continue
            db.add(StudioDelivery(webhook_id=hook.id, event_id=event.id, entity_id=event.entity_id,
                                  status="pending", next_attempt_at=now))
        event.dispatched_at = now
    db.commit()
    return len(ids)


def deliver_due(db: Session, limit: int = 20) -> int:
    ids = _locked(db, "SELECT id FROM studio_deliveries WHERE status = 'pending' AND next_attempt_at <= :now "
                      "ORDER BY next_attempt_at LIMIT :n {locking}", {"now": _now(), "n": limit})
    if not ids:
        db.rollback()
        return 0
    # Push the claimed rows' next attempt out while they are being sent, so a
    # second worker skips them even on SQLite, where there is no row lock.
    for d in db.query(StudioDelivery).filter(StudioDelivery.id.in_(ids)).all():
        d.next_attempt_at = _now() + timedelta(minutes=10)
    db.commit()
    for delivery_id in ids:
        _deliver_one(db, delivery_id)
    return len(ids)


def _deliver_one(db: Session, delivery_id: uuid.UUID) -> None:
    d = db.get(StudioDelivery, delivery_id)
    hook = db.get(StudioWebhook, d.webhook_id) if d else None
    event = db.get(StudioEvent, d.event_id) if d else None
    if d is None or hook is None or event is None:
        return
    body = json.dumps(events.envelope(event), separators=(",", ":"), default=str).encode()
    ts = int(time.time())
    d.attempts += 1
    try:
        header = signature_header(signing_secrets(hook), ts, body)
        resp = egress.request(db, hook.org_id, "POST", hook.url, body=body, timeout=15, max_bytes=64 * 1024, headers={
            "Content-Type": "application/json",
            "X-PeopleOpsLab-Event-Id": str(event.id),
            "X-PeopleOpsLab-Event-Type": event.type,
            "X-PeopleOpsLab-Delivery-Id": str(d.id),
            "X-PeopleOpsLab-Signature": header,
        })
        d.last_status_code = resp.status
        d.last_response_ms = resp.elapsed_ms
        ok = 200 <= resp.status < 300
        d.last_error = None if ok else f"Answered {resp.status}"
    except (egress.EgressRefused, egress.EgressFailed) as exc:
        ok = False
        d.last_status_code = None
        d.last_error = exc.message[:500]
    except vault.SecretStoreUnavailable as exc:
        ok = False
        d.last_error = str(exc)[:500]
    hook.last_delivery_at = _now()
    if ok:
        d.status = "delivered"
        d.delivered_at = _now()
        d.next_attempt_at = None
        hook.last_delivery_status = "delivered"
    elif d.attempts >= hook.max_attempts:
        d.status = "failed"
        d.next_attempt_at = None
        hook.last_delivery_status = "failed"
    else:
        d.next_attempt_at = _now() + timedelta(seconds=BACKOFF[min(d.attempts - 1, len(BACKOFF) - 1)])
        hook.last_delivery_status = "retrying"
    db.commit()


def dispatch(db: Session) -> int:
    return fan_out(db) + deliver_due(db)


# ---------------------------------------------------------------------------
# Inbound endpoints
# ---------------------------------------------------------------------------
def create_inbound(db: Session, entity: Entity, actor: User, *, name: str, action: dict[str, Any],
                   environment: str = "production") -> tuple[StudioInboundEndpoint, str]:
    from app.services.studio import imports, profiles
    from app.services.studio.credentials import _shadow_user

    if action.get("type") != "import":
        raise WebhookError("An inbound endpoint imports records (type: import).")
    kind = action.get("object_type")
    if kind not in imports.KINDS:
        raise WebhookError(f"object_type must be one of {', '.join(imports.KINDS)}.")
    if action.get("mapping_key"):
        versions = profiles.versions(db, entity.id, action["mapping_key"])
        if not versions or versions[0].object_type != kind:
            raise WebhookError(f"No {kind} mapping called {action['mapping_key']}.")
    secret = new_secret()
    endpoint = StudioInboundEndpoint(
        org_id=entity.org_id, entity_id=entity.id, user_id=_shadow_user(db, f"inbound {name}").id,
        name=name.strip()[:100], token=pysecrets.token_urlsafe(24), secret_ciphertext=vault.seal({"current": secret}),
        action={"type": "import", "object_type": kind, "mapping_key": action.get("mapping_key"),
                "options": action.get("options") or {}},
        environment=environment, created_by=actor.id,
    )
    db.add(endpoint)
    db.flush()
    audit.record(db, entity_id=entity.id, user=actor, action="studio.inbound.created",
                 object_type="studio_inbound_endpoint", object_id=str(endpoint.id),
                 summary=f"Created inbound endpoint “{endpoint.name}” importing {kind}")
    return endpoint, secret


def receive(db: Session, token: str, headers: dict[str, str], body: bytes, request_id: str | None) -> dict[str, Any]:
    """Verify, de-duplicate and act on one inbound call. Commits."""
    from app.services.studio import imports, profiles, runs

    endpoint = db.query(StudioInboundEndpoint).filter(StudioInboundEndpoint.token == token).first()
    if endpoint is None or endpoint.status != "active":
        raise WebhookError("Not found.", 404, "not_found")
    verify(headers.get("x-peopleopslab-signature"), vault.unseal(endpoint.secret_ciphertext)["current"], body)
    event_id = (headers.get("x-peopleopslab-event-id") or "").strip()
    if not event_id or len(event_id) > 200:
        raise WebhookError("Send a unique X-PeopleOpsLab-Event-Id with every call.", 400, "event_id_required")
    earlier = (db.query(StudioInboundReceipt)
               .filter(StudioInboundReceipt.endpoint_id == endpoint.id, StudioInboundReceipt.event_id == event_id).first())
    if earlier is not None:
        return {"duplicate": True, "receipt_id": str(earlier.id), "run_id": str(earlier.run_id) if earlier.run_id else None}
    try:
        payload = json.loads(body.decode("utf-8"))
    except ValueError:
        raise WebhookError("The body is not JSON.", 400, "invalid_request")
    action = endpoint.action or {}
    kind = action["object_type"]
    submitted = {**(action.get("options") or {}), **{k: v for k, v in payload.items() if k != "records"},
                 "records": payload.get("records")}
    try:
        options = imports.check_submission(kind, submitted)
    except ValueError as exc:
        raise WebhookError(str(exc), 400, "invalid_request")
    versions: dict[str, Any] = {}
    if action.get("mapping_key"):
        version = profiles.in_force(db, endpoint.entity_id, action["mapping_key"])
        if version is None:
            raise WebhookError("The endpoint's mapping has no published version in force.", 409, "conflict")
        versions = {"mapping": f"{version.key} v{version.version}", "mapping_id": str(version.id)}
    receipt = StudioInboundReceipt(endpoint_id=endpoint.id, entity_id=endpoint.entity_id, event_id=event_id)
    db.add(receipt)
    try:
        db.flush()
    except IntegrityError:
        # Two identical calls raced; the other one holds the receipt.
        db.rollback()
        return {"duplicate": True, "receipt_id": None, "run_id": None}
    from datetime import date

    run = runs.create(
        db, org_id=endpoint.org_id, entity_id=endpoint.entity_id, kind="import", object_type=kind,
        actor_type="machine", actor_user_id=endpoint.user_id, actor_label=f"Inbound endpoint “{endpoint.name}”",
        trigger="webhook", environment=endpoint.environment, source_system=payload.get("source_system") or endpoint.name,
        source_object=payload.get("source_object"), batch_id=payload.get("batch_id") or event_id[:100],
        period_month=date.fromisoformat(options["period_month"]) if options.get("period_month") else None,
        effective_from=date.fromisoformat(options["effective_from"]) if options.get("effective_from") else None,
        options=options, payload=submitted["records"], versions=versions, request_id=request_id,
        idempotency_key=event_id,
    )
    receipt.run_id = run.id
    endpoint.last_received_at = _now()
    from app.services.studio import events

    events.emit(db, org_id=endpoint.org_id, entity_id=endpoint.entity_id, type="inbound.received",
                data={"endpoint_id": str(endpoint.id), "receipt_id": str(receipt.id), "run_id": str(run.id)})
    db.commit()
    return {"duplicate": False, "receipt_id": str(receipt.id), "run_id": str(run.id)}


def describe_inbound(endpoint: StudioInboundEndpoint, base_url: str) -> dict[str, Any]:
    return {
        "id": str(endpoint.id), "name": endpoint.name, "url": f"{base_url}/hooks/{endpoint.token}",
        "action": endpoint.action, "environment": endpoint.environment, "status": endpoint.status,
        "last_received_at": endpoint.last_received_at.isoformat() if endpoint.last_received_at else None,
        "created_at": endpoint.created_at.isoformat() if endpoint.created_at else None,
    }
