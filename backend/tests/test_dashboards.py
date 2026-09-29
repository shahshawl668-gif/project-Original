"""
Configurable dashboards: tiles answer from the same services as the pages,
custom KPIs are safe formulas, visibility and roles are enforced, companies are
isolated, and every template works.

Fixture: the coverage register (tests/test_coverage.BASE_ROWS) for June 2026 —
three employees, E002's PF ₹100 short — validated through the job queue.
"""
from __future__ import annotations

import uuid

import pytest

from tests.test_coverage import BASE_ROWS, _register, _run
from tests.test_run_history import PASSWORD, PERIOD, _company, _data, _empty_queue  # noqa: F401

ALL = {"preset": "all"}


def _member(client, owner_headers, role: str) -> dict:
    email = f"dash-{role}-{uuid.uuid4().hex[:6]}@dash-example.com"
    inv = _data(client.post("/api/org/invitations", headers=owner_headers, json={"email": email, "role": role}))
    joined = client.post("/api/org/invitations/register", json={"token": inv["token"], "password": PASSWORD})
    assert joined.status_code == 200, joined.text
    return {"Authorization": f"Bearer {joined.json()['data']['access_token']}", "X-Entity-Id": owner_headers["X-Entity-Id"]}


@pytest.fixture()
def company(client):
    headers = _company(client, "dash")
    headers["_run"] = _run(client, headers, _register(BASE_ROWS))
    return headers


def H(headers):
    return {k: v for k, v in headers.items() if not k.startswith("_")}


def q(client, headers, **body):
    body.setdefault("period", ALL)
    return client.post("/api/dashboards/query", headers=H(headers), json=body)


def test_catalogue(client, company):
    cat = _data(client.get("/api/dashboards/datasets", headers=H(company)))
    assert {d["key"] for d in cat["datasets"]} == {"payroll_cost", "headcount", "findings", "validation", "budget"}
    assert len(cat["templates"]) == 8
    cost = next(d for d in cat["datasets"] if d["key"] == "payroll_cost")
    cph = next(m for m in cost["metrics"] if m["key"] == "cost_per_head")
    assert "person-months" in cph["definition"]


def test_a_tile_agrees_with_the_page_it_drills_into(client, company):
    page = _data(client.get("/api/bi/cost-analysis?group_by=department", headers=H(company)))
    tile = _data(q(client, company, dataset="payroll_cost", metric="ctc", breakdown="period"))
    assert tile["status"] == "ok"
    assert [r["key"] for r in tile["rows"]] == ["2026-06-01"]
    assert tile["total"] == page["totals"]["ctc"] == tile["rows"][0]["value"]
    assert tile["basis"]["periods_with_register"] == ["2026-06-01"]
    by_dept = _data(q(client, company, dataset="payroll_cost", metric="ctc", breakdown="department"))
    assert round(sum(r["value"] for r in by_dept["rows"]), 2) == by_dept["total"]
    assert by_dept["rows"][0]["drill"].startswith("/cost?view=overview&group_by=department&f_department=")
    cph = _data(q(client, company, dataset="payroll_cost", metric="cost_per_head", breakdown="period"))
    assert cph["total"] == page["totals"]["cost_per_head"] == round(page["totals"]["ctc"] / 3, 2)


def test_no_register_is_no_data_not_zero(client, company):
    other = _company(client, "dash-empty")
    tile = _data(q(client, other, dataset="payroll_cost", metric="ctc"))
    assert tile["status"] == "no_data" and tile["total"] is None and tile["rows"] == []


def test_findings_and_validation_tiles(client, company):
    work = _data(client.get("/api/findings/worklist?page_size=1", headers=H(company)))
    tile = _data(q(client, company, dataset="findings", metric="issues", breakdown="rule"))
    assert tile["total"] == work["counts"]["open"] + work["counts"]["acknowledged"]
    stat = next(r for r in tile["rows"] if r["key"] == "STAT-001")
    assert stat["value"] == 1 and stat["drill"] == "/payroll/issues?rule_id=STAT-001&state="
    run = _data(client.get(f"/api/validation/runs/{company['_run']}", headers=H(company)))
    cov = _data(q(client, company, dataset="validation", metric="coverage_pct"))
    assert cov["rows"][0]["value"] == run["summary"]["coverage"]["coverage_pct"]
    assert cov["rows"][0]["drill"] == f"/payroll/results?run={company['_run']}"


def test_bad_questions_are_refused(client, company):
    assert q(client, company, dataset="nope", metric="ctc").status_code == 400
    assert q(client, company, dataset="payroll_cost", metric="nope").status_code == 400
    assert q(client, company, dataset="validation", metric="failed_checks", breakdown="department").status_code == 400
    assert q(client, company, dataset="findings", metric="issues", filters={"department": ["X"]}).status_code == 400


def test_custom_kpi_is_a_safe_formula(client, company):
    k = _data(client.post("/api/kpis", headers=H(company), json={
        "name": "Employer share of gross", "dataset": "payroll_cost",
        "formula": "employer_cost / gross * 100", "unit": "pct"}))
    page = _data(client.get("/api/bi/cost-analysis?group_by=department", headers=H(company)))["totals"]
    tile = _data(q(client, company, dataset="payroll_cost", kpi_id=k["id"], breakdown="department"))
    assert tile["metric"]["custom"] is True
    assert tile["total"] == round(page["employer_cost"] / page["gross"] * 100, 4)
    for bad in ("__import__('os').system('id')", "gross.__class__", "bonus_pool / 2", "open('x')"):
        r = client.post("/api/kpis", headers=H(company), json={"name": "x", "dataset": "payroll_cost", "formula": bad})
        assert r.status_code == 400, bad
    # A KPI whose inputs are zero where it divides is unknown, not zero.
    zero = _data(client.post("/api/kpis", headers=H(company), json={
        "name": "Exposure per critical", "dataset": "findings", "formula": "exposure / (critical - critical)"}))
    assert _data(q(client, company, dataset="findings", kpi_id=zero["id"], breakdown="severity"))["total"] is None


def test_visibility_roles_and_isolation(client, company):
    viewer = _member(client, company, "viewer")
    analyst = _member(client, company, "analyst")
    manager = _member(client, company, "manager")
    tile = {"title": "CTC", "dataset": "payroll_cost", "metric": "ctc", "breakdown": "period", "chart": "bar"}
    mine = _data(client.post("/api/dashboards", headers=H(company), json={"name": "Owner's private", "tiles": [tile]}))
    shared = _data(client.post("/api/dashboards", headers=H(company),
                               json={"name": "Group board", "visibility": "shared", "tiles": [tile]}))
    seen = {d["name"] for d in _data(client.get("/api/dashboards", headers=viewer))}
    assert seen == {"Group board"}
    assert client.get(f"/api/dashboards/{mine['id']}", headers=viewer).status_code == 404
    # A viewer keeps private boards but cannot share one.
    assert client.post("/api/dashboards", headers=viewer, json={"name": "Mine", "tiles": [tile]}).status_code == 200
    assert client.post("/api/dashboards", headers=viewer,
                       json={"name": "Share", "visibility": "shared", "tiles": [tile]}).status_code == 403
    # An analyst cannot change someone else's shared board; a manager can.
    body = {"name": "Group board v2", "visibility": "shared", "tiles": [tile]}
    assert client.put(f"/api/dashboards/{shared['id']}", headers=analyst, json=body).status_code == 403
    assert client.put(f"/api/dashboards/{shared['id']}", headers=manager, json=body).status_code == 200
    # Another company sees none of it.
    stranger = _company(client, "dash-x")
    assert _data(client.get("/api/dashboards", headers=stranger)) == []
    assert client.get(f"/api/dashboards/{shared['id']}", headers=stranger).status_code == 404
    assert client.delete(f"/api/dashboards/{shared['id']}", headers=stranger).status_code == 404


def test_a_shared_dashboard_cannot_use_a_private_kpi(client, company):
    k = _data(client.post("/api/kpis", headers=H(company), json={
        "name": "Net share", "dataset": "payroll_cost", "formula": "net / gross * 100", "unit": "pct"}))
    tile = {"title": "Net share", "dataset": "payroll_cost", "kpi_id": k["id"], "breakdown": "period", "chart": "kpi"}
    r = client.post("/api/dashboards", headers=H(company), json={"name": "Shared", "visibility": "shared", "tiles": [tile]})
    assert r.status_code == 400 and "private KPI" in r.text
    private = _data(client.post("/api/dashboards", headers=H(company), json={"name": "Mine", "tiles": [tile]}))
    assert client.delete(f"/api/kpis/{k['id']}", headers=H(company)).status_code == 409
    client.delete(f"/api/dashboards/{private['id']}", headers=H(company))
    assert client.delete(f"/api/kpis/{k['id']}", headers=H(company)).status_code == 200


def test_every_template_builds_and_every_tile_answers(client, company):
    cat = _data(client.get("/api/dashboards/datasets", headers=H(company)))
    for t in cat["templates"]:
        d = _data(client.post("/api/dashboards/from-template", headers=H(company), json={"template": t["key"]}))
        assert d["visibility"] == "private" and len(d["layout"]["tiles"]) == t["tiles"]
        for tile in d["layout"]["tiles"]:
            r = q(client, company, dataset=tile["dataset"], metric=tile["metric"], breakdown=tile["breakdown"],
                  granularity=tile["granularity"], filters=tile["filters"])
            assert r.status_code == 200, (t["key"], tile["title"], r.text)
            assert r.json()["data"]["status"] in ("ok", "empty", "no_data", "no_budget")
