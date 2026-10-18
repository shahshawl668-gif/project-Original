"""A formula saved and activated in the Formula builder drives PF / ESIC validation."""
from __future__ import annotations

import io

import pandas as pd
import pytest

PASSWORD = "Passw0rd!x"
PF_FORMULA = "IF(basic<=25000, MIN((basic+special_allowance)*12%, 3000), basic*12%)"


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@formula-example.com".replace("_", "-")
    r = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD, "company_name": "Formula Tests"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    h = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    h["X-Entity-Id"] = client.post("/api/org/entities", json={"name": "F", "primary_state": "Karnataka"},
                                   headers=h).json()["data"]["id"]
    for name, pf in (("Basic", True), ("Special Allowance", True), ("HRA", False)):
        assert client.post("/api/components", headers=h, json={
            "component_name": name, "pf_applicable": pf, "esic_applicable": False,
            "pt_applicable": False, "included_in_wages": True, "taxable": True}).status_code == 201
    return h


def _validate(client, h, rows):
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    up = client.post("/api/payroll/upload", headers=h, files={"file": ("r.csv", buf.getvalue().encode(), "text/csv")},
                     data={"meta": '{"run_type":"regular","period_month":"2026-08-01","strict_header_check":false}'})
    assert up.status_code == 200, up.text
    v = client.post("/api/payroll/validate", headers=h, json={
        "employees": up.json()["data"]["employees"], "run_type": "regular",
        "period_month": "2026-08-01", "as_of_date": "2026-08-31"})
    assert v.status_code == 200, v.text
    return v.json()["data"]


def _row(eid, basic, special, pf):
    return {"Employee ID": eid, "Basic": basic, "Special Allowance": special, "HRA": 0,
            "PF Employee": pf, "Paid Days": 31, "LOP Days": 0, "Total Days": 31}


def _pf_fails(data):
    return {f["employee_id"] for f in data["findings"] if f["rule_id"] in ("STAT-001", "PF-009") and f["status"] == "FAIL"}


def test_the_saved_formula_is_the_expected_pf(client, workspace):
    saved = client.post("/api/rule-engine/formula", headers=workspace, json={
        "rule_type": "PF", "name": "mine", "expression": PF_FORMULA, "activate": True})
    assert saved.status_code == 201, saved.text
    data = _validate(client, workspace, [
        _row("A1", 20000, 10000, 3000),    # lower paid: (20000+10000)*12% = 3600, capped at 3000
        _row("A2", 12000, 3000, 1800),     # (12000+3000)*12% = 1800
        _row("A3", 30000, 5000, 3600),     # above 25,000: basic*12% = 3600 (not capped)
        _row("B1", 12000, 3000, 1000),     # wrong
        _row("B2", 30000, 5000, 3000),     # wrong under this formula (the formula says 3600)
    ])
    assert _pf_fails(data) == {"B1", "B2"}


def test_without_a_saved_formula_the_engine_decides(client, workspace):
    data = _validate(client, workspace, [_row("C1", 30000, 5000, 3000)])   # ceiling 15,000 -> 1800 expected
    assert "C1" in _pf_fails(data)


def test_a_formula_that_cannot_be_evaluated_is_reported_not_skipped(client, workspace):
    r = client.post("/api/rule-engine/formula", headers=workspace, json={
        "rule_type": "PF", "name": "divides", "expression": "basic / lop_days", "activate": True})
    assert r.status_code == 201, r.text
    data = _validate(client, workspace, [_row("D1", 12000, 3000, 1800)])
    row = data["results"][0]
    assert any("saved PF formula could not be applied" in str(m) for m in row.get("messages", row.get("errors", [])))


def test_the_tds_warning_needs_tds_to_be_missing(client, workspace):
    """High income with no TDS column still warns; stating the TDS that is due does not."""
    no_column = _validate(client, workspace, [_row("T1", 90000, 10000, 3000)])
    assert any(f["rule_id"] == "STAT-011" for f in no_column["findings"] if f["employee_id"] == "T1")
    row = dict(_row("T2", 90000, 10000, 3000), TDS=12000)
    stated = _validate(client, workspace, [row])
    assert not any(f["rule_id"] == "STAT-011" for f in stated["findings"] if f["employee_id"] == "T2")
