"""
Cross-company object access, swept across every route.

Company B is filled with one of nearly everything the product stores: a
validated register with findings, comments and an attachment, a saved report
with a generated file and a schedule, a minimum-wage rate, a dated statutory
change, and in Studio a service account and key, a connection with a stream, a
mapping, a sync run, a webhook, an inbound endpoint and a workflow.

Every identifier B's own list pages return is then replayed, as company A,
against every route that takes an identifier — read and write alike. A company
may reach its own objects only: any 2xx answer to A naming B's object is a
leak, and the test names the route and the identifier.

The route list is read from the application itself, so a route added tomorrow
is swept the day it is added. The only exemptions are identifiers that are not
company data at all, listed with the reason.
"""
from __future__ import annotations

import io
import re
import uuid
from typing import Any

import pytest

from app.main import app
from tests.test_coverage import BASE_ROWS, _register, _run
from tests.test_run_history import _company, _data
from tests.test_studio_sync import (  # noqa: F401 — hrms is a fixture
    Mock,
    _connection,
    _employees,
    _published_mapping,
    _stream,
    _sync,
    hrms,
)

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

#: Routes whose path identifier is not company data. Each needs a reason.
NOT_COMPANY_DATA = {
    # A platform administrator's own screens; they are guarded by the platform
    # portal and by support grants, which tests/test_support_access.py sweeps.
    "/api/admin/",
    # Your own membership and invitation screens act on the caller's own
    # organisation by construction; test_invitations.py covers foreign ids.
}


def _api_routes() -> list[tuple[str, set[str]]]:
    """(path, methods) for every route under /api, on either way FastAPI lists them.

    Newer FastAPI keeps an included router as one ``_IncludedRouter`` entry; older
    releases flatten it into ``APIRoute`` objects. requirements.txt sets only a
    minimum version, so the sweep must read both or it reads nothing at all.
    """
    inc = next((x for x in app.routes
                if type(x).__name__ == "_IncludedRouter" and x.include_context.prefix == "/api"), None)
    if inc is not None:
        return [(c.path, set(c.original_route.methods)) for c in inc.effective_route_contexts()]
    return [(r.path, set(r.methods)) for r in app.routes
            if type(r).__name__ == "APIRoute" and r.path.startswith("/api/") and not r.path.startswith("/api/v1/")]


def _routes() -> list[tuple[str, str]]:
    out = []
    for path, methods in _api_routes():
        if "{" not in path or any(path.startswith(p) for p in NOT_COMPANY_DATA):
            continue
        for method in methods:
            if method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                out.append((method, path))
    return sorted(out, key=lambda m: (m[0] != "GET", m[1]))  # reads first, then writes


def _walk(value: Any, into: dict[str, set[str]], key: str = "") -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _walk(v, into, k)
    elif isinstance(value, list):
        for v in value:
            _walk(v, into, key)
    elif isinstance(value, str) and (UUID.match(value) or HEX64.match(value)):
        into.setdefault(key, set()).add(value)


def _populate(client, headers, hrms) -> list[str]:
    """One of nearly every kind of object, in company B. Returns what failed to create."""
    failed: list[str] = []
    real_post, real_put = client.post, client.put

    def post(url, **kw):
        r = real_post(url, **kw)
        if r.status_code >= 300:
            failed.append(f"POST {url} -> {r.status_code} {r.text[:160]}")
        return r

    def put(url, **kw):
        r = real_put(url, **kw)
        if r.status_code >= 300:
            failed.append(f"PUT {url} -> {r.status_code} {r.text[:160]}")
        return r

    client = type("C", (), {"post": staticmethod(post), "put": staticmethod(put), "get": client.get})()
    run_id = _run(client, headers, _register(BASE_ROWS))
    findings = _data(client.get(f"/api/validation/runs/{run_id}/findings?page_size=5", headers=headers))
    items = findings.get("items") or findings.get("findings") or []
    if items:
        fp = items[0].get("fingerprint")
        if fp:
            client.post(f"/api/findings/{fp}/comments", headers=headers, json={"body": "B's private note"})
            client.post(f"/api/findings/{fp}/attachments", headers=headers,
                        files={"file": ("evidence.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
    report = client.post("/api/reports/builder/saved", headers=headers, json={
        "name": "B report", "visibility": "private",
        "specification": {"dataset": "payroll_cost", "dimension": "department",
                          "fields": ["period", "dimension", "ctc"],
                          "date_from": "2026-06-01", "date_to": "2026-06-01"}})
    if report.status_code == 200:
        rid = report.json()["data"]["id"]
        client.post(f"/api/reports/builder/saved/{rid}/jobs", headers=headers, json={"format": "xlsx"})
        client.put(f"/api/reports/builder/saved/{rid}/schedule", headers=headers,
                   json={"frequency": "monthly", "day": 5})
    client.post("/api/minimum-wage/rates", headers=headers, json={
        "state": "Karnataka", "skill_category": "Unskilled", "monthly_rate": 12000,
        "effective_from": "2026-04-01"})
    base = _data(client.get("/api/config/statutory", headers=headers))
    client.post("/api/config/statutory/versions", headers=headers, json={
        "effective_from": "2026-09-01", "config": {k: base[k] for k in ("pf", "esic", "component_mapping")}})
    # Studio
    client.post("/api/studio/destinations", headers=headers, json={"host": "127.0.0.1"})
    account = client.post("/api/studio/service-accounts", headers=headers, json={
        "name": f"B feed {uuid.uuid4().hex[:4]}", "environment": "production",
        "entity_ids": [headers["X-Entity-Id"]], "scopes": ["imports:write"]})
    if account.status_code == 200:
        aid = account.json()["data"]["id"]
        client.post(f"/api/studio/service-accounts/{aid}/keys", headers=headers,
                    json={"label": "b", "expires_in_days": 30})
    Mock.employees = _employees()
    conn = _connection(client, headers, hrms)
    _published_mapping(client, headers)
    stream = _stream(client, headers, conn["id"])
    _sync(client, headers, stream["id"])
    client.post("/api/studio/webhooks", headers=headers, json={
        "name": "B hook", "url": f"{hrms}/hook", "events": ["import.completed"]})
    client.post("/api/studio/inbound", headers=headers, json={
        "name": "B inbound", "object_type": "employee_master", "options": {"effective_from": "2026-06-01"}})
    me = _data(client.get("/api/auth/me", headers=headers))["id"]
    client.post("/api/studio/workflows", headers=headers, json={
        "name": f"B flow {uuid.uuid4().hex[:4]}",
        "definition": {"trigger": {"type": "manual"}, "actions": [
            {"type": "notify", "params": {"user_ids": [me], "title": "done", "body": "done"}}]}})
    return failed


def _collect(client, headers) -> dict[str, set[str]]:
    """Every identifier B's own GET routes hand back."""
    found: dict[str, set[str]] = {}
    spec = app.openapi()
    for path, ops in spec["paths"].items():
        if path.startswith("/api/v1") or "{" in path or "get" not in ops:
            continue
        if any(p.get("required") for p in ops["get"].get("parameters", [])):
            continue
        r = client.get(path, headers=headers)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
            _walk(r.json().get("data"), found)
    return found


@pytest.fixture()
def _studio_ready(monkeypatch):
    from app.services.studio import ratelimit

    ratelimit.reset()


def test_no_route_hands_one_company_another_companys_object(client, hrms, _studio_ready):
    b = _company(client, "sweep-b")
    a = _company(client, "sweep-a")
    failed = _populate(client, b, hrms)
    assert not failed, "setup did not create everything:\n" + "\n".join(failed)
    ids = _collect(client, b)
    own = _collect(client, a)
    # Only B's: an identifier A can see for itself (a shared reference row, a
    # dataset key) proves nothing about isolation.
    mine = set().union(*own.values()) if own else set()
    theirs = {v for vals in ids.values() for v in vals} - mine
    theirs.discard(b["X-Entity-Id"])  # covered by the entity-header tests
    assert len(theirs) > 40, f"too few of B's objects to be a meaningful sweep: {len(theirs)}"

    from fastapi.testclient import TestClient

    # Every answer is read, 500s included: a route that crashes on a foreign
    # identifier is a defect this sweep should list, not stop at.
    probe = TestClient(app, raise_server_exceptions=False)
    leaks, crashes = [], []
    routes = _routes()
    for method, path in routes:
        params = re.findall(r"{([^}]+)}", path)
        for value in theirs:
            url = path
            for p in params:
                url = url.replace("{" + p + "}", value)
            r = probe.request(method, url, headers=a, json={} if method != "GET" else None)
            if 200 <= r.status_code < 300:
                leaks.append(f"{method} {path} with {value} -> {r.status_code}")
            elif r.status_code >= 500:
                crashes.append(f"{method} {path}")
    print(f"swept {len(routes)} routes x {len(theirs)} of company B's identifiers "
          f"({len(routes) * len(theirs)} requests); kinds seen: {sorted(ids)}")
    assert not leaks, "cross-company access:\n" + "\n".join(leaks[:50])
    assert not crashes, "server errors on a foreign identifier:\n" + "\n".join(sorted(set(crashes)))

    # And A naming B's company outright is refused everywhere a company is resolved.
    stranger = {**a, "X-Entity-Id": b["X-Entity-Id"]}
    for path in ("/api/validation/runs", "/api/components", "/api/reports/builder/saved",
                 "/api/studio/connections", "/api/bi/cost-analysis"):
        assert client.get(path, headers=stranger).status_code == 404, path
