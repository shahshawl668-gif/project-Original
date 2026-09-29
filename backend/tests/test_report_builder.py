"""PeopleOps Reports builder: scope, arithmetic safety and shared BI totals."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services import report_builder
from test_reports_and_audit import _dims, _register, workspace  # noqa: F401


def _spec(**overrides):
    return {
        "dataset": "payroll_cost", "dimension": "department",
        "fields": ["period", "dimension", "headcount", "gross", "ctc"],
        "date_from": "2026-04-01", "date_to": "2026-04-01",
        **overrides,
    }


def test_builder_rejects_code_and_unapproved_fields():
    for expression in ('__import__("os").system("id")', "gross.__class__", "gross ** 2"):
        with pytest.raises(ValueError):
            report_builder.validate(_spec(calculations=[
                {"key": "calc_bad", "expression": expression}
            ]))
    with pytest.raises(ValueError):
        report_builder.validate(_spec(fields=["employee_name"]))
    with pytest.raises(ValueError):
        report_builder.validate(_spec(dimension="unknown"))


def test_preview_reconciles_to_existing_bi_and_distinguishes_empty(client, workspace):
    entity, user, headers = workspace
    missing = client.post("/api/reports/builder/preview", json={"specification": _spec()}, headers=headers)
    assert missing.status_code == 200
    assert missing.json()["data"]["status"] == "missing_data"
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "001", "dimensions": _dims(department="Store"), "components": {"basic": 10000}},
        {"employee_id": "002", "dimensions": _dims(department="Office"), "components": {"basic": 20000}},
    ])
    response = client.post("/api/reports/builder/preview", json={"specification": _spec(
        calculations=[{"key": "calc_half", "expression": "gross / 2"}],
        fields=["period", "dimension", "gross", "calc_half", "ctc"],
    )}, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "ok" and data["record_count"] == 2
    assert all(row["calc_half"] == row["gross"] / 2 for row in data["rows"])
    screen = client.get("/api/bi/cost-analysis?date_from=2026-04-01&date_to=2026-04-01", headers=headers)
    assert screen.status_code == 200
    assert data["control_totals"]["ctc"] == screen.json()["data"]["totals"]["ctc"]
    assert client.post("/api/reports/builder/preview", json={"specification": _spec(
        filters={"department": ["No match"]}
    )}, headers=headers).json()["data"]["status"] == "no_matching_records"


def test_saved_definition_version_and_company_isolation(client, workspace):
    _, _, headers = workspace
    body = {"name": "Store cost", "specification": _spec(), "visibility": "private", "status": "draft"}
    created = client.post("/api/reports/builder/saved", json=body, headers=headers)
    assert created.status_code == 200, created.text
    report = created.json()["data"]
    report_id = report["id"]
    updated = client.put(f"/api/reports/builder/saved/{report_id}", json={**body, "name": "Store cost updated"}, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["data"]["version"] == 2
    versions = client.get(f"/api/reports/builder/saved/{report_id}/versions", headers=headers).json()["data"]["versions"]
    assert [v["version"] for v in versions] == [2, 1]
    other = client.post("/api/org/entities", json={"name": "Separate company"}, headers=headers).json()["data"]["id"]
    other_headers = {**headers, "X-Entity-Id": other}
    assert client.get(f"/api/reports/builder/saved/{report_id}", headers=other_headers).status_code == 404
    assert client.get("/api/reports/builder/saved", headers=other_headers).json()["data"]["reports"] == []
