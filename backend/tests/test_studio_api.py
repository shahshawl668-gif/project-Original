"""
PeopleOps Studio, phase 1: machine identities, the integration API, imports,
run history.

Every expected count is worked out here from the synthetic records, not read
back from the code: received, accepted, rejected, skipped, created, updated,
unchanged. The properties under test are the ones an integration relies on
without seeing them — a key never reaches past its companies and scopes, a
retried request never imports twice, a value that cannot be read is rejected
and never quietly stored as blank or zero, and a key cannot take a decision
that belongs to a person.
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import (
    AuditEvent,
    EmployeeRecord,
    IntegrationCredential,
    RegisterUpload,
    ServiceAccount,
    StudioRun,
    User,
)
from app.security import create_access_token
from app.services.studio import credentials, ratelimit
from app.services.studio import worker as studio_worker
from tests.test_coverage import BASE_ROWS, HEADER, _register
from tests.test_run_history import PASSWORD, PERIOD, _company, _data, _drain, _empty_queue  # noqa: F401

API = "/api/integration/v1"
ALL_SCOPES = sorted(credentials.SCOPES)


def _studio_drain() -> int:
    db = SessionLocal()
    try:
        return studio_worker.drain(db)
    finally:
        db.close()


def _key(client, headers, *, scopes=None, entity_ids=None, environment="production", name=None) -> dict:
    account = _data(client.post("/api/studio/service-accounts", headers=headers, json={
        "name": name or f"HRMS feed {uuid.uuid4().hex[:6]}", "environment": environment,
        "entity_ids": entity_ids or [headers["X-Entity-Id"]], "scopes": scopes or ALL_SCOPES,
    }))
    issued = _data(client.post(f"/api/studio/service-accounts/{account['id']}/keys", headers=headers,
                               json={"label": "test", "expires_in_days": 30}))
    return {"key": issued["key"], "account": account, "credential": issued}


def call(client, key, method, path, *, company=None, idem=None, json_body=None, headers=None):
    h = {"Authorization": f"Bearer {key}"}
    if company:
        h["X-Company-Id"] = company
    if idem:
        h["Idempotency-Key"] = idem
    h.update(headers or {})
    return client.request(method, API + path, headers=h, json=json_body)


def ok_data(r, status=200):
    assert r.status_code == status, r.text
    body = r.json()
    assert body["success"] is True
    return body["data"]


def err(r, status, code):
    assert r.status_code == status, r.text
    body = r.json()
    assert body["success"] is False and body["error"]["code"] == code, body
    assert body["error"]["request_id"]
    return body["error"]


def submit(client, key, kind, body, *, company=None):
    r = call(client, key, "POST", f"/imports/{kind}", company=company, idem=uuid.uuid4().hex, json_body=body)
    run = ok_data(r, 202)
    _studio_drain()
    return ok_data(call(client, key, "GET", f"/imports/{run['id']}", company=company))


@pytest.fixture()
def company(client):
    ratelimit.reset()
    return _company(client, "studio")


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
def test_a_machine_is_not_a_person(client, company):
    k = _key(client, company)
    db = SessionLocal()
    try:
        account = db.get(ServiceAccount, uuid.UUID(k["account"]["id"]))
        machine = db.get(User, account.user_id)
        assert machine.role == "machine"
        # It cannot sign in, whatever password is tried: its address is not
        # even one the login form accepts (422), and the role is refused (401).
        assert client.post("/api/auth/login", json={"email": machine.email,
                                                    "password": "__machine__"}).status_code in (401, 422)
        # …and a session token naming it is refused by the product.
        forged = create_access_token(str(machine.id), {"portal": "client", "org_id": str(account.org_id)})
    finally:
        db.close()
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    # A person's session is not accepted by the integration API, and a key is
    # not accepted by the product's API.
    err(client.get(API + "/me", headers={"Authorization": company["Authorization"]}), 401, "unauthorized")
    assert client.get("/api/studio/overview", headers={"Authorization": f"Bearer {k['key']}",
                                                       "X-Entity-Id": company["X-Entity-Id"]}).status_code == 401
    me = ok_data(call(client, k["key"], "GET", "/me"))
    assert me["scopes"] == ALL_SCOPES and [c["id"] for c in me["companies"]] == [company["X-Entity-Id"]]


def test_the_key_is_shown_once_and_stored_only_as_a_hash(client, company):
    k = _key(client, company)
    assert k["key"].startswith("pol_live_") and k["credential"]["shown_once"]
    listed = _data(client.get("/api/studio/service-accounts", headers=company))
    assert k["key"] not in json.dumps(listed)
    db = SessionLocal()
    try:
        cred = db.query(IntegrationCredential).filter(IntegrationCredential.prefix == k["credential"]["prefix"]).one()
        assert cred.secret_hash == credentials.hash_key(k["key"]) and k["key"] not in cred.secret_hash
        trail = db.query(AuditEvent).filter(AuditEvent.org_id == cred.org_id).all()
        assert trail and all(k["key"] not in json.dumps([e.summary, e.detail], default=str) for e in trail)
    finally:
        db.close()
    assert credentials.redact(f"failed with {k['key']}") == f"failed with {k['credential']['prefix']}_[redacted]"


# ---------------------------------------------------------------------------
# Scopes, companies and who may create keys
# ---------------------------------------------------------------------------
def test_scopes_and_companies_bound_every_key(client, company):
    other_company = _data(client.post("/api/org/entities", headers=company,
                                      json={"name": "Studio sister co", "primary_state": "Karnataka"}))["id"]
    reader = _key(client, company, scopes=["imports:read"])
    err(call(client, reader["key"], "POST", "/imports/employee_master", idem="a",
             json_body={"effective_from": PERIOD, "records": [{"employee_id": "1"}]}), 403, "forbidden_scope")
    # A company the key does not name answers as if it did not exist.
    err(call(client, reader["key"], "GET", "/imports", company=other_company), 404, "not_found")
    err(call(client, reader["key"], "GET", "/imports", company=str(uuid.uuid4())), 404, "not_found")
    stranger = _company(client, "studio-stranger")
    err(call(client, reader["key"], "GET", "/imports", company=stranger["X-Entity-Id"]), 404, "not_found")
    # With two companies the caller must say which.
    both = _key(client, company, entity_ids=[company["X-Entity-Id"], other_company])
    err(call(client, both["key"], "GET", "/imports"), 400, "company_required")
    assert ok_data(call(client, both["key"], "GET", "/imports", company=other_company))["total"] == 0
    # Nobody can hand a key a company from another organisation.
    r = client.post("/api/studio/service-accounts", headers=company, json={
        "name": "reach", "entity_ids": [stranger["X-Entity-Id"]], "scopes": ["imports:read"]})
    assert r.status_code == 403


def test_only_owners_and_managers_manage_keys(client, company):
    email = f"studio-analyst-{uuid.uuid4().hex[:6]}@studio-example.com"
    inv = _data(client.post("/api/org/invitations", headers=company, json={"email": email, "role": "analyst"}))
    token = client.post("/api/org/invitations/register", json={"token": inv["token"], "password": PASSWORD}).json()["data"]["access_token"]
    analyst = {"Authorization": f"Bearer {token}", "X-Entity-Id": company["X-Entity-Id"]}
    assert client.post("/api/studio/service-accounts", headers=analyst, json={
        "name": "x", "entity_ids": [company["X-Entity-Id"]], "scopes": ["imports:read"]}).status_code == 403
    assert client.get("/api/studio/service-accounts", headers=analyst).status_code == 403
    # An analyst may read the run history.
    assert client.get("/api/studio/runs", headers=analyst).status_code == 200


def test_revoked_expired_and_rotated_keys(client, company):
    k = _key(client, company)
    assert call(client, k["key"], "GET", "/me").status_code == 200
    rotated = _data(client.post(f"/api/studio/keys/{k['credential']['id']}/rotate", headers=company,
                                json={"grace_hours": 1}))
    # During the overlap both keys work…
    assert call(client, k["key"], "GET", "/me").status_code == 200
    assert call(client, rotated["new"]["key"], "GET", "/me").status_code == 200
    assert rotated["previous"]["state"] == "rotating"
    # …and once the overlap ends only the new one does.
    db = SessionLocal()
    try:
        old = db.get(IntegrationCredential, uuid.UUID(k["credential"]["id"]))
        old.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    err(call(client, k["key"], "GET", "/me"), 401, "credential_expired")
    assert client.post(f"/api/studio/keys/{rotated['new']['id']}/revoke", headers=company,
                       json={"reason": "leaked in a ticket"}).status_code == 200
    err(call(client, rotated["new"]["key"], "GET", "/me"), 401, "credential_revoked")
    # A wrong secret with a real prefix learns nothing about the key's state.
    forged = rotated["new"]["key"][:18] + "_" + "A" * 43
    err(call(client, forged, "GET", "/me"), 401, "unauthorized")
    # Disabling the account stops every key it has.
    k2 = _key(client, company)
    client.patch(f"/api/studio/service-accounts/{k2['account']['id']}", headers=company, json={"status": "disabled"})
    err(call(client, k2["key"], "GET", "/me"), 401, "credential_revoked")


# ---------------------------------------------------------------------------
# Imports and reconciliation
# ---------------------------------------------------------------------------
MASTER = [
    {"employee_id": "00123", "employee_name": "Asha (synthetic)", "date_of_joining": "2024-04-15",
     "department": "Engineering", "_source_record_id": "hrms-1"},
    {"emp_id": "00124", "name": "Vikram (synthetic)", "doj": "2025-01-06", "department": "Sales",
     "_source_record_id": "hrms-2"},                                                   # other aliases
    {"employee_id": "00125", "employee_name": "Bad date", "date_of_joining": "31/31/2025"},  # rejected
    {"employee_name": "No id"},                                                          # rejected
    {"employee_id": "00123", "employee_name": "Asha (synthetic)", "date_of_joining": "2024-04-15",
     "department": "Engineering", "_source_record_id": "hrms-1"},                      # identical: skipped
    {"employee_id": "00126", "employee_name": "Twin A", "department": "Ops"},           # conflict
    {"employee_id": "00126", "employee_name": "Twin B", "department": "Ops"},           # conflict
    "not an object",                                                                     # rejected
]


def test_master_import_accounts_for_every_record(client, company):
    k = _key(client, company)
    run = submit(client, k["key"], "employee_master", {
        "batch_id": "MASTER-1", "source_system": "Example HRMS", "effective_from": PERIOD, "records": MASTER})
    assert run["status"] == "partially_completed"
    # 8 received: 00123 and 00124 accepted and created; the identical repeat
    # skipped; bad date, no id, both twins and the string rejected.
    assert run["counts"] == {"received": 8, "accepted": 2, "rejected": 5, "skipped": 1,
                             "created": 2, "updated": 0, "unchanged": 0, "removed": 0}
    assert run["error"]["recommended_action"]
    rej = ok_data(call(client, k["key"], "GET", f"/imports/{run['id']}/rejections"))
    codes = {(r["row_number"], r["code"]) for r in rej["items"]}
    assert codes == {(3, "invalid_date"), (4, "missing_employee_id"), (5, "duplicate_identical"),
                     (6, "duplicate_conflict"), (7, "duplicate_conflict"), (8, "invalid_record")}
    bad_date = next(r for r in rej["items"] if r["code"] == "invalid_date")
    assert bad_date["field"] == "date_of_joining" and bad_date["record_key"] == "00125"
    db = SessionLocal()
    try:
        stored = {r.employee_id: r for r in db.query(EmployeeRecord).filter(
            EmployeeRecord.entity_id == uuid.UUID(company["X-Entity-Id"])).all()}
    finally:
        db.close()
    # Leading zeros kept; the two alias spellings read the same way.
    assert set(stored) == {"00123", "00124"}
    assert str(stored["00124"].date_of_joining) == "2025-01-06"
    lineage = stored["00123"].lineage
    assert lineage["run_id"] == run["id"] and lineage["record_id"] == "hrms-1"
    assert lineage["source_system"] == "Example HRMS" and lineage["batch_id"] == "MASTER-1"

    # Upsert: one changed, one unchanged, one new. Nobody unmentioned removed.
    second = submit(client, k["key"], "employee_master", {"effective_from": PERIOD, "records": [
        {"employee_id": "00123", "employee_name": "Asha (synthetic)", "date_of_joining": "2024-04-15",
         "department": "Engineering"},
        {"employee_id": "00124", "employee_name": "Vikram (synthetic)", "date_of_joining": "2025-01-06",
         "department": "Finance"},
        {"employee_id": "00127", "employee_name": "New joiner"},
    ]})
    assert second["status"] == "completed"
    assert second["counts"] == {"received": 3, "accepted": 3, "rejected": 0, "skipped": 0,
                                "created": 1, "updated": 1, "unchanged": 1, "removed": 0}
    # Replace: the version becomes exactly the batch.
    third = submit(client, k["key"], "employee_master", {"effective_from": PERIOD, "mode": "replace", "records": [
        {"employee_id": "00123", "employee_name": "Asha (synthetic)"}]})
    assert third["counts"]["removed"] == 2 and third["counts"]["updated"] == 1


def test_idempotency_keys_make_retries_safe(client, company):
    k = _key(client, company)
    body = {"effective_from": PERIOD, "records": [{"employee_id": "9001", "employee_name": "Retry test"}]}
    err(call(client, k["key"], "POST", "/imports/employee_master", json_body=body), 400, "idempotency_key_required")
    first = call(client, k["key"], "POST", "/imports/employee_master", idem="batch-42", json_body=body)
    again = call(client, k["key"], "POST", "/imports/employee_master", idem="batch-42", json_body=body)
    assert first.status_code == again.status_code == 202
    assert again.headers.get("Idempotent-Replayed") == "true"
    assert first.json()["data"]["id"] == again.json()["data"]["id"]
    db = SessionLocal()
    try:
        n = db.query(StudioRun).filter(StudioRun.entity_id == uuid.UUID(company["X-Entity-Id"]),
                                       StudioRun.kind == "import").count()
    finally:
        db.close()
    assert n == 1
    changed = {**body, "records": [{"employee_id": "9002"}]}
    err(call(client, k["key"], "POST", "/imports/employee_master", idem="batch-42", json_body=changed),
        409, "idempotency_key_reused")
    # Keys belong to the caller: another key may use the same string.
    other = _key(client, company)
    assert call(client, other["key"], "POST", "/imports/employee_master", idem="batch-42",
                json_body=body).status_code == 202


def test_ctc_history_and_unreadable_amounts(client, company):
    k = _key(client, company)
    run = submit(client, k["key"], "ctc", {"records": [
        {"employee_id": "00123", "effective_from": "2025-04-01", "basic": 480000, "annual_ctc": 900000},
        {"employee_id": "00123", "effective_from": "2026-04-01", "basic": 528000, "annual_ctc": 990000},
        {"employee_id": "00124", "effective_from": "2026-04-01", "basic": "abc"},     # never read as 0
        {"employee_id": "00125", "basic": 300000},                                     # no date, no default
        {"employee_id": "00126", "effective_from": "2026-04-01", "basic": 300000, "shoe_allowance": 5},
    ]})
    assert run["counts"] == {"received": 5, "accepted": 3, "rejected": 2, "skipped": 0,
                             "created": 3, "updated": 0, "unchanged": 0, "removed": 0}
    rej = ok_data(call(client, k["key"], "GET", f"/imports/{run['id']}/rejections"))["items"]
    assert {(r["record_key"], r["code"], r["field"]) for r in rej} == {
        ("00124", "invalid_number", "basic"), ("00125", "missing_effective_from", "effective_from")}
    assert run["links"]["ignored_columns"] == ["shoe_allowance"]
    # History is kept by date; sending the same again changes nothing.
    again = submit(client, k["key"], "ctc", {"records": [
        {"employee_id": "00123", "effective_from": "2025-04-01", "basic": 480000, "annual_ctc": 900000}]})
    assert again["counts"]["unchanged"] == 1 and again["counts"]["created"] == 0


def test_attendance_keeps_absent_apart_from_zero(client, company):
    k = _key(client, company)
    run = submit(client, k["key"], "attendance", {"period_month": PERIOD, "records": [
        {"employee_id": "E1", "paid_days": 30, "lop_days": 0},
        {"employee_id": "E2", "paid_days": 28},
        {"employee_id": "E3", "paid_days": "twenty"},
    ]})
    assert run["counts"]["accepted"] == 2 and run["counts"]["rejected"] == 1
    from app.models import AttendanceRow

    db = SessionLocal()
    try:
        rows = {r.employee_id: r for r in db.query(AttendanceRow).filter(
            AttendanceRow.entity_id == uuid.UUID(company["X-Entity-Id"])).all()}
    finally:
        db.close()
    assert rows["E1"].lop_days == 0 and rows["E1"].present_days is None


def test_a_register_is_all_or_nothing_then_validated(client, company):
    k = _key(client, company)
    cols = HEADER.split(",")
    records = [dict(zip(cols, line.split(","), strict=True)) for line in _register(BASE_ROWS).decode().strip().split("\n")[1:]]
    broken = [dict(r) for r in records]
    broken[1]["basic"] = "thirty thousand"
    failed = submit(client, k["key"], "salary_register", {"period_month": PERIOD, "records": broken})
    assert failed["status"] == "failed" and failed["counts"]["accepted"] == 0
    assert "no rows were stored" in failed["error"]["message"]
    db = SessionLocal()
    try:
        assert db.query(RegisterUpload).filter(RegisterUpload.entity_id == uuid.UUID(company["X-Entity-Id"])).count() == 0
    finally:
        db.close()

    stored = submit(client, k["key"], "salary_register",
                    {"period_month": PERIOD, "records": records, "validate": True, "batch_id": "JUN"})
    assert stored["status"] == "completed" and stored["counts"]["created"] == 3
    job_id = stored["links"]["validation_job_id"]
    _drain()
    job = ok_data(call(client, k["key"], "GET", f"/validation-jobs/{job_id}"))
    assert job["state"] == "succeeded"
    run_id = job["run_id"]
    # The same numbers the product's own screen reports.
    screen = _data(client.get(f"/api/validation/runs/{run_id}/findings?page_size=500", headers=company))
    api = ok_data(call(client, k["key"], "GET", f"/validation-runs/{run_id}/findings?page_size=500"))
    assert api["total"] == screen["total"] and {f["fingerprint"] for f in api["items"]} == {f["fingerprint"] for f in screen["items"]}
    pf = next(f for f in api["items"] if f["rule_id"] == "STAT-001")
    assert pf["employee_id"] == "E002"

    # Work the finding — but never waive or resolve it.
    fp = pf["fingerprint"]
    assert call(client, k["key"], "POST", f"/findings/{fp}/comments", json_body={"body": "Seen by HRMS"}).status_code == 200
    ack = ok_data(call(client, k["key"], "POST", f"/findings/{fp}/decision", json_body={"state": "acknowledged"}))
    assert ack["state"] == "acknowledged"
    err(call(client, k["key"], "POST", f"/findings/{fp}/decision", json_body={"state": "waived"}), 403, "approval_required")
    err(call(client, k["key"], "POST", f"/findings/{fp}/decision", json_body={"state": "resolved"}), 403, "approval_required")

    # Period status is the screen's own answer.
    status = ok_data(call(client, k["key"], "GET", f"/periods/{PERIOD}/status"))
    assert status == _data(client.get(f"/api/validation/periods/{PERIOD}/status", headers=company))
    evidence = ok_data(call(client, k["key"], "GET", f"/periods/{PERIOD}/evidence"))
    assert evidence["state"] is None
    # Per-employee pay needs its own scope.
    narrow = _key(client, company, scopes=["validation:read"])
    err(call(client, narrow["key"], "GET", f"/validation-runs/{run_id}/employees"), 403, "forbidden_scope")
    assert ok_data(call(client, k["key"], "GET", f"/validation-runs/{run_id}/employees"))["total"] == 3

    # Run history links the import to the validation run it produced.
    history = _data(client.get(f"/api/studio/runs/{stored['id']}", headers=company))
    assert history["links"]["validation_run_id"] == run_id


def test_a_dry_run_stores_nothing(client, company):
    k = _key(client, company)
    r = call(client, k["key"], "POST", "/imports/employee_master/check",
             json_body={"effective_from": PERIOD, "records": MASTER})
    out = ok_data(r)
    assert out["counts"]["accepted"] == 2 and out["counts"]["rejected"] == 5 and out["counts"]["created"] == 2
    assert {x["code"] for x in out["rejections"]} >= {"invalid_date", "duplicate_conflict"}
    db = SessionLocal()
    try:
        cid = uuid.UUID(company["X-Entity-Id"])
        assert db.query(EmployeeRecord).filter(EmployeeRecord.entity_id == cid).count() == 0
        assert db.query(StudioRun).filter(StudioRun.entity_id == cid).count() == 0
    finally:
        db.close()


def test_rules_are_proposed_never_published_by_a_key(client, company):
    k = _key(client, company)
    body = {"rule_key": "CUST-BASIC-FLOOR", "name": "Basic at least 40% of gross", "effective_from": PERIOD,
            "assertion": {"left": {"source": "component", "key": "basic"}, "operator": "gte",
                          "right": {"source": "literal", "value": "10000"}},
            "change_reason": "Synthetic policy for the test"}
    err(call(client, k["key"], "POST", "/configuration/rules", json_body=body), 400, "idempotency_key_required")
    proposed = ok_data(call(client, k["key"], "POST", "/configuration/rules", idem="rule-1", json_body=body), 201)
    assert proposed["status"] == "pending"
    # There is no publishing endpoint for a key; a person publishes it.
    assert call(client, k["key"], "POST", f"/configuration/rules/{proposed['id']}/publish").status_code in (404, 405)
    published = _data(client.post(f"/api/validation-matrix/{proposed['id']}/publish", headers=company))
    assert published["status"] == "published"


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
def test_rate_limit_answers_429_with_retry_after(client, company, monkeypatch):
    k = _key(client, company)
    monkeypatch.setattr(settings, "integration_rate_limit_per_minute", 3)
    for _ in range(3):
        r = call(client, k["key"], "GET", "/me")
        assert r.status_code == 200 and int(r.headers["X-RateLimit-Limit"]) == 3
    r = call(client, k["key"], "GET", "/me")
    err(r, 429, "rate_limited")
    assert int(r.headers["Retry-After"]) >= 1
    # Another key has its own allowance.
    assert call(client, _key(client, company)["key"], "GET", "/me").status_code == 200


def test_request_size_and_batch_limits(client, company, monkeypatch):
    k = _key(client, company)
    monkeypatch.setattr(settings, "integration_max_records", 2)
    err(call(client, k["key"], "POST", "/imports/employee_master", idem="big", json_body={
        "effective_from": PERIOD, "records": [{"employee_id": str(i)} for i in range(3)]}), 400, "invalid_request")
    monkeypatch.setattr(settings, "integration_max_request_mb", 0)
    err(call(client, k["key"], "POST", "/imports/employee_master", idem="huge", json_body={
        "effective_from": PERIOD, "records": [{"employee_id": "1"}]}), 413, "payload_too_large")


# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------
def test_a_run_abandoned_by_a_dead_worker_is_finished_once(client, company):
    k = _key(client, company)
    run = ok_data(call(client, k["key"], "POST", "/imports/employee_master", idem="crash", json_body={
        "effective_from": PERIOD, "records": [{"employee_id": "C1"}, {"employee_id": "C2"}]}), 202)
    db = SessionLocal()
    try:
        row = db.get(StudioRun, uuid.UUID(run["id"]))
        row.status, row.worker_id, row.attempts = "running", "dead-worker", 1
        row.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        db.commit()
    finally:
        db.close()
    _studio_drain()
    done = ok_data(call(client, k["key"], "GET", f"/imports/{run['id']}"))
    assert done["status"] == "completed" and done["attempts"] == 2
    assert done["counts"]["created"] == 2


def test_a_transient_failure_is_retried_then_stops(client, company, monkeypatch):
    k = _key(client, company)
    from app.services.studio import imports

    calls = {"n": 0}
    real = imports.process

    def flaky(db, run):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("database went away")
        return real(db, run)

    monkeypatch.setattr(imports, "process", flaky)
    monkeypatch.setattr(studio_worker, "BACKOFF_SECONDS", 0)
    run = ok_data(call(client, k["key"], "POST", "/imports/employee_master", idem="flaky", json_body={
        "effective_from": PERIOD, "records": [{"employee_id": "F1"}]}), 202)
    _studio_drain()
    done = ok_data(call(client, k["key"], "GET", f"/imports/{run['id']}"))
    assert done["status"] == "completed" and done["attempts"] == 2

    monkeypatch.setattr(imports, "process", lambda db, run: (_ for _ in ()).throw(ConnectionError("down")))
    run = ok_data(call(client, k["key"], "POST", "/imports/employee_master", idem="dead", json_body={
        "effective_from": PERIOD, "records": [{"employee_id": "F2"}]}), 202)
    _studio_drain()
    failed = ok_data(call(client, k["key"], "GET", f"/imports/{run['id']}"))
    assert failed["status"] == "failed" and failed["attempts"] == 3
    assert failed["error"]["category"] == "internal" and failed["error"]["recommended_action"]


# ---------------------------------------------------------------------------
# Studio screens
# ---------------------------------------------------------------------------
def test_run_history_is_company_scoped_and_rejected_records_are_guarded(client, company):
    k = _key(client, company)
    run = submit(client, k["key"], "employee_master", {"effective_from": PERIOD, "records": MASTER})
    listed = _data(client.get("/api/studio/runs?status=partially_completed", headers=company))
    assert [r["id"] for r in listed["items"]] == [run["id"]]
    assert listed["items"][0]["actor"]["type"] == "machine"
    rejections = _data(client.get(f"/api/studio/runs/{run['id']}/rejections", headers=company))["items"]
    first = rejections[0]
    record = _data(client.get(f"/api/studio/runs/{run['id']}/rejections/{first['id']}/record", headers=company))
    assert record["record"] == MASTER[2]
    stranger = _company(client, "studio-other")
    assert client.get(f"/api/studio/runs/{run['id']}", headers=stranger).status_code == 404
    other_key = _key(client, stranger)
    err(call(client, other_key["key"], "GET", f"/imports/{run['id']}"), 404, "not_found")

    # Retrying sends only the rejected records, as a new run linked to the first.
    retry = _data(client.post(f"/api/studio/runs/{run['id']}/retry-rejected", headers=company))
    _studio_drain()
    done = _data(client.get(f"/api/studio/runs/{retry['id']}", headers=company))
    assert done["retry_of_run_id"] == run["id"] and done["counts"]["received"] == 4
    assert client.post(f"/api/studio/runs/{run['id']}/retry-rejected", headers=company).status_code == 409


def test_overview_says_which_sections_exist(client, company):
    data = _data(client.get("/api/studio/overview", headers=company))
    available = {s["key"] for s in data["sections"] if s["available"]}
    assert available == {"api", "runs", "connections", "mapping", "webhooks", "workflows", "developer", "releases"}
    assert all(s["href"] is None for s in data["sections"] if not s["available"])


def test_openapi_contract_is_published(client):
    spec = client.get(API + "/openapi.json").json()
    paths = spec["paths"]
    for path in ("/imports/{kind}", "/imports/{kind}/check", "/imports/{run_id}/rejections", "/validation-jobs",
                 "/validation-runs/{run_id}/findings", "/findings/{fingerprint}/decision", "/configuration/rules",
                 "/bi/query", "/periods/{period}/status", "/periods/{period}/evidence"):
        assert path in paths, path
    examples = paths["/imports/{kind}"]["post"]["requestBody"]["content"]["application/json"]["examples"]
    assert set(examples) == {"employee_master", "ctc", "attendance", "salary_register"}
    text = json.dumps(spec)
    assert "Idempotency-Key" in spec["info"]["description"] and "rate_limited" in spec["info"]["description"]
    # No example carries anything that looks like a real key.
    assert not credentials.KEY_PATTERN.search(text.replace("<your key>", ""))
    assert spec["servers"] == [{"url": API}]


def test_every_error_has_code_and_request_id(client, company):
    r = client.get(API + "/me", headers={"X-Request-Id": "trace-me-123"})
    e = err(r, 401, "unauthorized")
    assert e["request_id"] == "trace-me-123" and r.headers["X-Request-Id"] == "trace-me-123"
    k = _key(client, company)
    err(call(client, k["key"], "POST", "/validation-jobs", idem="v", json_body={"period_month": "not-a-date"}),
        422, "validation_error")
    err(call(client, k["key"], "POST", "/validation-jobs", idem="v2", json_body={"period_month": PERIOD}),
        400, "invalid_request")


def test_bi_through_the_api_matches_the_product(client, company):
    k = _key(client, company)
    cols = HEADER.split(",")
    records = [dict(zip(cols, line.split(","), strict=True)) for line in _register(BASE_ROWS).decode().strip().split("\n")[1:]]
    submit(client, k["key"], "salary_register", {"period_month": PERIOD, "records": records})
    body = {"dataset": "payroll_cost", "metric": "ctc", "breakdown": "period", "period": {"preset": "all"}}
    api = ok_data(call(client, k["key"], "POST", "/bi/query", json_body=body))
    screen = _data(client.post("/api/dashboards/query", headers=company, json=body))
    assert api["total"] == screen["total"] and api["total"] is not None
    assert api["basis"]["periods_with_register"] == ["2026-06-01"]


def test_upload_screens_record_lineage_too(client, company):
    csv = "employee_id,employee_name,date_of_joining\n0042,Screen upload,2024-01-01\n0042,Duplicate,2024-01-01\n"
    r = client.post("/api/workforce/master/commit", headers=company,
                    files={"file": ("m.csv", io.BytesIO(csv.encode()), "text/csv")},
                    data={"meta": json.dumps({"effective_from": PERIOD})})
    out = _data(r)
    assert out["duplicates_skipped"] == ["0042"]
    db = SessionLocal()
    try:
        rec = db.query(EmployeeRecord).filter(EmployeeRecord.entity_id == uuid.UUID(company["X-Entity-Id"])).one()
    finally:
        db.close()
    assert rec.employee_id == "0042" and rec.lineage["channel"] == "upload" and rec.lineage["source_object"] == "m.csv"
