"""
PeopleOps Studio, phase 2a: destinations, secrets, connections, mapping, sync.

A mock HRMS runs on 127.0.0.1 for these tests. Every expected count is worked
out from the records the mock serves, not read back from the code.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import AuditEvent, EmployeeRecord, StudioConnection, StudioStream
from app.services.studio import egress
from app.services.studio import secrets as vault
from app.services.studio import sync as sync_svc
from app.services.studio import worker as studio_worker
from tests.test_run_history import PASSWORD, _company, _data, _empty_queue  # noqa: F401

API_KEY = "hrms-key-" + "7" * 24


class Mock:
    employees: list[dict] = []
    flaky_left = 0
    token_calls = 0
    codes: dict[str, str] = {}
    seen_params: list[dict] = []


def _employees():
    return [
        {"EmpNo": "123", "Name": "Asha (synthetic)", "Hired": "15/04/2024", "Loc": "BLR", "Type": "P",
         "updated_at": "2026-06-01T10:00:00Z", "id": "h-1", "CostCode": "CC-9"},
        {"EmpNo": "124", "Name": "Vikram (synthetic)", "Hired": "06/01/2025", "Loc": "MUM", "Type": "C",
         "updated_at": "2026-06-02T10:00:00Z", "id": "h-2"},
        {"EmpNo": "125", "Name": "Bad date (synthetic)", "Hired": "31/31/2025", "Loc": "BLR", "Type": "P",
         "updated_at": "2026-06-03T10:00:00Z", "id": "h-3"},
        {"EmpNo": "126", "Name": "Unknown place (synthetic)", "Hired": "01/02/2025", "Loc": "XYZ", "Type": "P",
         "updated_at": "2026-06-04T10:00:00Z", "id": "h-4"},
        {"EmpNo": "127", "Name": "Meera (synthetic)", "Hired": "01/03/2025", "Loc": "BLR", "Type": "P",
         "updated_at": "2026-06-05T10:00:00Z", "id": "h-5"},
    ]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body, headers=None):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        url = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        Mock.seen_params.append({"path": url.path, **q})
        if url.path == "/v1/employees":
            if self.headers.get("X-API-Key") != API_KEY:
                return self._send(401, {"error": "bad key"})
            rows = Mock.employees
            if q.get("modified_since"):
                rows = [r for r in rows if r["updated_at"] > q["modified_since"]]
            page, size = int(q.get("page", 1)), int(q.get("page_size", 100))
            return self._send(200, {"data": rows[(page - 1) * size: page * size]})
        if url.path == "/v1/cursor":
            if self.headers.get("X-API-Key") != API_KEY:
                return self._send(401, {})
            start = int(q.get("cursor", "0"))
            chunk = Mock.employees[start:start + 2]
            nxt = str(start + 2) if start + 2 < len(Mock.employees) else None
            return self._send(200, {"items": chunk, "next": nxt})
        if url.path == "/v1/secure":
            if self.headers.get("Authorization") != "Bearer access-abc":
                return self._send(401, {})
            return self._send(200, {"data": Mock.employees[:1]})
        if url.path == "/v1/flaky":
            if Mock.flaky_left > 0:
                Mock.flaky_left -= 1
                return self._send(503, {"error": "down"})
            return self._send(200, Mock.employees[:2])
        if url.path == "/v1/redirect":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if url.path == "/v1/big":
            return self._send(200, [{"x": "y" * 1000}] * 3000)
        return self._send(404, {})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
        if self.path == "/oauth/token":
            Mock.token_calls += 1
            auth = self.headers.get("Authorization", "")
            if auth != "Basic " + base64.b64encode(b"client-1:client-secret-xyz").decode():
                return self._send(401, {"error": "invalid_client"})
            if form.get("grant_type") == "client_credentials":
                return self._send(200, {"access_token": "access-abc", "expires_in": 3600})
            if form.get("grant_type") == "authorization_code":
                challenge = Mock.codes.get(form.get("code", ""))
                verifier = form.get("code_verifier", "")
                digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
                if challenge is None or digest != challenge:
                    return self._send(400, {"error": "invalid_grant"})
                return self._send(200, {"access_token": "access-abc", "refresh_token": "refresh-1", "expires_in": 3600})
            if form.get("grant_type") == "refresh_token" and form.get("refresh_token") == "refresh-1":
                return self._send(200, {"access_token": "access-abc", "expires_in": 3600})
            return self._send(400, {"error": "unsupported"})
        return self._send(404, {})


@pytest.fixture(scope="module")
def hrms():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture()
def company(client, hrms):
    Mock.employees = _employees()
    Mock.flaky_left = 0
    Mock.seen_params = []
    headers = _company(client, "sync")
    assert client.post("/api/studio/destinations", headers=headers, json={"host": "127.0.0.1"}).status_code == 200
    return headers


def _drain():
    db = SessionLocal()
    try:
        return studio_worker.drain(db)
    finally:
        db.close()


MAPPING = {
    "record_id": "id",
    "fields": [
        {"target": "employee_id", "source": "EmpNo", "type": "id", "required": True, "pad_to": 5},
        {"target": "employee_name", "source": "Name"},
        {"target": "date_of_joining", "source": "Hired", "type": "date", "formats": ["%d/%m/%Y"]},
        {"target": "work_state", "source": "Loc", "lookup": {"BLR": "Karnataka", "MUM": "Maharashtra"},
         "on_unmatched": "reject"},
        {"target": "employment_type", "cases": [{"when": {"source": "Type", "op": "eq", "value": "C"},
                                                 "value": "Contract"}], "else": "Permanent"},
        {"target": "extra.cost_code", "source": "CostCode"},
    ],
}


def _connection(client, headers, hrms, *, method="api_key_header", **extra):
    body = {"name": f"Mock HRMS {uuid.uuid4().hex[:4]}", "base_url": f"{hrms}/v1", "auth_method": method,
            "auth_config": {"header": "X-API-Key"} if method == "api_key_header" else {},
            "secrets": {"api_key": API_KEY} if method == "api_key_header" else {}, **extra}
    return _data(client.post("/api/studio/connections", headers=headers, json=body))


def _published_mapping(client, headers, key="hrms-employees", spec=None):
    draft = _data(client.post("/api/studio/mappings", headers=headers, json={
        "key": key, "name": "HRMS employees", "object_type": "employee_master", "spec": spec or MAPPING,
        "change_reason": "First version"}))
    return _data(client.post(f"/api/studio/mappings/{draft['id']}/publish", headers=headers))


def _stream(client, headers, conn_id, **body):
    payload = {"name": "Employees", "object_type": "employee_master", "path": "/employees", "records_path": "data",
               "pagination": {"type": "page", "size": 2}, "mapping_key": "hrms-employees",
               "import_options": {"period": "2026-06-01"}, **body}
    return _data(client.post(f"/api/studio/connections/{conn_id}/streams", headers=headers, json=payload))


def _sync(client, headers, stream_id):
    run = _data(client.post(f"/api/studio/streams/{stream_id}/sync", headers=headers))
    _drain()
    return _data(client.get(f"/api/studio/runs/{run['id']}", headers=headers))


# ---------------------------------------------------------------------------
# Destinations
# ---------------------------------------------------------------------------
def test_only_allowed_public_destinations_are_reached(client, hrms, monkeypatch):
    headers = _company(client, "sync-dest")
    r = client.post("/api/studio/connections", headers=headers, json={
        "name": "Unlisted", "base_url": f"{hrms}/v1", "auth_method": "none"})
    assert r.status_code == 400 and "allowed destinations" in r.text
    assert client.post("/api/studio/destinations", headers=headers, json={"host": "https://x.com/path"}).status_code == 400
    assert egress.host_matches("api.example.com", "*.example.com")
    assert not egress.host_matches("example.com", "*.example.com")
    assert not egress.host_matches("evil-example.com", "*.example.com")
    # Private, loopback, CGNAT and metadata addresses are refused in production mode…
    monkeypatch.setattr(settings, "studio_allow_private_destinations", False)
    for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "100.64.0.1", "169.254.169.254",
               "::1", "fd00::1", "::ffff:127.0.0.1", "0.0.0.0"):
        assert not egress.address_allowed(ip), ip
    assert egress.address_allowed("8.8.8.8")
    # …and so is plain http.
    client.post("/api/studio/destinations", headers=headers, json={"host": "127.0.0.1"})
    assert client.post("/api/studio/connections", headers=headers, json={
        "name": "Plain http", "base_url": f"{hrms}/v1", "auth_method": "none"}).status_code == 400
    # Metadata stays refused even where local development relaxes the rest.
    monkeypatch.setattr(settings, "studio_allow_private_destinations", True)
    assert not egress.address_allowed("169.254.169.254")


def test_redirects_are_not_followed_and_size_is_capped(client, company, hrms, monkeypatch):
    conn = _connection(client, company, hrms)
    db = SessionLocal()
    try:
        row = db.get(StudioConnection, uuid.UUID(conn["id"]))
        from app.services.studio import connections as conns

        with pytest.raises(egress.EgressFailed) as exc:
            conns.get_json(db, row, "/redirect")
        assert exc.value.code == "redirect_not_followed"
        monkeypatch.setattr(settings, "studio_http_max_response_mb", 1)
        with pytest.raises(egress.EgressFailed) as exc:
            conns.get_json(db, row, "/big")
        assert exc.value.code == "response_too_large"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------
def test_secrets_are_encrypted_masked_and_never_returned(client, company, hrms, monkeypatch):
    conn = _connection(client, company, hrms)
    text = json.dumps(conn) + json.dumps(_data(client.get(f"/api/studio/connections/{conn['id']}", headers=company)))
    assert API_KEY not in text and conn["secret_hint"]["api_key"] == "••••7777"
    db = SessionLocal()
    try:
        row = db.get(StudioConnection, uuid.UUID(conn["id"]))
        assert API_KEY.encode() not in bytes(row.secret_ciphertext)
        assert vault.unseal(row.secret_ciphertext)["api_key"] == API_KEY
        trail = db.query(AuditEvent).filter(AuditEvent.entity_id == row.entity_id).all()
        assert all(API_KEY not in json.dumps([e.summary, e.detail], default=str) for e in trail)
    finally:
        db.close()
    # Rotating the encryption key: the old key still decrypts, the new one encrypts.
    old_key = base64.urlsafe_b64encode(hashlib.sha256(("studio-secrets:" + settings.jwt_secret).encode()).digest()).decode()
    from cryptography.fernet import Fernet

    new_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "studio_secret_key", f"{new_key},{old_key}")
    db = SessionLocal()
    try:
        row = db.get(StudioConnection, uuid.UUID(conn["id"]))
        assert vault.unseal(row.secret_ciphertext)["api_key"] == API_KEY
        rotated = vault.reencrypt(row.secret_ciphertext)
    finally:
        db.close()
    monkeypatch.setattr(settings, "studio_secret_key", new_key)
    assert vault.unseal(rotated)["api_key"] == API_KEY
    # Production without a key refuses to store anything.
    monkeypatch.setattr(settings, "studio_secret_key", "")
    monkeypatch.setattr(settings, "env", "production")
    with pytest.raises(vault.SecretStoreUnavailable):
        vault.seal({"x": "y"})


def test_extra_headers_cannot_smuggle_credentials(client, company, hrms):
    r = client.post("/api/studio/connections", headers=company, json={
        "name": "Smuggle", "base_url": f"{hrms}/v1", "auth_method": "none",
        "auth_config": {"extra_headers": {"Authorization": "Bearer x"}}})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Connection tests and OAuth
# ---------------------------------------------------------------------------
def test_connection_test_records_health(client, company, hrms):
    conn = _connection(client, company, hrms)
    _published_mapping(client, company)
    stream = _stream(client, company, conn["id"])
    ok = _data(client.post(f"/api/studio/connections/{conn['id']}/test?stream_id={stream['id']}", headers=company))
    assert ok["ok"] and ok["sample_count"] == 2 and "EmpNo" in ok["sample_fields"]
    assert _data(client.get(f"/api/studio/connections/{conn['id']}", headers=company))["health"] == "healthy"
    client.patch(f"/api/studio/connections/{conn['id']}", headers=company, json={"secrets": {"api_key": "wrong-" + "0" * 20}})
    bad = _data(client.post(f"/api/studio/connections/{conn['id']}/test?stream_id={stream['id']}", headers=company))
    assert not bad["ok"] and bad["code"] == "auth_refused"
    got = _data(client.get(f"/api/studio/connections/{conn['id']}", headers=company))
    assert got["health"] == "failing" and got["last_error"]
    # The test is audited against the person who ran it — never the company id
    # standing in for a user (SQLite would not catch that; PostgreSQL's FK does).
    from app.models import User

    with SessionLocal() as db:
        tested = db.query(AuditEvent).filter(AuditEvent.action == "studio.connection.tested").all()
        assert len(tested) == 2
        assert all(db.get(User, e.user_id) is not None and str(e.user_id) != company["X-Entity-Id"] for e in tested)


def test_oauth_client_credentials(client, company, hrms):
    conn = _connection(client, company, hrms, method="oauth2_client_credentials",
                       auth_config={"token_url": f"{hrms}/oauth/token", "client_id": "client-1"},
                       secrets={"client_secret": "client-secret-xyz"})
    _data(client.post(f"/api/studio/connections/{conn['id']}/streams", headers=company, json={
        "name": "Secure", "object_type": "employee_master", "path": "/secure", "records_path": "data"}))
    streams = _data(client.get(f"/api/studio/connections/{conn['id']}", headers=company))["streams"]
    before = Mock.token_calls
    res = _data(client.post(f"/api/studio/connections/{conn['id']}/test?stream_id={streams[0]['id']}", headers=company))
    assert res["ok"], res
    _data(client.post(f"/api/studio/connections/{conn['id']}/test?stream_id={streams[0]['id']}", headers=company))
    assert Mock.token_calls == before + 1, "the token is cached, not fetched per request"


def test_oauth_authorization_code_with_pkce(client, company, hrms):
    conn = _connection(client, company, hrms, method="oauth2_authorization_code",
                       auth_config={"authorize_url": f"{hrms}/oauth/authorize", "token_url": f"{hrms}/oauth/token",
                                    "client_id": "client-1", "scope": "employees.read"},
                       secrets={"client_secret": "client-secret-xyz"})
    assert _data(client.get(f"/api/studio/connections/{conn['id']}", headers=company))["oauth"]["connected"] is False
    start = _data(client.post(f"/api/studio/connections/{conn['id']}/oauth/start", headers=company,
                              json={"redirect_uri": "http://localhost:3000/studio/connections/oauth"}))
    q = {k: v[0] for k, v in parse_qs(urlsplit(start["authorize_url"]).query).items()}
    assert q["code_challenge_method"] == "S256" and q["client_id"] == "client-1" and q["state"]
    # The provider would show consent and redirect back with a code.
    Mock.codes["code-1"] = q["code_challenge"]
    done = _data(client.post("/api/studio/oauth/callback", headers=company, json={"state": q["state"], "code": "code-1"}))
    assert done["oauth"]["connected"] and done["oauth"]["has_refresh_token"]
    # A state is single-use.
    again = client.post("/api/studio/oauth/callback", headers=company, json={"state": q["state"], "code": "code-1"})
    assert again.status_code == 400
    # A forged state is refused.
    assert client.post("/api/studio/oauth/callback", headers=company,
                       json={"state": "x" * 40, "code": "code-1"}).status_code == 400


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------
def test_mapping_preview_names_every_error_by_row(client, company):
    preview = _data(client.post("/api/studio/mappings/preview", headers=company, json={
        "object_type": "employee_master", "spec": MAPPING, "records": _employees()}))
    assert preview["rows"] == 5 and preview["mapped"] == 3 and preview["rejected"] == 2
    first = preview["results"][0]["output"]
    assert first["employee_id"] == "00123" and first["date_of_joining"] == "2024-04-15"
    assert first["work_state"] == "Karnataka" and first["employment_type"] == "Permanent"
    assert first["_extra"] == {"cost_code": "CC-9"} and first["_source_record_id"] == "h-1"
    assert preview["results"][1]["output"]["employment_type"] == "Contract"
    errors = {r["row"]: r["errors"][0] for r in preview["results"] if r["errors"]}
    assert errors[3]["field"] == "date_of_joining" and "31/31/2025" in errors[3]["message"]
    assert errors[4]["field"] == "work_state" and "XYZ" in errors[4]["message"]


def test_mapping_absent_is_not_zero_and_formulas_are_safe(client, company):
    spec = {"fields": [
        {"target": "employee_id", "source": "id", "type": "id", "required": True},
        {"target": "basic", "source": "basic", "type": "currency"},
        {"target": "hra", "formula": "basic_monthly * 12 * 0.4", "type": "number"},
    ]}
    db_components = client.post("/api/components", headers=company, json={"component_name": "Basic", "taxable": True})
    client.post("/api/components", headers=company, json={"component_name": "HRA", "taxable": True})
    assert db_components.status_code in (201, 400)
    out = _data(client.post("/api/studio/mappings/preview", headers=company, json={
        "object_type": "ctc", "spec": spec, "records": [
            {"id": "1", "basic": "₹ 1,20,000", "basic_monthly": "10000"},
            {"id": "2", "basic": "", "basic_monthly": None},
            {"id": "3", "basic": "0"},
        ]}))["results"]
    assert out[0]["output"]["basic"] == 120000 and out[0]["output"]["hra"] == 48000
    assert "basic" not in out[1]["output"] and "hra" not in out[1]["output"], "blank is absent, not zero"
    assert out[2]["output"]["basic"] == 0
    for bad in ("__import__('os')", "basic.__class__", "open('x')"):
        r = client.post("/api/studio/mappings/preview", headers=company, json={
            "object_type": "ctc", "records": [], "spec": {"fields": [
                {"target": "employee_id", "source": "id"}, {"target": "basic", "formula": bad}]}})
        assert r.status_code == 400, bad


def test_attendance_codes_are_counted(client, company):
    spec = {"fields": [{"target": "employee_id", "source": "emp", "type": "id", "required": True},
                       {"target": "attendance", "source": "days", "type": "attendance_codes",
                        "codes": {"P": "present", "A": "lop", "L": "paid_leave", "WO": "weekly_off",
                                  "H": "holiday", "HD": "half_lop"}}]}
    out = _data(client.post("/api/studio/mappings/preview", headers=company, json={
        "object_type": "attendance", "spec": spec,
        "records": [{"emp": "E1", "days": "P P A L WO H HD"}, {"emp": "E2", "days": ["P", "X"]}]}))["results"]
    first = out[0]["output"]
    assert first["calendar_days"] == 7 and first["lop_days"] == 1.5 and first["present_days"] == 2.5
    assert first["paid_days"] == 5.5 and first["paid_leave_days"] == 1 and first["weekly_off_days"] == 1
    assert out[1]["errors"][0]["code"] == "invalid_value" and "X" in out[1]["errors"][0]["message"]


def test_mapping_versions_are_controlled(client, company):
    draft = _data(client.post("/api/studio/mappings", headers=company, json={
        "key": "hrms-employees", "name": "HRMS", "object_type": "employee_master", "spec": MAPPING}))
    assert draft["status"] == "draft" and draft["version"] == 1
    bad = client.post("/api/studio/mappings", headers=company, json={
        "key": "bad-target", "object_type": "employee_master", "spec": {"fields": [
            {"target": "employee_id", "source": "x"}, {"target": "salary_hike", "source": "y"}]}})
    assert bad.status_code == 400 and "salary_hike" in bad.text
    pub = _data(client.post(f"/api/studio/mappings/{draft['id']}/publish", headers=company))
    assert pub["status"] == "published"
    assert client.patch(f"/api/studio/mappings/{draft['id']}", headers=company,
                        json={"spec": MAPPING}).status_code == 409, "a published version is immutable"
    v2 = _data(client.post(f"/api/studio/mappings/{draft['id']}/new-version", headers=company,
                           json={"change_reason": "Pad to 6"}))
    spec2 = json.loads(json.dumps(MAPPING))
    spec2["fields"][0]["pad_to"] = 6
    _data(client.patch(f"/api/studio/mappings/{v2['id']}", headers=company, json={"spec": spec2}))
    diff = _data(client.get(f"/api/studio/mappings/{v2['id']}/compare?other={draft['id']}", headers=company))
    assert [c["target"] for c in diff["changes"]] == ["employee_id"]
    # Where the organisation requires it, the author cannot publish their own mapping.
    assert client.put("/api/org/approval-policy", headers=company, json={"studio_publish_requires_independent_approver": True}).status_code == 200
    refused = client.post(f"/api/studio/mappings/{v2['id']}/publish", headers=company)
    assert refused.status_code == 409 and "someone other" in refused.text
    listed = _data(client.get("/api/studio/mappings", headers=company))
    assert listed[0]["in_force"]["version"] == 1 and len(listed[0]["versions"]) == 2


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------
def test_full_sync_pages_maps_reconciles_and_replays(client, company, hrms):
    conn = _connection(client, company, hrms)
    mapping = _published_mapping(client, company)
    stream = _stream(client, company, conn["id"])
    run = _sync(client, company, stream["id"])
    # 5 records over 3 pages of 2; rows 3 (bad date) and 4 (unknown location) rejected.
    assert run["status"] == "partially_completed", run
    assert run["counts"] == {"received": 5, "accepted": 3, "rejected": 2, "skipped": 0,
                             "created": 3, "updated": 0, "unchanged": 0, "removed": 0}
    assert run["links"]["pages"] == 3 and run["versions"]["mapping_id"] == mapping["id"]
    rej = _data(client.get(f"/api/studio/runs/{run['id']}/rejections", headers=company))["items"]
    assert {(r["row_number"], r["field"]) for r in rej} == {(3, "date_of_joining"), (4, "work_state")}
    # A record the mapping rejects still points back at the source's own id.
    assert {r["row_number"]: r["source_ref"].get("record_id") for r in rej} == {3: "h-3", 4: "h-4"}
    assert all(r["source_ref"]["batch_id"] == run["source"]["batch_id"] for r in rej)
    db = SessionLocal()
    try:
        rec = db.query(EmployeeRecord).filter(EmployeeRecord.entity_id == uuid.UUID(company["X-Entity-Id"]),
                                              EmployeeRecord.employee_id == "00123").one()
        assert rec.lineage["mapping_version"] == "hrms-employees v1" and rec.lineage["record_id"] == "h-1"
        assert rec.extra.get("cost_code") == "CC-9" and rec.cost_center is None, "an extra never becomes a product field"
        s = db.get(StudioStream, uuid.UUID(stream["id"]))
        assert s.checkpoint["last_run_id"] == run["id"]
    finally:
        db.close()
    # Replaying the same data changes nothing and duplicates nothing.
    again = _sync(client, company, stream["id"])
    assert again["counts"]["unchanged"] == 3 and again["counts"]["created"] == 0
    health = _data(client.get(f"/api/studio/connections/{conn['id']}", headers=company))
    assert health["health"] == "healthy" and health["last_success_at"]


def test_retry_uses_the_corrected_mapping_and_never_replaces(client, company, hrms):
    # A replace-mode stream stores 3 of 5; the mapping then learns "XYZ". The
    # retry reads the 2 rejected records with v2, and adds — the 3 already
    # stored must survive, though the first run's mode was "replace".
    from app.services.workforce import master_as_of

    conn = _connection(client, company, hrms)
    first_version = _published_mapping(client, company)
    stream = _stream(client, company, conn["id"], import_options={"period": "2026-06-01", "mode": "replace"})
    run = _sync(client, company, stream["id"])
    assert run["counts"]["accepted"] == 3 and run["counts"]["rejected"] == 2
    v2 = _data(client.post(f"/api/studio/mappings/{first_version['id']}/new-version", headers=company,
                           json={"change_reason": "Add XYZ"}))
    spec2 = json.loads(json.dumps(MAPPING))
    spec2["fields"][3]["lookup"]["XYZ"] = "Karnataka"
    _data(client.patch(f"/api/studio/mappings/{v2['id']}", headers=company, json={"spec": spec2}))
    _data(client.post(f"/api/studio/mappings/{v2['id']}/publish", headers=company))

    retry = _data(client.post(f"/api/studio/runs/{run['id']}/retry-rejected", headers=company))
    _drain()
    done = _data(client.get(f"/api/studio/runs/{retry['id']}", headers=company))
    assert done["versions"]["mapping"] == "hrms-employees v2" and done["options"]["mode"] == "upsert"
    assert done["counts"]["received"] == 2 and done["counts"]["accepted"] == 1 and done["counts"]["rejected"] == 1
    db = SessionLocal()
    try:
        stored = set(master_as_of(db, uuid.UUID(company["X-Entity-Id"]), datetime(2026, 6, 1).date()))
    finally:
        db.close()
    assert stored == {"00123", "00124", "00126", "00127"}, stored


def test_incremental_sync_advances_only_after_commit(client, company, hrms, monkeypatch):
    conn = _connection(client, company, hrms)
    _published_mapping(client, company)
    stream = _stream(client, company, conn["id"], sync_mode="incremental", watermark_field="updated_at",
                     watermark_param="modified_since")
    first = _sync(client, company, stream["id"])
    assert first["counts"]["received"] == 5
    db = SessionLocal()
    try:
        assert db.get(StudioStream, uuid.UUID(stream["id"])).checkpoint["watermark"] == "2026-06-05T10:00:00Z"
    finally:
        db.close()
    # One record changes at the source.
    Mock.employees[0] = {**Mock.employees[0], "Name": "Asha R (synthetic)", "updated_at": "2026-06-10T09:00:00Z"}
    # A crash after fetching but before the commit leaves the checkpoint where it was.
    from app.services.studio import imports

    real = imports.ingest_records
    monkeypatch.setattr(imports, "ingest_records", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash")))
    monkeypatch.setattr(studio_worker, "BACKOFF_SECONDS", 0)
    crashed = _data(client.post(f"/api/studio/streams/{stream['id']}/sync", headers=company))
    db = SessionLocal()
    try:
        studio_worker.run_once(db, "w")
        assert db.get(StudioStream, uuid.UUID(stream["id"])).checkpoint["watermark"] == "2026-06-05T10:00:00Z"
    finally:
        db.close()
    monkeypatch.setattr(imports, "ingest_records", real)
    _drain()
    done = _data(client.get(f"/api/studio/runs/{crashed['id']}", headers=company))
    assert done["status"] == "completed" and done["attempts"] == 2
    assert done["counts"] == {"received": 1, "accepted": 1, "rejected": 0, "skipped": 0,
                              "created": 0, "updated": 1, "unchanged": 0, "removed": 0}
    assert Mock.seen_params[-1]["modified_since"] == "2026-06-05T10:00:00Z"
    db = SessionLocal()
    try:
        assert db.get(StudioStream, uuid.UUID(stream["id"])).checkpoint["watermark"] == "2026-06-10T09:00:00Z"
    finally:
        db.close()


def test_cursor_pagination_and_deletions_are_reported_not_applied(client, company, hrms):
    conn = _connection(client, company, hrms)
    spec = {"fields": [{"target": "employee_id", "source": "EmpNo", "type": "id", "required": True},
                       {"target": "employee_name", "source": "Name"}]}
    _published_mapping(client, company, key="plain", spec=spec)
    stream = _stream(client, company, conn["id"], path="/cursor", records_path="items", mapping_key="plain",
                     pagination={"type": "cursor", "cursor_path": "next", "param": "cursor"},
                     import_options={"period": "2026-06-01", "deletions": "report"})
    first = _sync(client, company, stream["id"])
    assert first["counts"]["created"] == 5 and first["links"]["pages"] == 3
    Mock.employees = Mock.employees[:3]
    second = _sync(client, company, stream["id"])
    assert second["links"]["missing_in_source"] == {"count": 2, "employee_ids": ["126", "127"]}
    assert second["counts"]["removed"] == 0
    db = SessionLocal()
    try:
        n = db.query(EmployeeRecord).filter(EmployeeRecord.entity_id == uuid.UUID(company["X-Entity-Id"])).count()
    finally:
        db.close()
    assert n == 5, "absence from the source is reported, never turned into a deletion"


def test_provider_outage_retries_with_backoff_then_fails_clearly(client, company, hrms, monkeypatch):
    conn = _connection(client, company, hrms)
    spec = {"fields": [{"target": "employee_id", "source": "EmpNo", "type": "id", "required": True}]}
    _published_mapping(client, company, key="flaky", spec=spec)
    stream = _stream(client, company, conn["id"], path="/flaky", records_path="", mapping_key="flaky",
                     pagination={"type": "none"}, max_attempts=3)
    Mock.flaky_left = 2
    run = _data(client.post(f"/api/studio/streams/{stream['id']}/sync", headers=company))
    _drain()
    queued = _data(client.get(f"/api/studio/runs/{run['id']}", headers=company))
    assert queued["status"] == "queued" and "Retrying in 30 s" in queued["error"]["message"], "backoff, not a hot loop"
    monkeypatch.setattr(studio_worker, "BACKOFF_SECONDS", 0)
    db = SessionLocal()
    try:
        from app.models import StudioRun

        row = db.get(StudioRun, uuid.UUID(run["id"]))
        row.queued_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    _drain()
    done = _data(client.get(f"/api/studio/runs/{run['id']}", headers=company))
    assert done["status"] == "completed" and done["attempts"] == 3 and done["counts"]["created"] == 2
    Mock.flaky_left = 99
    run2 = _data(client.post(f"/api/studio/streams/{stream['id']}/sync", headers=company))
    _drain()
    failed = _data(client.get(f"/api/studio/runs/{run2['id']}", headers=company))
    assert failed["status"] == "failed" and failed["attempts"] == 3
    assert "checkpoint did not move" in failed["error"]["recommended_action"]
    assert _data(client.get(f"/api/studio/connections/{conn['id']}", headers=company))["health"] == "failing"


def test_schedules_fire_once_when_due(client, company, hrms):
    now = datetime(2026, 6, 15, 20, 0, tzinfo=UTC)  # 01:30 IST on the 16th
    daily = sync_svc.check_schedule({"every": "day", "at": "02:00", "timezone": "Asia/Kolkata"})
    assert sync_svc.next_run(daily, now) == datetime(2026, 6, 15, 20, 30, tzinfo=UTC)
    weekly = sync_svc.check_schedule({"every": "week", "at": "06:00", "weekday": 0, "timezone": "Asia/Kolkata"})
    assert sync_svc.next_run(weekly, now).astimezone(UTC) == datetime(2026, 6, 22, 0, 30, tzinfo=UTC)
    with pytest.raises(sync_svc.SyncError):
        sync_svc.check_schedule({"every": "minute"})
    conn = _connection(client, company, hrms)
    _published_mapping(client, company)
    stream = _stream(client, company, conn["id"], schedule={"every": "day", "at": "02:00"})
    assert stream["next_run_at"]
    db = SessionLocal()
    try:
        row = db.get(StudioStream, uuid.UUID(stream["id"]))
        row.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
        assert sync_svc.schedule_due(db) == 1
        assert sync_svc.schedule_due(db) == 0, "a fired schedule moves on; it does not fire twice"
        assert db.get(StudioStream, uuid.UUID(stream["id"])).next_run_at > datetime.now(UTC).replace(tzinfo=None) \
            if db.bind.dialect.name == "sqlite" else True
    finally:
        db.close()
    _drain()
    runs = _data(client.get("/api/studio/runs?kind=sync", headers=company))["items"]
    assert len(runs) == 1 and runs[0]["trigger"] == "schedule" and runs[0]["counts"]["created"] == 3


def test_a_file_imported_with_a_mapping(client, company):
    mapping = _published_mapping(client, company)
    csv = "EmpNo,Name,Hired,Loc,Type,id\n0042,Priya (synthetic),01/07/2025,BLR,P,f-1\n0043,Bad,99/99/2025,BLR,P,f-2\n"
    run = _data(client.post("/api/studio/imports", headers=company,
                            files={"file": ("people.csv", io.BytesIO(csv.encode()), "text/csv")},
                            data={"meta": json.dumps({"mapping_id": mapping["id"], "effective_from": "2026-06-01"})}))
    _drain()
    done = _data(client.get(f"/api/studio/runs/{run['id']}", headers=company))
    assert done["trigger"] == "ui" and done["actor"]["type"] == "user"
    assert done["counts"]["created"] == 1 and done["counts"]["rejected"] == 1
    db = SessionLocal()
    try:
        rec = db.query(EmployeeRecord).filter(EmployeeRecord.entity_id == uuid.UUID(company["X-Entity-Id"])).one()
        assert rec.employee_id == "00042", "read as text, then padded by the mapping — never 42"
    finally:
        db.close()


def test_the_api_can_import_through_a_mapping(client, company):
    _published_mapping(client, company)
    account = _data(client.post("/api/studio/service-accounts", headers=company, json={
        "name": "Mapped feed", "entity_ids": [company["X-Entity-Id"]], "scopes": ["imports:write", "imports:read"]}))
    key = _data(client.post(f"/api/studio/service-accounts/{account['id']}/keys", headers=company,
                            json={"label": "t", "expires_in_days": 5}))["key"]
    h = {"Authorization": f"Bearer {key}", "Idempotency-Key": uuid.uuid4().hex}
    body = {"effective_from": "2026-06-01", "mapping_key": "hrms-employees", "records": _employees()}
    check = client.post("/api/integration/v1/imports/employee_master/check", headers=h, json=body).json()["data"]
    assert check["counts"]["accepted"] == 3 and check["counts"]["rejected"] == 2 and check["counts"]["received"] == 5
    run = client.post("/api/integration/v1/imports/employee_master", headers=h, json=body).json()["data"]
    _drain()
    done = client.get(f"/api/integration/v1/imports/{run['id']}", headers=h).json()["data"]
    assert done["counts"]["created"] == 3 and done["versions"]["mapping"] == "hrms-employees v1"


def test_connections_are_company_scoped(client, company, hrms):
    conn = _connection(client, company, hrms)
    stranger = _company(client, "sync-other")
    assert client.get(f"/api/studio/connections/{conn['id']}", headers=stranger).status_code == 404
    assert client.post(f"/api/studio/connections/{conn['id']}/test", headers=stranger).status_code == 404
    assert _data(client.get("/api/studio/connections", headers=stranger)) == []
