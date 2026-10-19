"""One register, one validation: increments mid-month, arrears for earlier months, and proration by days.

The register holds everyone. An employee whose increment lands part-way through the month,
one whose increment is two or three months old and is being settled now, and one who took
loss of pay are all in the same file, validated in the same pass, each against their own CTC.
"""
from __future__ import annotations

import io

import pandas as pd
import pytest

from app.services import increments

PASSWORD = "Passw0rd!x"
PERIOD = "2026-08-01"
DAYS = 31


@pytest.fixture(scope="module")
def world(client):
    r = client.post("/api/auth/signup", json={"email": "increments-e2e@inc-example.com", "password": PASSWORD,
                                              "company_name": "Increments"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": "increments-e2e@inc-example.com", "password": PASSWORD})
    h = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    h["X-Entity-Id"] = client.post("/api/org/entities", json={"name": "Inc", "primary_state": "Karnataka"},
                                   headers=h).json()["data"]["id"]
    for name, pf in (("Basic", True), ("HRA", False)):
        assert client.post("/api/components", headers=h, json={
            "component_name": name, "pf_applicable": pf, "esic_applicable": False, "pt_applicable": False,
            "included_in_wages": True, "taxable": True}).status_code == 201
    return h


def _ctc(client, h, eid, revisions):
    """revisions: [(effective_from, monthly basic)] -- HRA is 40% of basic."""
    records = [{"employee_id": eid, "effective_from": eff, "annual_components": {"basic": basic * 12, "hra": basic * 12 * 0.4},
                "annual_ctc": basic * 12 * 1.4} for eff, basic in revisions]
    assert client.post("/api/ctc/commit", headers=h, json={"records": records}).status_code == 200


def _validate(client, h, rows):
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    up = client.post("/api/payroll/upload", headers=h, files={"file": ("r.csv", buf.getvalue().encode(), "text/csv")},
                     data={"meta": '{"period_month":"2026-08-01","strict_header_check":false}'})
    assert up.status_code == 200, up.text
    v = client.post("/api/payroll/validate", headers=h, json={
        "employees": up.json()["data"]["employees"], "period_month": PERIOD, "as_of_date": "2026-08-31"})
    assert v.status_code == 200, v.text
    return v.json()["data"]


def _row(eid, basic, *, arrear=0, lop=0, pf=None):
    paid = DAYS - lop
    return {"Employee ID": eid, "UAN": f"10120260{ord(eid[0])}{int(eid[1:]):02d}", "Basic": basic, "HRA": round(basic * 0.4, 2), "Basic Arrear": arrear, "HRA Arrear": round(arrear * 0.4, 2),
            "Total Days": DAYS, "Paid Days": paid, "LOP Days": lop,
            "PF Employee": pf if pf is not None else round(min(basic, 15000) * 0.12)}


def _rules(data, eid):
    return {f["rule_id"] for f in data["findings"] if f["employee_id"] == eid and f["status"] == "FAIL" and f["severity"] != "INFO"}


BLEND = round(20000 * 15 / 31 + 25000 * 16 / 31, 2)               # 22,580.65: revision effective 16 Aug
ARREAR_2M = 5000 * 2                                              # effective 1 Jun: June and July
ARREAR_3M = round(5000 * 16 / 31 + 5000 * 2, 2)                   # effective 16 May: part of May, June, July


@pytest.fixture(scope="module")
def run(client, world):
    h = world
    _ctc(client, h, "M1", [("2026-04-01", 20000), ("2026-08-16", 25000)])   # mid-month, paid correctly
    _ctc(client, h, "M2", [("2026-04-01", 20000), ("2026-08-16", 25000)])   # mid-month, paid the full new amount
    _ctc(client, h, "M3", [("2026-04-01", 20000), ("2026-08-16", 25000)])   # mid-month, increment ignored
    _ctc(client, h, "A1", [("2026-04-01", 20000), ("2026-06-01", 25000)])   # two months' arrear, correct
    _ctc(client, h, "A2", [("2026-04-01", 20000), ("2026-06-01", 25000)])   # two months' arrear, short
    _ctc(client, h, "A3", [("2026-04-01", 20000), ("2026-05-16", 25000)])   # three months' arrear, correct
    _ctc(client, h, "A4", [("2026-04-01", 20000), ("2026-05-16", 25000)])   # three months' arrear, whole months paid
    _ctc(client, h, "A5", [("2026-04-01", 20000), ("2026-06-01", 25000)])   # still paid at the old pay
    _ctc(client, h, "L1", [("2026-04-01", 20000)])                          # five days' loss of pay, correct
    _ctc(client, h, "L2", [("2026-04-01", 20000)])                          # five days' loss of pay, not deducted
    rows = [
        _row("M1", BLEND), _row("M2", 25000), _row("M3", 20000),
        _row("A1", 25000, arrear=ARREAR_2M), _row("A2", 25000, arrear=7500),
        _row("A3", 25000, arrear=ARREAR_3M), _row("A4", 25000, arrear=15000),
        _row("A5", 20000),
        _row("L1", round(20000 * 26 / 31, 2), lop=5), _row("L2", 20000, lop=5),
    ]
    return _validate(client, h, rows)


def test_the_blend_is_by_days_of_each_rate():
    from types import SimpleNamespace as N
    from datetime import date
    old = N(effective_from=date(2026, 4, 1), annual_components={"basic": 240000})
    new = N(effective_from=date(2026, 8, 16), annual_components={"basic": 300000})
    s = increments.structure_for_month(new, old, date(2026, 8, 1))
    assert (s.mid_month, s.days_old, s.days_new) == (True, 15, 16)
    assert round(float(s.expected["basic"]), 2) == BLEND
    arrears, months = increments.expected_arrears(N(effective_from=date(2026, 5, 16), annual_components={"basic": 300000}),
                                                  old, date(2026, 8, 1))
    assert float(arrears["basic"]) == ARREAR_3M and round(float(months), 3) == 2.516


def test_a_correctly_paid_mid_month_increment_is_clean(run):
    assert _rules(run, "M1") == set()


def test_a_mid_month_increment_paid_whole_or_ignored_is_reported_as_such(run):
    assert "INC-002" in _rules(run, "M2")
    assert "INC-002" in _rules(run, "M3")


def test_arrears_for_two_and_three_months_are_checked_against_the_ctc_revision(run):
    assert _rules(run, "A1") == set()
    assert _rules(run, "A3") == set()
    assert "MOM-006" in _rules(run, "A2")      # 7,500 against 10,000
    assert "MOM-006" in _rules(run, "A4")      # three whole months against two and a part


def test_pay_still_at_the_old_structure_is_an_increment_not_applied(run):
    assert "INC-001" in _rules(run, "A5")


def test_basic_follows_working_days(run):
    assert _rules(run, "L1") == set()
    assert "LOP-002" in _rules(run, "L2") or "ATT-020" in _rules(run, "L2")


def test_pf_follows_the_configured_ceiling_for_every_kind_of_row(run):
    by_id = {r["employee_id"]: r for r in run["results"]}
    for eid in ("M1", "A1", "A3", "L1"):
        wage = by_id[eid]["pf_wage"]
        assert by_id[eid]["pf_amount_employee"] == round(min(wage, 15000) * 0.12, 2), eid
    assert "STAT-001" not in {f["rule_id"] for f in run["findings"] if f["status"] == "FAIL"}


def test_one_register_one_run_no_declared_type(client, world, run):
    runs = client.get("/api/findings/runs", headers=world).json()["data"]
    assert len(runs) >= 1 and run["lifecycle"]["run_id"]
