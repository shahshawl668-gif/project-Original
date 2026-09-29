"""PeopleOps Reports builder: scope, arithmetic safety and shared BI totals."""
from __future__ import annotations

import io
import time
from datetime import date

import pytest

from app.services import report_builder
from tests.test_reports_and_audit import _dims, _register, workspace  # noqa: F401


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


def test_saved_excel_exports_every_row_and_typed_period(client, workspace, monkeypatch):
    from openpyxl import load_workbook

    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "dimensions": _dims(department="A"), "components": {"basic": 10000}},
        {"employee_id": "E2", "dimensions": _dims(department="B"), "components": {"basic": 12000}},
    ])
    created = client.post("/api/reports/builder/saved", json={
        "name": "All departments", "specification": _spec(), "visibility": "private"
    }, headers=headers)
    assert created.status_code == 200, created.text
    report_id = created.json()["data"]["id"]
    monkeypatch.setattr(report_builder, "MAX_PREVIEW_ROWS", 1)
    payload = client.get(f"/api/reports/builder/saved/{report_id}.xlsx", headers=headers)
    assert payload.status_code == 200, payload.text[:200] if payload.status_code != 200 else ""
    wb = load_workbook(io.BytesIO(payload.content))
    assert wb.sheetnames[:3] == ["About this report", "Summary", "Details"]
    assert wb["Details"].max_row == 3
    assert wb["Details"]["A2"].value.date() == date(2026, 4, 1)
    info = {row[0]: row[1] for row in wb["About this report"].values if row[0]}
    assert info["Record count"] == 2
    assert info["Definition version"] == 1


def test_report_name_cannot_inject_spreadsheet_formula(client, workspace):
    from openpyxl import load_workbook

    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "dimensions": _dims(department="A")}
    ])
    created = client.post("/api/reports/builder/saved", json={
        "name": '=HYPERLINK("https://example.invalid")',
        "specification": _spec(), "visibility": "private"
    }, headers=headers)
    assert created.status_code == 200
    payload = client.get(f"/api/reports/builder/saved/{created.json()['data']['id']}.xlsx", headers=headers)
    assert payload.status_code == 200
    wb = load_workbook(io.BytesIO(payload.content))
    names = [row[1] for row in wb["About this report"].values if row[0] == "Report"]
    assert names[0].startswith("'=")
    assert all(cell.data_type != "f" for row in wb["About this report"] for cell in row)


def test_generated_job_keeps_fixed_file_and_checks_company_on_download(client, workspace):
    from app.services import report_jobs

    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "dimensions": _dims(department="A"), "components": {"basic": 10000}}
    ])
    created = client.post("/api/reports/builder/saved", json={
        "name": "Monthly cost", "specification": _spec(), "visibility": "private"
    }, headers=headers)
    report_id = created.json()["data"]["id"]
    queued = client.post(f"/api/reports/builder/saved/{report_id}/jobs", headers=headers)
    assert queued.status_code == 200, queued.text
    job_id = queued.json()["data"]["id"]
    duplicate = client.post(f"/api/reports/builder/saved/{report_id}/jobs", headers=headers)
    assert duplicate.status_code == 200 and duplicate.json()["data"]["id"] == job_id
    for _ in range(40):
        state = client.get(f"/api/reports/builder/jobs/{job_id}", headers=headers).json()["data"]
        if state["state"] in ("succeeded", "failed"):
            break
        report_jobs.run_once()
        time.sleep(0.05)
    assert state["state"] == "succeeded", state
    assert state["definition_version"] == 1
    assert state["record_count"] == 1
    assert state["source_references"] and state["artifact_sha256"]
    first = client.get(f"/api/reports/builder/jobs/{job_id}/download", headers=headers)
    assert first.status_code == 200
    # A later register edit cannot rewrite an output already generated.
    second = client.get(f"/api/reports/builder/jobs/{job_id}/download", headers=headers)
    assert first.content == second.content
    other = client.post("/api/org/entities", json={"name": "Other company"}, headers=headers).json()["data"]["id"]
    assert client.get(f"/api/reports/builder/jobs/{job_id}/download",
                      headers={**headers, "X-Entity-Id": other}).status_code == 404
