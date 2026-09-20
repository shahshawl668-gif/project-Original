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
