"""
A stated zero is not a missing column.

A register that writes ``0`` in the PF column is making a claim: nothing was
deducted. A register with no PF column at all is making no claim. Those are
different facts and they deserve different findings — and the first one is
precisely what a payroll checker exists to catch.

Five rules read their figure with ``row.get(a) or row.get(b)``, which in Python
treats ``0`` as absent. The effect was that an employee with PF wages and no PF
deducted was reported as "this file has no PF column" at INFO, rather than "PF
was not deducted" at CRITICAL. The same suppression hit the employer PF check,
the PT slab check, the EPS split, and — with the most exposure attached — the
Section 206AA test, whose whole subject is an employee with no PAN and no tax
deducted.

Each test below plants the zero and asserts the rule still fires at the
severity it is meant to.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.services.rule_engine_v2 import _stated


# ---------------------------------------------------------------------------
# The helper itself
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "row,expected",
    [
        ({"pf_employee": 0}, 0),
        ({"pf_employee": 0.0}, 0.0),
        ({"pf_employee": "0"}, "0"),
        ({"pf_employee": 1800}, 1800),
        ({"pf_employee": None, "pf_emp": 0}, 0),
        ({"pf_employee": "", "pf_emp": 1800}, 1800),
        ({}, None),
        ({"pf_employee": None}, None),
    ],
)
def test_a_stated_zero_is_returned_and_a_missing_column_is_not(row, expected):
    assert _stated(row, "pf_employee", "pf_emp") == expected


def test_the_first_column_that_states_anything_wins():
    assert _stated({"pt": 0, "pt_amount": 200}, "pt", "pt_amount") == 0
    assert _stated({"pt": None, "pt_amount": 200}, "pt", "pt_amount") == 200


# ---------------------------------------------------------------------------
# The rules, through the API
# ---------------------------------------------------------------------------
PASSWORD = "Passw0rd!x"

COMPONENTS = [
    {"component_name": "Basic", "pf_applicable": True, "esic_applicable": True,
     "pt_applicable": True, "included_in_wages": True, "taxable": True},
    {"component_name": "HRA", "esic_applicable": True, "pt_applicable": True, "taxable": True},
]


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@zero-example.com".replace("_", "-")
    r = client.post("/api/auth/signup", json={
        "email": email, "password": PASSWORD, "company_name": "Zero Tests",
    })
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    entity_id = client.post(
        "/api/org/entities",
        json={"name": f"E-{request.node.name[:26]}", "primary_state": "Karnataka"},
        headers=headers,
    ).json()["data"]["id"]
    headers["X-Entity-Id"] = entity_id
    for component in COMPONENTS:
        assert client.post("/api/components", json=component, headers=headers).status_code == 201
    client.post(
        "/api/rule-engine/slabs/import-defaults/all?rule_type=PT&overwrite=true", headers=headers
    )
    # PT only applies where the entity says it operates, so the slab check has
    # nothing to compare against until a state is declared.
    assert client.put(
        "/api/settings/statutory", headers=headers,
        json={"pt_states": ["Karnataka"], "lwf_states": ["Karnataka"]},
    ).status_code == 200
    return headers


def validate(client, headers, employee: dict[str, Any]) -> list[dict]:
    body = {"employees": [employee], "period_month": "2026-06-01"}
    response = client.post("/api/payroll/validate", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]["results"][0]["findings"]


def find(findings: list[dict], rule_id: str) -> dict | None:
    return next((f for f in findings if f.get("rule_id") == rule_id), None)


BASE = {
    "employee_id": "E1", "employee_name": "Asha Menon", "state": "Karnataka",
    "paid_days": 30, "lop_days": 0, "basic": 30000, "hra": 12000,
}


def test_pf_deducted_as_zero_is_critical_not_an_absent_column(client, workspace):
    # The single most important rule in the product: someone with PF wages who
    # had no PF taken. Reading the zero as "no column" hid it.
    findings = validate(client, workspace, {**BASE, "pf_employee": 0})
    stat_001 = find(findings, "STAT-001")
    assert stat_001 is not None
    assert stat_001["severity"] == "CRITICAL"
    assert "missing" not in str(stat_001.get("actual", "")).lower()


def test_a_register_with_no_pf_column_still_reports_that_it_cannot_check(client, workspace):
    # The other half of the distinction: no claim made, so no violation found —
    # but the reader is told the check could not run.
    findings = validate(client, workspace, dict(BASE))
    stat_001 = find(findings, "STAT-001")
    assert stat_001 is not None
    assert stat_001["severity"] == "INFO"


def test_employer_pf_of_zero_is_checked_rather_than_skipped(client, workspace):
    findings = validate(client, workspace, {**BASE, "pf_employee": 1800, "pf_employer": 0})
    stat_002 = find(findings, "STAT-002")
    assert stat_002 is not None and stat_002["severity"] == "CRITICAL"


def test_professional_tax_of_zero_is_checked_against_the_slab(client, workspace):
    # A PT of exactly zero is ordinary in a register — every employee under the
    # slab floor has one — which is why reading it as absent was so quiet.
    findings = validate(client, workspace, {**BASE, "pf_employee": 1800, "pt": 0})
    stat_008 = find(findings, "STAT-008")
    assert stat_008 is not None
    assert stat_008["severity"] != "INFO"


def test_no_pan_with_zero_tds_still_trips_section_206aa(client, workspace):
    # Section 206AA requires 20% where there is no PAN. An employee with no PAN
    # and no tax deducted is the violation, and it was the case being skipped.
    findings = validate(client, workspace, {**BASE, "pf_employee": 1800, "tds": 0})
    tds_001 = find(findings, "TDS-001")
    assert tds_001 is not None
    assert tds_001["severity"] == "CRITICAL"


def test_an_eps_split_stated_as_zero_is_checked(client, workspace):
    findings = validate(
        client, workspace, {**BASE, "pf_employee": 1800, "pf_employer": 1800, "eps": 0}
    )
    assert find(findings, "PF-004") is not None


def test_a_correct_register_is_not_made_noisy_by_the_change(client, workspace):
    # The fix must not turn correct zeroes into findings. PF at the ceiling,
    # PT at the Karnataka slab, and a TDS that is genuinely nil on a low wage.
    findings = validate(client, workspace, {
        **BASE, "basic": 12000, "hra": 4800, "pf_employee": 1440, "pf_employer": 1440,
        "pt": 0, "pan": "ABCDE1234F",
    })
    for rule_id in ("STAT-001", "STAT-002", "TDS-001"):
        finding = find(findings, rule_id)
        assert finding is None or finding["severity"] in ("INFO", "PASS"), rule_id
