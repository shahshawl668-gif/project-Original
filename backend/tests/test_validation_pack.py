"""The manual-test pack under testdata/payroll-validation, driven through the real API.

The pack is what a person loads by hand to try the module. This test loads the
same files in the same order and checks the tool reports every planted mistake
-- and nothing else of consequence -- so the pack cannot silently rot when a
rule changes.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PACK = Path(__file__).resolve().parents[2] / "testdata" / "payroll-validation"
PASSWORD = "Passw0rd!x"
PERIOD = {"period_month": "2026-08-01"}

# employee -> rule ids that must fire (severity above INFO) for that employee
EXPECTED = {
    "E004": {"STAT-006"},        # ESIC not deducted within the ceiling
    "E005": {"STAT-001"},        # PF not deducted
    "E015": {"STAT-008"},        # PT missing
    "E019": {"STAT-006"},        # ESIC deducted above the ceiling
    "E021": {"PF-009"},          # PF on the full wage above the ceiling
    "E024": {"STAT-008"},        # PT wrong amount
    "E026": {"AGG-001"},         # gross does not add up
    "E027": {"AGG-002"},         # net does not add up
    "E028": {"ATT-001", "ATT-002", "ATT-020"},   # paid days vs attendance
    "E029": {"LOP-002"},         # basic above the CTC letter
    "E030": {"MST-003"},         # paid after exit
    "E031": {"MST-006"},         # full month paid to a mid-month joiner
    "E033": {"DATA-002"},        # duplicate row
    "E036": {"ATT-022"},         # overtime hours, none paid
    "E038": {"ATT-015"},         # on attendance, not on the register
    "E040": {"MST-001"},         # not in the master
}
# Rules that may fire on people who are otherwise correct
BACKGROUND: set[str] = set()


def _file(name: str):
    return {"file": (name, (PACK / name).read_bytes(), "text/csv")}


@pytest.fixture(scope="module")
def workspace(client):
    email = "validation-pack@pack-example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD, "company_name": "Pack Co"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    entity = client.post("/api/org/entities", json={"name": "Pack entity", "primary_state": "Karnataka"},
                         headers=headers).json()["data"]["id"]
    headers["X-Entity-Id"] = entity
    return headers


@pytest.fixture(scope="module")
def run(client, workspace):
    h = workspace
    # 1. the one-file configuration
    preview = client.post("/api/config/bundle/import?dry_run=true", files=_file("1_configuration.csv"), headers=h)
    assert preview.status_code == 200, preview.text
    applied = client.post("/api/config/bundle/import?dry_run=false", files=_file("1_configuration.csv"), headers=h)
    assert applied.status_code == 200, applied.text
    # 2. employee master
    r = client.post("/api/workforce/master/commit", files=_file("2_employee_master.csv"),
                    data={"meta": json.dumps({"effective_from": "2026-04-01"})}, headers=h)
    assert r.status_code == 200, r.text
    # 3. CTC (parse, then commit the parsed records)
    r = client.post("/api/ctc/upload", files=_file("3_ctc_report.csv"),
                    data={"meta": json.dumps({"default_effective_from": "2026-04-01"})}, headers=h)
    assert r.status_code == 200, r.text
    r = client.post("/api/ctc/commit", json={"filename": "3_ctc_report.csv", "default_effective_from": "2026-04-01",
                                              "records": r.json()["data"]["records"]}, headers=h)
    assert r.status_code == 200, r.text
    # 4. attendance
    check = client.post("/api/workforce/attendance/validate", files=_file("4_attendance_report.csv"),
                        data={"meta": json.dumps(PERIOD)}, headers=h)
    assert check.status_code == 200, check.text
    r = client.post("/api/workforce/attendance/commit", files=_file("4_attendance_report.csv"),
                    data={"meta": json.dumps(PERIOD)}, headers=h)
    assert r.status_code == 200, r.text
    # 5. last month's register, so August can be compared with it
    july = client.post("/api/payroll/upload", files=_file("6_previous_month_register_july.csv"), headers=h, data={
        "meta": json.dumps({"run_type": "regular", "period_month": "2026-07-01", "strict_header_check": False})})
    assert july.status_code == 200, july.text
    r = client.post("/api/payroll/validate", headers=h, json={
        "employees": july.json()["data"]["employees"], "run_type": "regular",
        "period_month": "2026-07-01", "as_of_date": "2026-07-31"})
    assert r.status_code == 200, r.text
    # 6. the August register, then validate
    up = client.post("/api/payroll/upload", files=_file("5_salary_register.csv"), headers=h, data={
        "meta": json.dumps({"run_type": "regular", **PERIOD, "strict_header_check": False})})
    assert up.status_code == 200, up.text
    v = client.post("/api/payroll/validate", headers=h, json={
        "employees": up.json()["data"]["employees"], "run_type": "regular", **PERIOD, "as_of_date": "2026-08-31"})
    assert v.status_code == 200, v.text
    return {"attendance": check.json()["data"], "validation": v.json()["data"]}


def test_the_configuration_file_sets_up_the_entity(client, workspace, run):
    comps = client.get("/api/components", headers=workspace).json()["data"]
    assert {c["component_name"] for c in comps} == {"Basic", "HRA", "Special Allowance", "Conveyance", "Overtime"}
    stat = client.get("/api/settings/statutory", headers=workspace).json()["data"]
    assert float(stat["pf_wage_ceiling"]) == 25000


def test_every_planted_mistake_is_reported(run):
    fired: dict[str, set[str]] = {}
    for f in run["validation"]["findings"]:
        if f["status"] == "FAIL" and f["severity"] != "INFO":
            fired.setdefault(f["employee_id"], set()).add(f["rule_id"])
    for employee, rules in EXPECTED.items():
        assert rules <= fired.get(employee, set()), f"{employee}: expected {rules}, got {fired.get(employee)}"


def test_correct_employees_are_left_alone(run):
    unexpected = {}
    for f in run["validation"]["findings"]:
        if f["status"] == "FAIL" and f["severity"] != "INFO" and f["employee_id"] not in EXPECTED \
                and f["rule_id"] not in BACKGROUND:
            unexpected.setdefault(f["employee_id"], []).append(f["rule_id"])
    assert not unexpected, unexpected


def test_the_attendance_file_that_contradicts_itself_is_caught_before_payroll(run):
    flagged = {f["employee_id"] for f in run["attendance"]["findings"]}
    assert flagged == {"E037"}


def test_the_answer_key_matches_the_generator(tmp_path):
    """Regenerating gives the committed files, so the key in the README is what is in the CSVs."""
    before = {p.name: p.read_bytes() for p in PACK.glob("*.csv")}
    out = subprocess.run([sys.executable, str(PACK / "generate.py")], capture_output=True, text=True,
                         env={"PYTHONPATH": str(Path(__file__).resolve().parents[1]), "PATH": ""}, cwd=PACK)
    assert out.returncode == 0, out.stderr
    assert before == {p.name: p.read_bytes() for p in PACK.glob("*.csv")}
