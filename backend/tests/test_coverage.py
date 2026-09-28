"""
Every check has one of five outcomes, and a missing input is never a pass.

Fixtures are built so each outcome has a specific, independently known cause:

* E001 — complete register row, ESIC-ineligible, PF correct.
      STAT-001 passed; STAT-006 not applicable (gross above ₹21,000).
* E002 — PF under-deducted by ₹100.            STAT-001 failed.
* E003 — gross ₹16,000, ESIC deducted correctly. STAT-006 passed.
* Register variant without a PF column:         STAT-001 cannot validate.
* A suppressed rule:                            disabled for everyone.
* No employee master uploaded:                  MST-001 cannot validate;
  after the master is uploaded:                 MST-001 passed.
"""
from __future__ import annotations

import io
import json
import math
import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import coverage, explain
from tests.test_run_history import PERIOD, _company, _data, _drain, _empty_queue  # noqa: F401

COMPONENTS_ALL_ESIC = None  # the history fixture's components: Basic/HRA/Special all ESIC-applicable


def _pf(basic: int) -> int:
    return round(min(basic + round(basic * 0.25), 15000) * 0.12)


def _row(eid, basic, *, pf_delta=0, esic=True):
    hra, special = round(basic * 0.4), round(basic * 0.25)
    gross = basic + hra + special
    pf = _pf(basic) + pf_delta
    # Above the ESIC ceiling the cells are left empty, as most registers do;
    # a stated 0 against an expected 0 would be a genuine pass, not N/A.
    esic_ee = math.ceil(gross * 0.0075) if (esic and gross <= 21000) else ""
    esic_er = math.ceil(gross * 0.0325) if (esic and gross <= 21000) else ""
    return f"{eid},Person {eid},Karnataka,30,0,{basic},{hra},{special},{pf},{pf},{esic_ee},{esic_er},ABCPE1234F,100200300400"


HEADER = ("employee_id,employee_name,state,paid_days,lop_days,basic,hra,special allowance,"
          "pf_employee,pf_employer,esic_employee,esic_employer,pan,uan")


def _register(rows, drop: set[str] | None = None) -> bytes:
    lines = [HEADER, *rows]
    if drop:
        cols = HEADER.split(",")
        keep = [i for i, c in enumerate(cols) if c not in drop]
        lines = [",".join(line.split(",")[i] for i in keep) for line in lines]
    return ("\n".join(lines) + "\n").encode()


def _run(client, headers, content: bytes) -> str:
    r = client.post("/api/payroll/upload", headers=headers,
                    files={"file": ("r.csv", io.BytesIO(content), "text/csv")},
                    data={"meta": json.dumps({"period_month": PERIOD, "strict_header_check": False,
                                              "return_employees": False})})
    assert r.status_code == 200, r.text
    job = _data(client.post("/api/validation/jobs", headers=headers, json={"period_month": PERIOD}))["job"]
    _drain()
    job = _data(client.get(f"/api/validation/jobs/{job['id']}", headers=headers))
    assert job["state"] == "succeeded", job
    return job["run_id"]


def _outcome(client, headers, run_id, employee, rule):
    detail = _data(client.get(f"/api/validation/runs/{run_id}/employees/{employee}", headers=headers))
    return detail["result"]["coverage"][rule]


@pytest.fixture()
def company(client):
    return _company(client, "cov")


BASE_ROWS = [_row("E001", 30000), _row("E002", 30000, pf_delta=-100), _row("E003", 8000)]


def test_each_outcome_comes_from_its_cause(client, company):
    run_id = _run(client, company, _register(BASE_ROWS))
    assert _outcome(client, company, run_id, "E001", "STAT-001")["outcome"] == "passed"
    assert _outcome(client, company, run_id, "E002", "STAT-001")["outcome"] == "failed"
    na = _outcome(client, company, run_id, "E001", "STAT-006")
    assert na["outcome"] == "not_applicable" and "ESIC" in na["reason"]
    assert _outcome(client, company, run_id, "E003", "STAT-006")["outcome"] == "passed"


def test_a_missing_column_is_cannot_validate_never_passed(client, company):
    run_id = _run(client, company, _register(BASE_ROWS, drop={"pf_employee"}))
    verdict = _outcome(client, company, run_id, "E001", "STAT-001")
    assert verdict["outcome"] == "cannot_validate"
    run = _data(client.get(f"/api/validation/runs/{run_id}", headers=company))
    cov = run["summary"]["coverage"]
    stat001 = next(r for r in cov["rules"] if r["rule_id"] == "STAT-001")
    assert stat001["counts"]["cannot_validate"] == 3
    assert stat001["counts"]["passed"] == 0
    assert cov["material_cannot_validate"] >= 3
    # The employees table can be filtered to exactly these people.
    page = _data(client.get(f"/api/validation/runs/{run_id}/employees?only_unverifiable=true", headers=company))
    assert page["total"] == 3


def test_a_switched_off_rule_is_disabled_not_passed(client, company):
    r = client.put("/api/rule-preferences", headers=company, json={"rule_id": "STAT-001", "suppressed": True})
    assert r.status_code == 200, r.text
    run_id = _run(client, company, _register(BASE_ROWS))
    assert _outcome(client, company, run_id, "E002", "STAT-001")["outcome"] == "disabled"


def test_master_checks_need_a_master_and_pass_once_it_exists(client, company):
    run_id = _run(client, company, _register(BASE_ROWS))
    assert _outcome(client, company, run_id, "E001", "MST-001")["outcome"] == "cannot_validate"

    master = ("employee_id,employee_name,gender,date_of_joining,work_state,department,uan\n"
              + "\n".join(f"{e},Person {e},F,2022-04-01,Karnataka,Ops,100200300400" for e in ("E001", "E002", "E003"))
              + "\n")
    r = client.post("/api/workforce/master/commit", headers=company,
                    files={"file": ("m.csv", io.BytesIO(master.encode()), "text/csv")},
                    data={"meta": json.dumps({"effective_from": "2026-04-01"})})
    assert r.status_code == 200, r.text
    run_id = _run(client, company, _register(BASE_ROWS))
    assert _outcome(client, company, run_id, "E001", "MST-001")["outcome"] == "passed"


def test_coverage_is_reported_separately_from_failures(client, company):
    run_id = _run(client, company, _register(BASE_ROWS))
    run = _data(client.get(f"/api/validation/runs/{run_id}", headers=company))
    cov = run["summary"]["coverage"]
    assert set(cov["totals"]) == set(coverage.OUTCOMES)
    assert 0 < cov["coverage_pct"] <= 100
    # Every employee got a verdict on every registered rule.
    assert sum(cov["totals"].values()) == len(coverage.REGISTRY) * 3


# ---------------------------------------------------------------------------
# Minimum wage, inside every validation
# ---------------------------------------------------------------------------
def test_minimum_wage_is_cannot_validate_until_someone_decides(client, company):
    run_id = _run(client, company, _register(BASE_ROWS))
    assert _outcome(client, company, run_id, "E001", "MW-001")["outcome"] == "cannot_validate"


def test_minimum_wage_marked_not_applicable_is_not_applicable(client, company):
    r = client.post("/api/minimum-wage/applicability", headers=company, json={
        "effective_from": "2026-04-01", "applicable": False, "reason": "Only managerial staff"})
    assert r.status_code == 200, r.text
    run_id = _run(client, company, _register(BASE_ROWS))
    assert _outcome(client, company, run_id, "E001", "MW-001")["outcome"] == "not_applicable"


def test_minimum_wage_runs_in_validation_when_applicable(client, company):
    assert client.post("/api/minimum-wage/applicability", headers=company, json={
        "effective_from": "2026-04-01", "applicable": True}).status_code == 200
    # A floor of ₹14,000 a month for unskilled Karnataka work (test figure, not law).
    assert client.post("/api/minimum-wage/rates", headers=company, json={
        "state": "Karnataka", "skill_category": "unskilled", "basic_per_month": "14000",
        "effective_from": "2026-04-01", "source_reference": "test fixture"}).status_code in (200, 201)
    master = ("employee_id,employee_name,gender,date_of_joining,work_state,department,skill_category,uan\n"
              "E001,Person E001,F,2022-04-01,Karnataka,Ops,unskilled,100200300400\n"
              "E002,Person E002,F,2022-04-01,Karnataka,Ops,unskilled,100200300400\n"
              "E003,Person E003,F,2022-04-01,Karnataka,Ops,,100200300400\n")
    assert client.post("/api/workforce/master/commit", headers=company,
                       files={"file": ("m.csv", io.BytesIO(master.encode()), "text/csv")},
                       data={"meta": json.dumps({"effective_from": "2026-04-01"})}).status_code == 200
    rows = [_row("E001", 30000), _row("E002", 7000), _row("E003", 30000)]
    run_id = _run(client, company, _register(rows))
    # E001: 30,000 + 7,500 special (HRA excluded) = 37,500 ≥ 14,000.
    assert _outcome(client, company, run_id, "E001", "MW-001")["outcome"] == "passed"
    # E002: 7,000 + 1,750 = 8,750 < 14,000 — below the floor.
    below = _outcome(client, company, run_id, "E002", "MW-001")
    assert below["outcome"] == "failed"
    # E003: no skill category on the master, so no rate can be chosen.
    assert _outcome(client, company, run_id, "E003", "MW-003")["outcome"] == "cannot_validate"
    finding = _data(client.get(f"/api/validation/runs/{run_id}/findings?rule_id=MW-001", headers=company))
    assert finding["items"][0]["employee_id"] == "E002"
    assert Decimal(str(finding["items"][0]["financial_impact"])) == Decimal("5250.00")


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------
def test_overlapping_findings_are_counted_once():
    findings = [
        {"employee_id": "E1", "rule_id": "STAT-001", "financial_impact": 1438},
        {"employee_id": "E1", "rule_id": "PF-009", "financial_impact": 1438},
        {"employee_id": "E1", "rule_id": "STAT-006", "financial_impact": 40},
        {"employee_id": "E2", "rule_id": "ID-004", "financial_impact": 0},
    ]
    out = explain.deduplicated_exposure(findings)
    assert out["exposure"] == Decimal("1478.00")
    assert out["overlap_excluded"] == Decimal("1438.00")
    assert out["impact_not_calculated"] == 1


def test_an_uncalculated_impact_is_not_zero():
    assert explain.impact_known("ID-004", 0) is False
    assert explain.impact_known("STAT-001", 0) is False
    assert explain.impact_known("STAT-001", 12.5) is True


# ---------------------------------------------------------------------------
# The registry keeps up with the engine
# ---------------------------------------------------------------------------
ENGINE_FILES = ("rule_engine_v2.py", "workforce_rules.py", "attendance_rules.py", "minimum_wage.py", "validation.py")


def test_every_rule_the_engine_can_emit_has_a_coverage_entry():
    root = Path(__file__).resolve().parents[1] / "app" / "services"
    emitted: set[str] = set()
    for name in ENGINE_FILES:
        text = (root / name).read_text()
        emitted |= set(re.findall(r'"((?:[A-Z]{2,6})-\d{3})"', text))
        for scheme in ("PT", "LWF"):
            for kind in ("STATE", "RATE"):
                if f'DATA-{{scheme}}-{kind}' in text:
                    emitted.add(f"DATA-{scheme}-{kind}")
    assert emitted - set(coverage.BY_ID) == set(), "add these to services/coverage.py"


# ---------------------------------------------------------------------------
# A month with no failures is not ready when material checks never ran
# ---------------------------------------------------------------------------
def test_no_failures_with_unperformed_statutory_checks_is_incomplete_not_ready(client, company):
    # One ESIC-exempt employee, and the rules that report on a first month or
    # an above-ceiling wage switched off, so nothing at all fails.
    for rule in ("MOM-001", "STAT-005", "STAT-011"):
        assert client.put("/api/rule-preferences", headers=company,
                          json={"rule_id": rule, "suppressed": True}).status_code == 200
    clean = [_row("E001", 30000)]
    run_id = _run(client, company, _register(clean))
    run = _data(client.get(f"/api/validation/runs/{run_id}", headers=company))
    assert run["total_findings"] == 0, run
    status = _data(client.get(f"/api/validation/periods/{PERIOD}/status", headers=company))
    # Minimum wage has not been decided for this company, so it could not be checked.
    assert status["stage"] == "checks_incomplete"
    assert [b["code"] for b in status["readiness"]["blockers"]] == ["incomplete_coverage"]

    assert client.post("/api/minimum-wage/applicability", headers=company, json={
        "effective_from": "2026-04-01", "applicable": False, "reason": "Only managerial staff"}).status_code == 200
    _run(client, company, _register(clean))
    status = _data(client.get(f"/api/validation/periods/{PERIOD}/status", headers=company))
    assert status["stage"] == "ready_for_approval", status["readiness"]


def test_outcomes_are_stored_compactly_and_expand_to_every_check(client, company):
    """The stored form keeps memory flat at scale; readers still see one verdict per check."""
    from app.database import SessionLocal
    from app.models import ValidationRunEmployee
    from app.services.register_uploads import gunzip_json

    run_id = _run(client, company, _register(BASE_ROWS))
    db = SessionLocal()
    try:
        row = db.query(ValidationRunEmployee).filter(
            ValidationRunEmployee.employee_id == "E002",
            ValidationRunEmployee.run_id == __import__("uuid").UUID(run_id)).one()
        stored = gunzip_json(row.detail_gz)["coverage"]
    finally:
        db.close()
    assert isinstance(stored["passed"], list) and "STAT-001" in stored["failed"]
    expanded = coverage.expand(stored)
    assert list(expanded) == [r.rule_id for r in coverage.REGISTRY]
    served = _data(client.get(f"/api/validation/runs/{run_id}/employees/E002", headers=company))
    assert served["result"]["coverage"] == coverage.expand(stored, served["result"]["findings"])
    assert served["employee"]["cannot_validate_checks"] == len(stored["cannot_validate"])
