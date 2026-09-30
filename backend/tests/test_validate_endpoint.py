"""
End-to-end coverage for the validation endpoint.

Every other suite exercises a service directly. That left the one path every
user actually takes — upload a register, validate it — with no test at all, and
a stray reference to a parameter the entity refactor had renamed sat in
`validate_employees` undetected: every validation run returned a 500.

These drive the real HTTP surface, so the wiring between router, service and
config is covered and not merely the arithmetic inside it.
"""
from __future__ import annotations

import io

import pandas as pd
import pytest

PASSWORD = "Passw0rd!x"

COMPONENTS = [
    {"component_name": "Basic", "pf_applicable": True, "esic_applicable": True,
     "pt_applicable": True, "included_in_wages": True, "taxable": True},
    {"component_name": "HRA", "esic_applicable": True, "pt_applicable": True, "taxable": True},
    {"component_name": "Special Allowance", "pf_applicable": True, "esic_applicable": True,
     "pt_applicable": True, "taxable": True},
]

REGISTER = [
    {"Employee ID": "E001", "Employee Name": "Asha Menon", "State": "Karnataka",
     "Paid Days": 30, "LOP Days": 0,
     "Basic": 20000, "HRA": 8000, "Special Allowance": 7000,
     "PF Employee": 2400, "Gross": 35000},
    # PF not deducted at all — should be caught.
    {"Employee ID": "E002", "Employee Name": "Rahul Verma", "State": "Karnataka",
     "Paid Days": 30, "LOP Days": 0,
     "Basic": 15000, "HRA": 6000, "Special Allowance": 5000,
     "PF Employee": 0, "Gross": 26000},
]


@pytest.fixture()
def workspace(client, request):
    """A signed-in user with components configured, in an entity of their own."""
    email = f"{request.node.name[:40]}@validate-example.com".replace("_", "-")
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": PASSWORD, "company_name": "Validate Tests"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}

    entity_id = client.post(
        "/api/org/entities", json={"name": f"E-{request.node.name[:26]}", "primary_state": "Karnataka"},
        headers=headers,
    ).json()["data"]["id"]
    headers["X-Entity-Id"] = entity_id

    for payload in COMPONENTS:
        assert client.post("/api/components", json=payload, headers=headers).status_code == 201
    return headers


def _csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode()


def _upload(client, headers, rows=REGISTER, period="2026-08-01"):
    return client.post(
        "/api/payroll/upload",
        files={"file": ("register.csv", _csv(rows), "text/csv")},
        data={"meta": f'{{"run_type":"regular","period_month":"{period}","strict_header_check":false}}'},
        headers=headers,
    )


def test_upload_parses_the_register(client, workspace):
    r = _upload(client, workspace)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data["employees"]) == 2
    assert data["missing_required"] == []


def test_validate_returns_findings(client, workspace):
    """The regression this file exists for: this endpoint returned 500."""
    employees = _upload(client, workspace).json()["data"]["employees"]

    r = client.post(
        "/api/payroll/validate",
        json={"employees": employees, "run_type": "regular",
              "period_month": "2026-08-01", "as_of_date": "2026-08-31"},
        headers=workspace,
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    assert len(data["results"]) == 2
    assert len(data["risk_scores"]) == 2
    assert "findings_summary" in data
    # The employee with no PF deducted must be flagged somewhere.
    flagged = {f["employee_id"] for f in data["findings"] if f["status"] == "FAIL"}
    assert "E002" in flagged


def test_validation_run_is_recorded(client, workspace):
    """A validated period must leave a record the worklist can build on."""
    employees = _upload(client, workspace).json()["data"]["employees"]
    r = client.post(
        "/api/payroll/validate",
        json={"employees": employees, "run_type": "regular",
              "period_month": "2026-08-01", "as_of_date": "2026-08-31"},
        headers=workspace,
    )
    lifecycle = r.json()["data"]["lifecycle"]
    assert lifecycle["period_month"] == "2026-08-01"
    assert lifecycle["run_id"]

    runs = client.get("/api/findings/runs", headers=workspace).json()["data"]
    assert len(runs) == 1
    assert runs[0]["period_month"] == "2026-08-01"

    # And the findings are on the worklist.
    assert client.get("/api/findings", headers=workspace).json()["data"]


def test_statutory_settings_resolve_for_the_entity(client, workspace):
    """
    PT and LWF state lists are read through StatutorySettings, which the entity
    refactor re-keyed. Setting them must change what validation sees.
    """
    r = client.put(
        "/api/settings/statutory",
        json={"pt_states": ["Karnataka"], "lwf_states": ["Karnataka"]},
        headers=workspace,
    )
    assert r.status_code == 200, r.text

    employees = _upload(client, workspace).json()["data"]["employees"]
    r = client.post(
        "/api/payroll/validate",
        json={"employees": employees, "run_type": "regular",
              "period_month": "2026-08-01", "as_of_date": "2026-08-31"},
        headers=workspace,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["results"][0]["pt_applicable_state"] == "Karnataka"


def test_excel_export_returns_a_workbook(client, workspace):
    employees = _upload(client, workspace).json()["data"]["employees"]
    r = client.post(
        "/api/payroll/validate/export-excel",
        json={"employees": employees, "run_type": "regular",
              "period_month": "2026-08-01", "as_of_date": "2026-08-31"},
        headers=workspace,
    )
    assert r.status_code == 200, r.text
    assert "spreadsheetml" in r.headers["content-type"]
    assert r.content[:2] == b"PK"


def test_dashboard_stats_reflect_the_upload(client, workspace):
    _upload(client, workspace)
    stats = client.get("/api/payroll/dashboard-stats", headers=workspace).json()["data"]
    assert stats["components_configured"] == len(COMPONENTS)
    assert stats["last_run_employee_count"] == 2


def test_excel_export_includes_unmatched_findings(client, workspace, monkeypatch):
    """Export must agree with the validation worklist when a person is absent from payroll."""
    from openpyxl import load_workbook
    from app.routers import payroll

    employees = _upload(client, workspace).json()["data"]["employees"]
    original = payroll.validate_employees

    def with_unmatched(*args, **kwargs):
        rows, summary = original(*args, **kwargs)
        summary["unmatched_findings"] = [{
            "employee_id": "MISSING-001",
            "employee_name": "Missing Worker",
            "rule_id": "ATTENDANCE_MISSING_PAYROLL",
            "rule_name": "Missing from payroll",
            "status": "FAIL",
            "severity": "CRITICAL",
            "financial_impact": 1000,
            "reason": "Attendance record has no payroll row",
        }]
        return rows, summary

    monkeypatch.setattr(payroll, "validate_employees", with_unmatched)
    response = client.post(
        "/api/payroll/validate/export-excel",
        json={"employees": employees, "run_type": "regular",
              "period_month": "2026-08-01", "as_of_date": "2026-08-31"},
        headers=workspace,
    )
    assert response.status_code == 200, response.text
    workbook = load_workbook(io.BytesIO(response.content), read_only=True, data_only=True)
    findings = list(workbook["Findings"].values)
    assert any(row[0] == "MISSING-001" for row in findings[1:])
    assert workbook["Summary"]["B2"].value == 2
    assert workbook["Summary"]["B3"].value == len(findings) - 1


def _run_findings(run_id: str) -> set[tuple[str, str, str]]:
    import uuid

    from app.database import SessionLocal
    from app.models import FindingRecord

    db = SessionLocal()
    try:
        return {(f.employee_id, f.rule_id, f.status) for f in
                db.query(FindingRecord).filter(FindingRecord.run_id == uuid.UUID(run_id))}
    finally:
        db.close()


def test_a_register_too_large_for_one_request_is_queued_and_validated_the_same(
    client, workspace, monkeypatch,
):
    """Past the limit the request would outlive the gateway. It is queued
    instead, and the queued run finds exactly what the request would have."""
    from app.config import settings
    from app.database import SessionLocal
    from app.models import ValidationJob
    from app.services import validation_worker

    employees = _upload(client, workspace).json()["data"]["employees"]
    body = {"employees": employees, "run_type": "regular",
            "period_month": "2026-08-01", "as_of_date": "2026-08-31"}
    inline = client.post("/api/payroll/validate", json=body, headers=workspace)
    assert inline.status_code == 200, inline.text
    inline_findings = _run_findings(inline.json()["data"]["lifecycle"]["run_id"])
    assert inline_findings

    monkeypatch.setattr(settings, "sync_validate_max_employees", 1)
    queued = client.post("/api/payroll/validate", json=body, headers=workspace)
    assert queued.status_code == 202, queued.text
    data = queued.json()["data"]
    assert data["queued"] is True and "limit is 1" in data["reason"]
    assert data["follow"] == f"/api/validation/jobs/{data['job']['id']}"

    db = SessionLocal()
    try:
        validation_worker.drain(db, "test-worker")
    finally:
        db.close()
    job = client.get(data["follow"], headers=workspace).json()["data"]
    assert job["state"] == "succeeded", job
    assert _run_findings(job["run_id"]) == inline_findings

    # Without a month there is nothing to queue it under: refused, and said why.
    no_month = client.post("/api/payroll/validate", headers=workspace,
                           json={"employees": employees, "run_type": "regular"})
    assert no_month.status_code == 413
    assert "period_month" in no_month.json()["error"]["detail"]
    # The Excel export has no queued form of its own; it points to the run's.
    excel = client.post("/api/payroll/validate/export-excel", json=body, headers=workspace)
    assert excel.status_code == 413
    assert "export.xlsx" in excel.json()["error"]["detail"]
    db = SessionLocal()
    try:
        assert db.query(ValidationJob).filter(ValidationJob.period_month.isnot(None)).count() >= 1
    finally:
        db.close()
