"""
PeopleOps Studio, phase 2b: the outbox, signed outbound webhooks with retries
and a failed queue, and signed, de-duplicated inbound endpoints.

A receiver runs on 127.0.0.1 and records every request it gets.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.database import SessionLocal
from app.models import EmployeeRecord, StudioDelivery, StudioEvent
from app.services.studio import events, webhooks
from app.services.studio import worker as studio_worker
from tests.test_run_history import _company, _data, _empty_queue  # noqa: F401


class Receiver:
    requests: list[dict] = []
    status = 200


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        Receiver.requests.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        self.send_response(Receiver.status)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")


@pytest.fixture(scope="module")
def receiver():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/hook"
    server.shutdown()


@pytest.fixture()
def company(client, receiver):
    Receiver.requests = []
    Receiver.status = 200
    headers = _company(client, "hooks")
    client.post("/api/studio/destinations", headers=headers, json={"host": "127.0.0.1"})
    _drain()  # clear any outbox rows other tests left
    Receiver.requests = []
    return headers


def _drain():
    db = SessionLocal()
    try:
        studio_worker.drain(db)
    finally:
        db.close()


def _key(client, headers):
    account = _data(client.post("/api/studio/service-accounts", headers=headers, json={
        "name": f"feed {uuid.uuid4().hex[:4]}", "entity_ids": [headers["X-Entity-Id"]],
        "scopes": ["imports:write", "imports:read"]}))
    return _data(client.post(f"/api/studio/service-accounts/{account['id']}/keys", headers=headers,
                             json={"label": "t", "expires_in_days": 5}))["key"]


def _import(client, key, records):
    r = client.post("/api/integration/v1/imports/employee_master", headers={
        "Authorization": f"Bearer {key}", "Idempotency-Key": uuid.uuid4().hex},
        json={"effective_from": "2026-06-01", "records": records})
    assert r.status_code == 202, r.text
    return r.json()["data"]["id"]


def _mine(company):
    return [r for r in Receiver.requests if json.loads(r["body"])["company_id"] == company["X-Entity-Id"]]


def test_the_outbox_commits_with_the_change_or_not_at_all(client, company):
    db = SessionLocal()
    try:
        entity_id = uuid.UUID(company["X-Entity-Id"])
        from app.models import Entity

        org_id = db.get(Entity, entity_id).org_id
        events.emit(db, org_id=org_id, entity_id=entity_id, type="webhook.test", data={"x": 1})
        db.rollback()
        assert db.query(StudioEvent).filter(StudioEvent.entity_id == entity_id).count() == 0
    finally:
        db.close()
    key = _key(client, company)
    run_id = _import(client, key, [{"employee_id": "E1", "salary": "should not travel"}])
    db = SessionLocal()
    try:
        assert db.query(StudioEvent).filter(StudioEvent.entity_id == entity_id).count() == 0, \
            "a queued run announces nothing until it finishes"
    finally:
        db.close()
    _drain()
    db = SessionLocal()
    try:
        evs = db.query(StudioEvent).filter(StudioEvent.entity_id == entity_id).all()
    finally:
        db.close()
    assert [e.type for e in evs] == ["import.completed"]
    data = evs[0].data
    assert data["run_id"] == run_id and data["status"] == "completed" and data["counts"]["created"] == 1
    assert "should not travel" not in json.dumps(data), "events carry ids and states, never record content"


def test_deliveries_are_signed_verifiable_and_minimal(client, company, receiver):
    hook = _data(client.post("/api/studio/webhooks", headers=company, json={
        "name": "Finance", "url": receiver, "events": ["import.completed"]}))
    assert hook["secret"].startswith("whsec_") and hook["shown_once"]
    assert hook["secret"] not in json.dumps(_data(client.get("/api/studio/webhooks", headers=company)))
    key = _key(client, company)
    run_id = _import(client, key, [{"employee_id": "E1"}])
    _drain()
    got = _mine(company)
    assert len(got) == 1
    req = got[0]
    body = json.loads(req["body"])
    assert body["type"] == "import.completed" and body["data"]["run_id"] == run_id
    assert req["headers"]["x-peopleopslab-event-id"] == body["id"]
    webhooks.verify(req["headers"]["x-peopleopslab-signature"], hook["secret"], req["body"])
    with pytest.raises(webhooks.WebhookError):
        webhooks.verify(req["headers"]["x-peopleopslab-signature"], "whsec_wrong", req["body"])
    with pytest.raises(webhooks.WebhookError) as exc:
        webhooks.verify(req["headers"]["x-peopleopslab-signature"], hook["secret"], req["body"], now=time.time() + 600)
    assert exc.value.code == "signature_expired"
    listed = _data(client.get(f"/api/studio/webhooks/deliveries?webhook_id={hook['id']}", headers=company))
    assert listed["items"][0]["status"] == "delivered" and listed["items"][0]["last_status_code"] == 200


def test_failures_retry_with_backoff_then_wait_in_the_failed_queue(client, company, receiver):
    hook = _data(client.post("/api/studio/webhooks", headers=company, json={
        "name": "Flaky", "url": receiver, "events": ["import.completed"]}))
    db = SessionLocal()
    try:
        from app.models import StudioWebhook

        db.get(StudioWebhook, uuid.UUID(hook["id"])).max_attempts = 2
        db.commit()
    finally:
        db.close()
    Receiver.status = 500
    _import(client, _key(client, company), [{"employee_id": "E1"}])
    _drain()
    d = _data(client.get(f"/api/studio/webhooks/deliveries?webhook_id={hook['id']}", headers=company))["items"][0]
    assert d["status"] == "pending" and d["attempts"] == 1 and d["last_status_code"] == 500
    wait = datetime.fromisoformat(d["next_attempt_at"]) - datetime.now(UTC)
    assert timedelta(seconds=50) < wait <= timedelta(seconds=60), "first retry after about a minute"
    db = SessionLocal()
    try:
        row = db.get(StudioDelivery, uuid.UUID(d["id"]))
        row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    _drain()
    d = _data(client.get(f"/api/studio/webhooks/deliveries?webhook_id={hook['id']}", headers=company))["items"][0]
    assert d["status"] == "failed" and d["attempts"] == 2
    # The receiver recovers; a person replays the failed queue.
    Receiver.status = 200
    assert _data(client.post(f"/api/studio/webhooks/{hook['id']}/replay-failed", headers=company))["replayed"] == 1
    _drain()
    ok = [x for x in _data(client.get(f"/api/studio/webhooks/deliveries?webhook_id={hook['id']}", headers=company))["items"]
          if x["status"] == "delivered"]
    assert len(ok) == 1 and ok[0]["replay_of_id"] == d["id"]
    ids = {r["headers"]["x-peopleopslab-event-id"] for r in _mine(company)}
    assert len(_mine(company)) == 3 and len(ids) == 1, "at least once: the same event id every time, for de-duplication"


def test_secret_rotation_overlaps_then_ends(client, company, receiver):
    hook = _data(client.post("/api/studio/webhooks", headers=company, json={
        "name": "Rotating", "url": receiver, "events": ["*"]}))
    new = _data(client.post(f"/api/studio/webhooks/{hook['id']}/rotate-secret", headers=company,
                            json={"overlap_hours": 1}))["secret"]
    assert _data(client.post(f"/api/studio/webhooks/{hook['id']}/test", headers=company))["event_id"]
    _drain()
    req = _mine(company)[-1]
    assert json.loads(req["body"])["type"] == "webhook.test"
    assert req["headers"]["x-peopleopslab-signature"].count("v1=") == 2
    webhooks.verify(req["headers"]["x-peopleopslab-signature"], hook["secret"], req["body"])
    webhooks.verify(req["headers"]["x-peopleopslab-signature"], new, req["body"])
    _data(client.post(f"/api/studio/webhooks/{hook['id']}/rotate-secret", headers=company, json={"overlap_hours": 0}))
    client.post(f"/api/studio/webhooks/{hook['id']}/test", headers=company)
    _drain()
    assert _mine(company)[-1]["headers"]["x-peopleopslab-signature"].count("v1=") == 1


def test_a_test_event_reaches_only_its_webhook(client, company, receiver):
    a = _data(client.post("/api/studio/webhooks", headers=company, json={"name": "A", "url": receiver, "events": ["*"]}))
    _data(client.post("/api/studio/webhooks", headers=company, json={"name": "B", "url": receiver, "events": ["*"]}))
    client.post(f"/api/studio/webhooks/{a['id']}/test", headers=company)
    _drain()
    assert len(_mine(company)) == 1


def test_validation_and_finding_events(client, company):
    from tests.test_coverage import BASE_ROWS, _register, _run

    run_id = _run(client, company, _register(BASE_ROWS))
    worklist = _data(client.get("/api/findings/worklist?page_size=5", headers=company))
    fp = worklist["items"][0]["fingerprint"]
    client.post(f"/api/findings/{fp}/decision", headers=company, json={"state": "acknowledged"})
    db = SessionLocal()
    try:
        evs = db.query(StudioEvent).filter(StudioEvent.entity_id == uuid.UUID(company["X-Entity-Id"])).all()
    finally:
        db.close()
    types = [e.type for e in evs]
    assert "validation.completed" in types and "finding.state_changed" in types
    vc = next(e for e in evs if e.type == "validation.completed")
    assert vc.data["run_id"] == run_id
    fc = next(e for e in evs if e.type == "finding.state_changed")
    assert fc.data == {"fingerprint": fp, "rule_id": fc.data["rule_id"], "from": "open", "to": "acknowledged"}


def _signed(secret, body: bytes, event_id: str, ts: int | None = None):
    ts = ts or int(time.time())
    return {"X-PeopleOpsLab-Signature": webhooks.signature_header([secret], ts, body),
            "X-PeopleOpsLab-Event-Id": event_id, "Content-Type": "application/json"}


def test_inbound_endpoints_verify_deduplicate_and_import(client, company):
    ep = _data(client.post("/api/studio/inbound", headers=company, json={
        "name": "HRMS push", "object_type": "employee_master", "options": {"effective_from": "2026-06-01"}}))
    assert ep["secret"].startswith("whsec_") and ep["url"].endswith(ep["url"].split("/hooks/")[1])
    path = "/api/integration/v1/hooks/" + ep["url"].split("/hooks/")[1]
    body = json.dumps({"batch_id": "PUSH-1", "records": [{"employee_id": "00777", "employee_name": "Pushed (synthetic)"}]}).encode()
    first = client.post(path, content=body, headers=_signed(ep["secret"], body, "evt-1"))
    assert first.status_code == 202, first.text
    run_id = first.json()["data"]["run_id"]
    dup = client.post(path, content=body, headers=_signed(ep["secret"], body, "evt-1"))
    assert dup.status_code == 200 and dup.json()["data"]["duplicate"] is True and dup.json()["data"]["run_id"] == run_id
    bad = client.post(path, content=body, headers=_signed("whsec_wrong", body, "evt-2"))
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "signature_invalid"
    stale = client.post(path, content=body, headers=_signed(ep["secret"], body, "evt-3", ts=int(time.time()) - 900))
    assert stale.status_code == 401 and stale.json()["error"]["code"] == "signature_expired"
    tampered = client.post(path, content=body.replace(b"00777", b"00778"), headers=_signed(ep["secret"], body, "evt-4"))
    assert tampered.status_code == 401
    no_id = client.post(path, content=body, headers={k: v for k, v in _signed(ep["secret"], body, "x").items()
                                                     if k != "X-PeopleOpsLab-Event-Id"})
    assert no_id.status_code == 400 and no_id.json()["error"]["code"] == "event_id_required"
    assert client.post("/api/integration/v1/hooks/nope", content=body, headers=_signed(ep["secret"], body, "e")).status_code == 404
    _drain()
    run = _data(client.get(f"/api/studio/runs/{run_id}", headers=company))
    assert run["trigger"] == "webhook" and run["actor"]["type"] == "machine" and run["counts"]["created"] == 1
    db = SessionLocal()
    try:
        rec = db.query(EmployeeRecord).filter(EmployeeRecord.entity_id == uuid.UUID(company["X-Entity-Id"])).one()
        assert rec.employee_id == "00777"
    finally:
        db.close()
    receipts = _data(client.get(f"/api/studio/inbound/{ep['id']}/receipts", headers=company))
    assert [r["event_id"] for r in receipts] == ["evt-1"]
    client.patch(f"/api/studio/inbound/{ep['id']}", headers=company, json={"status": "disabled"})
    assert client.post(path, content=body, headers=_signed(ep["secret"], body, "evt-9")).status_code == 404


def test_webhooks_are_company_scoped_and_destinations_enforced(client, company, receiver):
    hook = _data(client.post("/api/studio/webhooks", headers=company, json={"name": "Mine", "url": receiver, "events": ["*"]}))
    other = _company(client, "hooks-other")
    assert _data(client.get("/api/studio/webhooks", headers=other)) == []
    assert client.post(f"/api/studio/webhooks/{hook['id']}/test", headers=other).status_code == 404
    r = client.post("/api/studio/webhooks", headers=other, json={"name": "x", "url": receiver, "events": ["*"]})
    assert r.status_code == 400 and "allowed destinations" in r.text
