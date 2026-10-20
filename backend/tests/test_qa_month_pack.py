"""The September 2026 QA month under testdata/payroll-qa-sep2026, driven through the real API.

A payroll processor's month: increments mid-month and in arrears, loss of pay, a
joiner and a leaver, PF and ESIC on arrears, PT by gender, LWF by month and
minimum wage on the CTC break-up -- in one register, validated once. Every
planted mistake must be reported, and nobody else may get a warning or worse.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PACK = Path(__file__).resolve().parents[2] / "testdata" / "payroll-qa-sep2026"
PASSWORD = "Passw0rd!x"
KEY = json.loads((PACK / "answer_key.json").read_text())
# LC-001 and MW-005 read the CTC: Basic + DA below half of pay, or below the minimum wage on its own,
# are structure review points listed in the README, not payroll errors of the month.
BACKGROUND = {"LC-001", "MW-005"}


def _file(name: str):
    return {"file": (name, (PACK / name).read_bytes(), "text/csv")}


@pytest.fixture(scope="module")
def month(client):
    email = "qa-month@qa-month-example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD, "company_name": "QA Retail"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    h = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    h["X-Entity-Id"] = client.post("/api/org/entities", json={"name": "QA Retail Pvt Ltd", "primary_state": "Karnataka"},
                                   headers=h).json()["data"]["id"]
    r = client.post("/api/config/bundle/import?dry_run=false", files=_file("1_configuration.csv"), headers=h)
    assert r.status_code == 200, r.text
    r = client.post("/api/workforce/master/commit", files=_file("2_employee_master.csv"),
                    data={"meta": json.dumps({"effective_from": "2022-04-01"})}, headers=h)
    assert r.status_code == 200, r.text
    parsed = client.post("/api/ctc/upload", files=_file("3_ctc_report.csv"),
                         data={"meta": json.dumps({"default_effective_from": "2026-04-01"})}, headers=h)
    assert parsed.status_code == 200, parsed.text
    r = client.post("/api/ctc/commit", headers=h, json={"filename": "3_ctc_report.csv", "default_effective_from": "2026-04-01",
                                                         "records": parsed.json()["data"]["records"]})
    assert r.status_code == 200, r.text
    meta = {"meta": json.dumps({"period_month": "2026-09-01"})}
    attendance = client.post("/api/workforce/attendance/validate", files=_file("4_attendance_report.csv"), data=meta, headers=h)
    assert attendance.status_code == 200, attendance.text
    assert client.post("/api/workforce/attendance/commit", files=_file("4_attendance_report.csv"), data=meta,
                       headers=h).status_code == 200
    out = {"attendance": attendance.json()["data"]}
    for name, period in (("5_previous_month_register_aug.csv", "2026-08-01"), ("6_salary_register_sep.csv", "2026-09-01")):
        up = client.post("/api/payroll/upload", files=_file(name), headers=h, data={
            "meta": json.dumps({"period_month": period, "strict_header_check": True})})
        assert up.status_code == 200, up.text
        v = client.post("/api/payroll/validate", headers=h, json={
            "employees": up.json()["data"]["employees"], "period_month": period})
        assert v.status_code == 200, v.text
        out[period] = v.json()["data"]
    return out


def _fired(data):
    fired: dict[str, set[str]] = {}
    for f in data["findings"]:
        if f["status"] == "FAIL" and f["severity"] != "INFO":
            fired.setdefault(f["employee_id"], set()).add(f["rule_id"])
    return fired


def test_every_planted_mistake_is_reported(month):
    fired = _fired(month["2026-09-01"])
    for employee, entry in KEY.items():
        assert set(entry["rules"]) <= fired.get(employee, set()), f"{employee} ({entry['mistake']}): {fired.get(employee)}"


def test_correct_payslips_are_left_alone(month):
    fired = _fired(month["2026-09-01"])
    unexpected = {e: sorted(r - BACKGROUND - set(KEY.get(e, {}).get("rules", []))) for e, r in fired.items()}
    assert not {e: r for e, r in unexpected.items() if r}, unexpected


def test_the_attendance_file_with_a_joiner_and_a_leaver_is_clean(month):
    assert month["attendance"]["findings"] == []


def test_the_answer_key_matches_the_generator():
    before = {p.name: p.read_bytes() for p in PACK.glob("*.csv")}
    out = subprocess.run([sys.executable, str(PACK / "generate.py")], capture_output=True, text=True,
                         env={"PYTHONPATH": str(Path(__file__).resolve().parents[1]), "PATH": ""}, cwd=PACK)
    assert out.returncode == 0, out.stderr
    assert before == {p.name: p.read_bytes() for p in PACK.glob("*.csv")}
