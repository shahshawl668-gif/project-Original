"""The rules that changed in autumn 2026, and the month's input checks beside them.

August, September and October 2026 for one company, validated in order so each
month has the one before it:

* the PF ceiling rose to ₹25,000 on 17 September 2026 — September is held to a
  day-weighted ceiling, October to ₹25,000, and a September shortfall may be
  recovered in October exactly once;
* EPS follows the same ceiling (up to ₹2,083), and an EPS exclusion is no longer
  valid for someone earning up to ₹25,000;
* ESIC coverage holds to the end of a contribution period and is decided afresh
  in October;
* held salaries, undeclared VPF, bank accounts, one-time inputs, LOP reversals,
  overtime in the ESIC wage, headcount roll-forward and unexplained net pay.
"""
from __future__ import annotations

import io
import json
import math

import pandas as pd
import pytest

from app.services.pf_engine import ceiling_for_month

PASSWORD = "Passw0rd!x"
SEPT_DUE = round(0.12 * 19666.67)        # 16 days at ₹15,000 and 14 at ₹25,000: 2,360
SHORTFALL = SEPT_DUE - 1800              # worked on ₹15,000 in September: 560 short


def _ok(r):
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]


@pytest.fixture(scope="module")
def company(client):
    email = "oct-2026@oct-rules-example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD, "company_name": "Oct Rules"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    h = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    h["X-Entity-Id"] = _ok(client.post("/api/org/entities", json={"name": "Oct Rules", "primary_state": "Karnataka"},
                                       headers=h))["id"]
    for name, pf, esic in (("Basic", True, True), ("HRA", False, True), ("Overtime", False, False),
                           ("Incentive", False, True)):
        _ok(client.post("/api/components", headers=h, json={
            "component_name": name, "pf_applicable": pf, "esic_applicable": esic, "pt_applicable": False,
            "included_in_wages": True, "taxable": True}))
    master = pd.DataFrame([
        {"Employee ID": e, "Employee Name": f"Person {e}", "Date of Joining": "2022-04-01", "State": "Karnataka",
         "UAN": "" if e == "E06" else f"1000000000{i:02d}", "ESIC IP Number": f"52000000{i:02d}",
         "EPS Member": "No" if e == "E05" else "Yes", "Status": "On Hold" if e == "E08" else "Active",
         "VPF Declared": "Yes" if e == "E10" else "", "Bank Account": f"5000{i:04d}",
         "Bank Changed On": "2026-10-05" if e == "E10" else ""}
        for i, e in enumerate([f"E{n:02d}" for n in range(1, 16)], 1)])
    buf = io.StringIO()
    master.to_csv(buf, index=False)
    _ok(client.post("/api/workforce/master/commit", headers=h,
                    files={"file": ("m.csv", buf.getvalue().encode(), "text/csv")},
                    data={"meta": json.dumps({"effective_from": "2022-04-01"})}))
    # E16: increment effective 1 Aug 2026, settled in September and (wrongly) again in October.
    # E12: CTC Basic 20,000 + HRA 8,000, so its October HRA of 7,000 is on different days from Basic.
    _ok(client.post("/api/ctc/commit", headers=h, json={"records": [
        {"employee_id": "E16", "effective_from": "2026-04-01", "annual_components": {"basic": 240000}, "annual_ctc": 240000},
        {"employee_id": "E16", "effective_from": "2026-08-01", "annual_components": {"basic": 264000}, "annual_ctc": 264000},
        {"employee_id": "E12", "effective_from": "2026-04-01", "annual_components": {"basic": 240000, "hra": 96000},
         "annual_ctc": 336000},
    ]}))
    return h


def _row(eid, basic, *, pf=0, days=31, hra=0, esic="", ot=0, extra=None):
    row = {"Employee ID": eid, "Employee Name": f"Person {eid}", "State": "Karnataka", "Total Days": days,
           "Paid Days": days, "LOP Days": 0, "Basic": basic, "HRA": hra, "Overtime": ot, "Incentive": 0,
           "PF Employee": pf, "ESIC Employee": esic, "UAN": "" if eid == "E06" else f"1000000000{int(eid[1:]):02d}",
           "Bank Account": f"5000{int(eid[1:]):04d}"}
    row.update(extra or {})
    gross = row["Basic"] + row["HRA"] + row["Overtime"] + row["Incentive"] + float(row.get("LOP Reversal Amount", 0) or 0)
    ded = float(row["PF Employee"] or 0) + float(row["ESIC Employee"] or 0) + float(row.get("Other Deduction", 0) or 0)
    row.setdefault("Gross", gross)
    row.setdefault("Total Deductions", ded)
    row.setdefault("Net", gross - ded)
    return row


def _month(client, h, period, rows):
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    up = client.post("/api/payroll/upload", headers=h, files={"file": ("r.csv", buf.getvalue().encode(), "text/csv")},
                     data={"meta": json.dumps({"period_month": period, "strict_header_check": False})})
    data = _ok(up)
    return _ok(client.post("/api/payroll/validate", headers=h, json={
        "employees": data["employees"], "period_month": period}))


def _fired(data, eid, *, info=False):
    return {f["rule_id"] for f in data["findings"]
            if f["employee_id"] == eid and f["status"] == "FAIL" and (info or f["severity"] != "INFO")}


def _finding(data, eid, rule):
    return next(f for f in data["findings"] if f["employee_id"] == eid and f["rule_id"] == rule)


@pytest.fixture(scope="module")
def months(client, company):
    h = company
    aug = [_row("E01", 30000, pf=1800), _row("E07", 14000, hra=6000, esic=150, pf=1680), _row("E14", 20000, pf=1800),
           _row("E15", 20000, pf=1800), _row("E13", 20000, pf=1800)]
    sep = [_row(e, 30000, pf=1800, days=30) for e in ("E01", "E02", "E03", "E04")] + [
        # crossed ₹21,000 in September: still covered; overtime paid but not ESIC-applicable
        _row("E07", 15000, hra=7000, esic=165, pf=1800, ot=1000, days=30),
        _row("E14", 20000, pf=2360, days=30),
        _row("E15", 20000, pf=2360, days=30), _row("E13", 20000, pf=2360, days=30),
        _row("E16", 22000, pf=2360, days=30, extra={"Basic Arrear": 2000})]
    octo = [
        _row("E01", 30000, pf=3000, extra={"PF Employee Arrear": SHORTFALL, "EPS": 2083}),  # recovered once
        _row("E02", 30000, pf=3000),                                                      # not recovered
        _row("E03", 30000, pf=3000 + SHORTFALL, extra={"PF Employee Arrear": SHORTFALL}),  # recovered twice
        _row("E04", 30000, pf=3000 + SHORTFALL),                                           # recovered in the PF line
        _row("E05", 20000, pf=2400),                    # excluded from EPS, now within the ceiling
        _row("E06", 20000, pf=0),                       # PF due, no UAN
        _row("E07", 15000, hra=7000, esic=165, pf=1800),  # new period: no longer covered
        _row("E08", 20000, pf=2400),                    # on hold, paid
        _row("E09", 20000, pf=2400, extra={"VPF": 1000}),   # VPF not declared
        _row("E10", 20000, pf=2400, extra={"VPF": 1000}),   # VPF declared
        _row("E11", 20000, pf=2400, extra={"Incentive": 5000}),                        # no approval
        _row("E12", 20000, hra=7000, pf=2400,
             extra={"Incentive": 5000, "Approval Ref": "INC-77", "Input Month": "2026-09"}),  # approved, wrong month
        _row("E13", 20000, pf=2400, extra={"LOP Reversal Days": 2}),                    # no LOP last month
        _row("E15", 20000, pf=2400, extra={"Other Deduction": 4000}),                   # net fell, gross did not
        _row("E16", 22000, pf=2640, extra={"Basic Arrear": 2000}),                      # August settled again
    ]
    for r in octo:
        if r["Employee ID"] == "E09":
            r["Bank Account"] = "99999999"       # not the master's account
    return {"aug": _month(client, h, "2026-08-01", aug), "sep": _month(client, h, "2026-09-01", sep),
            "oct": _month(client, h, "2026-10-01", octo)}


# ── the ceiling itself ─────────────────────────────────────────────────────────
def test_the_ceiling_is_15000_before_25000_after_and_weighted_in_september():
    from datetime import date
    from decimal import Decimal
    assert ceiling_for_month(date(2026, 8, 1), Decimal("15000")).ceiling == 15000
    sept = ceiling_for_month(date(2026, 9, 1), Decimal("15000"))
    assert sept.transition and sept.ceiling == Decimal("19666.67") and sept.effective_from == date(2026, 9, 17)
    assert ceiling_for_month(date(2026, 10, 1), Decimal("15000")).ceiling == 25000
    # A company ceiling above the statute stands.
    assert ceiling_for_month(date(2026, 10, 1), Decimal("30000")).ceiling == 30000


def test_august_is_still_on_15000(months):
    assert "STAT-001" not in _fired(months["aug"], "E01")


def test_september_worked_on_the_old_ceiling_is_a_shortfall_to_recover_not_an_error(months):
    assert "STAT-001" not in _fired(months["sep"], "E01")
    f = _finding(months["sep"], "E01", "PF-012")
    assert f["severity"] == "INFO" and str(SHORTFALL) in f["reason"].replace(".00", "")


def test_october_is_capped_at_3000(months):
    assert {"STAT-001", "PF-009"}.isdisjoint(_fired(months["oct"], "E01"))


def test_the_september_shortfall_is_recovered_once(months):
    oct_ = months["oct"]
    assert "PF-012" not in _fired(oct_, "E01")                       # separate line, right amount
    assert "PF-012" not in _fired(oct_, "E04") and "STAT-001" not in _fired(oct_, "E04")  # inside the PF line
    assert _finding(oct_, "E02", "PF-012")["severity"] == "WARNING"   # not recovered
    assert _finding(oct_, "E03", "PF-012")["severity"] == "CRITICAL"  # twice


# ── EPS, UAN ────────────────────────────────────────────────────────────────────
def test_an_eps_exclusion_within_the_new_ceiling_is_flagged(months):
    assert "PF-010" in _fired(months["oct"], "E05")
    assert "PF-010" not in _fired(months["oct"], "E01")


def test_pf_due_with_no_uan_is_flagged_even_when_nothing_was_deducted(months):
    assert "MST-007" in _fired(months["oct"], "E06")


# ── ESIC contribution periods ─────────────────────────────────────────────────
def test_esic_coverage_holds_to_the_end_of_the_period(months):
    # ₹22,000 in September, covered in August: ESIC continues to the end of September.
    assert "STAT-006" not in _fired(months["sep"], "E07")


def test_a_new_period_decides_coverage_afresh(months):
    f = _finding(months["oct"], "E07", "STAT-006")
    assert "new contribution period" in f["reason"]


# ── master data and inputs ─────────────────────────────────────────────────────
def test_a_held_salary_paid_is_critical(months):
    assert _finding(months["oct"], "E08", "MST-009")["severity"] == "CRITICAL"


def test_vpf_only_where_declared(months):
    assert "PF-014" in _fired(months["oct"], "E09")
    assert "PF-014" not in _fired(months["oct"], "E10")


def test_a_bank_account_other_than_the_masters_is_flagged(months):
    assert "DATA-014" in _fired(months["oct"], "E09")
    assert "DATA-014" not in _fired(months["oct"], "E10")


def test_one_time_inputs_need_an_approval(months):
    assert "OTI-001" in _fired(months["oct"], "E11")
    assert "OTI-001" not in _fired(months["oct"], "E12")


def test_a_lop_reversal_needs_earlier_lop(months):
    assert "LOP-004" in _fired(months["oct"], "E13")


def test_overtime_left_out_of_the_esic_wage_is_flagged_for_a_covered_employee(months):
    assert "ESI-009" in _fired(months["sep"], "E07")       # covered (continuing), overtime paid
    assert "ESI-009" not in _fired(months["oct"], "E07")   # no longer covered


def test_someone_missing_without_an_exit_is_named(months):
    assert "HC-001" in _fired(months["oct"], "E14")


def test_net_pay_moved_by_a_deduction_is_flagged(months):
    assert "ADV-004" in _fired(months["oct"], "E15")
    assert "ADV-004" not in _fired(months["oct"], "E01")


def test_headcount_roll_forward_endpoint(client, company, months):
    data = _ok(client.get("/api/validation/periods/2026-10-01/headcount", headers=company))
    assert data["available"] and data["last_month"] == 9 and data["this_month"] == 15
    assert "E14" in data["missing_without_exit"]
    assert set(data["unexplained_additions"]) >= {"E05", "E06", "E08"}


def test_pf_on_code_wages_follows_the_deemed_wage(client):
    r = client.post("/api/auth/signup", json={"email": "codewage@oct-rules-example.com", "password": PASSWORD,
                                              "company_name": "Code wages"})
    h = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    h["X-Entity-Id"] = _ok(client.post("/api/org/entities", json={"name": "CW", "primary_state": "Karnataka"},
                                       headers=h))["id"]
    for name, pf in (("Basic", True), ("HRA", False)):
        _ok(client.post("/api/components", headers=h, json={
            "component_name": name, "pf_applicable": pf, "esic_applicable": False, "pt_applicable": False,
            "included_in_wages": True, "taxable": True}))
    from app.services.config_files import tables_to_csv
    cfg = tables_to_csv({"statutory": [{"pf_on_code_wages": "Yes"}]})
    _ok(client.post("/api/config/bundle/import?dry_run=false", headers=h, files={"file": ("c.csv", cfg, "text/csv")}))
    # Remuneration 25,000, Basic 10,000: 2,500 of HRA is deemed wages -> PF on 12,500.
    data = _month(client, h, "2026-10-01", [_row("W1", 10000, hra=15000, pf=1500), _row("W2", 10000, hra=15000, pf=1200)])
    assert "STAT-001" not in _fired(data, "W1")
    assert "STAT-001" in _fired(data, "W2")
    assert math.isclose(_finding(data, "W2", "STAT-001")["financial_impact"], 300, abs_tol=1)


def test_eps_follows_the_new_ceiling_up_to_2083(months):
    assert "PF-004" not in _fired(months["oct"], "E01")


def test_a_bank_change_this_month_needs_proof(months):
    assert "DATA-013" in _fired(months["oct"], "E10")


def test_a_one_time_input_for_another_month_is_flagged(months):
    assert "OTI-002" in _fired(months["oct"], "E12")


def test_components_prorated_on_different_days_are_flagged(months):
    assert "LOP-006" in _fired(months["oct"], "E12")


def test_an_arrear_settled_again_is_flagged(months):
    assert "ARR-005" not in _fired(months["sep"], "E16")
    assert "ARR-005" in _fired(months["oct"], "E16")
