"""A whole financial year, April 2026 to March 2027, run month by month through the API.

The pack is testdata/payroll-fy2026-27: one company, 24 people, twelve months of
master changes, CTC revisions, attendance and salary registers, with the payroll
worked out independently by the pack's generator and one or two mistakes planted
each month. Each month is loaded the way a payroll team would load it and
validated with the months before it on file. Every planted mistake must be
reported, and nobody else may get a warning or a critical finding.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PACK = Path(__file__).resolve().parents[2] / "testdata" / "payroll-fy2026-27"
KEY = json.loads((PACK / "answer_key.json").read_text())
MONTHS = sorted(p.name for p in (PACK / "months").iterdir())
PASSWORD = "Passw0rd!x"


def _file(path: Path):
    return {"file": (path.name, path.read_bytes(), "text/csv")}


def _ok(r):
    assert r.status_code == 200, r.text
    return r.json()["data"]


def run_year(client) -> dict[str, dict]:
    email = "full-year@fy-example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD, "company_name": "FY Retail"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    h = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    h["X-Entity-Id"] = _ok(client.post("/api/org/entities", json={"name": "FY Retail Pvt Ltd", "primary_state": "Karnataka"},
                                       headers=h))["id"]
    _ok(client.post("/api/config/bundle/import?dry_run=false", files=_file(PACK / "1_configuration.csv"), headers=h))
    out: dict[str, dict] = {}
    for month in MONTHS:
        folder = PACK / "months" / month
        first = f"{month}-01"
        if (folder / "employee_master.csv").exists():
            _ok(client.post("/api/workforce/master/commit", files=_file(folder / "employee_master.csv"),
                            data={"meta": json.dumps({"effective_from": first})}, headers=h))
        if (folder / "ctc.csv").exists():
            parsed = _ok(client.post("/api/ctc/upload", files=_file(folder / "ctc.csv"),
                                     data={"meta": json.dumps({"default_effective_from": first})}, headers=h))
            _ok(client.post("/api/ctc/commit", headers=h, json={"filename": "ctc.csv", "default_effective_from": first,
                                                                 "records": parsed["records"]}))
        meta = {"meta": json.dumps({"period_month": first})}
        attendance = _ok(client.post("/api/workforce/attendance/validate", files=_file(folder / "attendance.csv"),
                                     data=meta, headers=h))
        _ok(client.post("/api/workforce/attendance/commit", files=_file(folder / "attendance.csv"), data=meta, headers=h))
        up = _ok(client.post("/api/payroll/upload", files=_file(folder / "salary_register.csv"), headers=h,
                             data={"meta": json.dumps({"period_month": first, "strict_header_check": True})}))
        result = _ok(client.post("/api/payroll/validate", headers=h, json={"employees": up["employees"],
                                                                         "period_month": first}))
        out[month] = {"attendance": attendance, "validation": result}
    return out


@pytest.fixture(scope="module")
def year(client):
    return run_year(client)


def _fired(data) -> dict[str, set[str]]:
    fired: dict[str, set[str]] = {}
    for f in data["findings"]:
        if f["status"] == "FAIL" and f["severity"] != "INFO":
            fired.setdefault(f["employee_id"], set()).add(f["rule_id"])
    return fired


@pytest.mark.parametrize("month", MONTHS)
def test_every_planted_mistake_is_reported(year, month):
    fired = _fired(year[month]["validation"])
    for employee, entry in KEY.get(month, {}).items():
        assert set(entry["rules"]) <= fired.get(employee, set()), \
            f"{month} {employee} ({entry['mistake']}): got {sorted(fired.get(employee, set()))}"


@pytest.mark.parametrize("month", MONTHS)
def test_correct_payslips_are_left_alone(year, month):
    fired = _fired(year[month]["validation"])
    planted = KEY.get(month, {})
    unexpected = {e: sorted(r - set(planted.get(e, {}).get("rules", []))) for e, r in fired.items()}
    unexpected = {e: r for e, r in unexpected.items() if r}
    assert not unexpected, f"{month}: {unexpected}"


@pytest.mark.parametrize("month", MONTHS)
def test_attendance_files_are_consistent(year, month):
    assert year[month]["attendance"]["findings"] == [], year[month]["attendance"]["findings"][:3]


def test_the_answer_key_matches_the_generator():
    before = {p.relative_to(PACK): p.read_bytes() for p in PACK.rglob("*.csv")}
    out = subprocess.run([sys.executable, str(PACK / "generate.py")], capture_output=True, text=True,
                         env={"PYTHONPATH": str(Path(__file__).resolve().parents[1]), "PATH": ""}, cwd=PACK)
    assert out.returncode == 0, out.stderr
    assert before == {p.relative_to(PACK): p.read_bytes() for p in PACK.rglob("*.csv")}


@pytest.mark.parametrize("month", MONTHS)
def test_every_register_column_is_recognised(year, month):
    """The pack uses only columns the template documents: none may be reported as ignored."""
    unmapped = {f["component"] for f in year[month]["validation"]["findings"] if f["rule_id"] == "COMP-001"}
    assert not unmapped, f"{month}: {sorted(unmapped)}"
