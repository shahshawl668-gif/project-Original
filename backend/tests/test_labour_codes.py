"""
The Labour Codes, in force from 21 November 2025, as the engine checks them.

* LC-001 — the Code on Wages s.2(y): exclusions above half of remuneration are
  deemed wages. The answer key is worked by hand in each test.
* GRAT-002 / GRAT-005 — a fixed-term employee leaving under the Codes earns
  gratuity after one year (Social Security Code s.53), not five.
* GRAT-003 — gratuity at an exit under the Codes is on the deemed wages.

All data is synthetic.
"""
from __future__ import annotations

import io
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.schemas.rule_thresholds import RuleThresholdsConfig
from app.services import labour_codes
from app.services.rule_engine_v2 import build_findings
from tests.test_coverage import _outcome
from tests.test_run_history import _company, _data, _drain

LC = RuleThresholdsConfig().labour_codes


def _comp(pf=False, included=True):
    return SimpleNamespace(pf_applicable=pf, included_in_wages=included, esic_applicable=False,
                           pt_applicable=False, lwf_applicable=False, taxable=True)


COMPS = {"basic": _comp(pf=True), "hra": _comp(), "special": _comp(), "gratuity": _comp()}


def _pf_calc(pf_wage, restrict=True):
    capped = min(pf_wage, Decimal("15000")) if restrict else pf_wage
    return {"pf_type": "restricted" if restrict and pf_wage > 15000 else "unrestricted",
            "pf_employee": float(capped * Decimal("0.12")), "pf_employer_total": float(capped * Decimal("0.12")),
            "pf_wage_capped": float(capped), "_ceiling": 15000, "_pf_wage_full": float(pf_wage),
            "_restrict": restrict, "_emp_rate": 0.12, "_er_rate": 0.12}


def run(amounts, *, row=None, period=date(2026, 4, 1), thresholds=None, restrict=True):
    regular = {k: Decimal(str(v)) for k, v in amounts.items()}
    return build_findings(
        employee_id="T1", employee_name="Synthetic", row={"employee_id": "T1", **(row or {})},
        comp_by_key=COMPS, regular=regular, arrear_by_base={}, inc_arrear_total=Decimal("0"),
        paid_days=Decimal("30"), lop_days=Decimal("0"), days_in_month=30,
        pf_calc=_pf_calc(regular.get("basic", Decimal("0")), restrict),
        esic_calc={"esic_employee": 0, "esic_employer": 0, "esic_eligible": False,
                   "_ceiling": 21000, "_emp_rate": 0.0075, "_er_rate": 0.0325},
        pt_due=Decimal("0"), lwf_eamt=Decimal("0"), lwf_oamt=Decimal("0"),
        prior_components=None, prior_is_joiner=True, lop_diffs=[], inc_info={}, tds_risk=[],
        thresholds=thresholds or RuleThresholdsConfig(), period_month=period,
        # The 50% test reads the CTC break-up; here the structure is the month's pay.
        ctc_components=regular,
    )


def only(findings, rule_id):
    hits = [f for f in findings if f.rule_id == rule_id]
    assert len(hits) <= 1, hits
    return hits[0] if hits else None


# ── the wage test itself ─────────────────────────────────────────────────────

def test_exclusions_above_half_are_deemed_wages():
    # Remuneration 50,000; wages 20,000; exclusions 30,000; half is 25,000.
    t = labour_codes.wage_test({"basic": Decimal("20000"), "hra": Decimal("15000"), "special": Decimal("15000")},
                               COMPS, LC)
    assert (t.wages, t.remuneration, t.excluded, t.allowed) == (20000, 50000, 30000, 25000)
    assert t.deemed_addition == Decimal("5000.00") and t.code_wages == Decimal("25000.00")


def test_exactly_half_is_within_the_definition():
    t = labour_codes.wage_test({"basic": Decimal("25000"), "hra": Decimal("25000")}, COMPS, LC)
    assert t.deemed_addition == 0


def test_an_exit_payment_is_not_part_of_the_monthly_test():
    # Without the exclusion a ₹2 lakh gratuity would itself be deemed wages.
    t = labour_codes.wage_test({"basic": Decimal("30000"), "hra": Decimal("10000"),
                                "gratuity": Decimal("200000")}, COMPS, LC)
    assert t.remuneration == 40000 and t.deemed_addition == 0


def test_an_annual_bonus_month_is_not_a_structure_change():
    comps = {**COMPS, "bonus": _comp()}
    amounts = {"basic": Decimal("30000"), "hra": Decimal("10000"), "bonus": Decimal("60000")}
    assert labour_codes.wage_test(amounts, comps, LC).deemed_addition == 0
    # A company that pays bonus monthly takes it off the one-off list, and it counts.
    monthly = LC.model_copy(update={"one_off_component_keys": ["gratuity"]})
    assert labour_codes.wage_test(amounts, comps, monthly).deemed_addition == Decimal("20000.00")


def test_configured_wage_components_replace_the_pf_proxy():
    # A company that marks Special Allowance PF-applicable would otherwise
    # count it as wages; naming Basic alone puts it back among the exclusions.
    comps = {**COMPS, "special": _comp(pf=True)}
    amounts = {"basic": Decimal("20000"), "hra": Decimal("10000"), "special": Decimal("20000")}
    assert labour_codes.wage_test(amounts, comps, LC).deemed_addition == 0
    named = LC.model_copy(update={"wage_component_keys": ["basic"]})
    t = labour_codes.wage_test(amounts, comps, named)
    assert t.deemed_addition == Decimal("5000.00") and t.basis.endswith("basic")


def test_no_component_marked_as_wages_is_no_basis_not_a_pass():
    t = labour_codes.wage_test({"hra": Decimal("10000")}, {"hra": _comp()}, LC)
    assert t.basis_known is False


def test_the_codes_apply_from_the_month_they_took_effect():
    assert not labour_codes.in_force(LC, date(2025, 10, 1))
    assert labour_codes.in_force(LC, date(2025, 11, 1))      # in force from the 21st
    assert labour_codes.in_force(LC, date(2026, 4, 1))
    assert not labour_codes.in_force(LC, None)


def test_fixed_term_markers_ignore_case_and_punctuation():
    for value in ("Fixed-Term", "fixed_term", "FIXED TERM EMPLOYEE", "FTC"):
        assert labour_codes.is_fixed_term(value, LC), value
    for value in ("permanent", "contract", "", None):
        assert not labour_codes.is_fixed_term(value, LC), value


# ── LC-001 in the engine ─────────────────────────────────────────────────────

def test_lc001_reports_the_deemed_addition_and_its_pf_effect():
    # Wages 10,000 of 25,000: exclusions 15,000, allowed 12,500, deemed 2,500.
    # PF wage 10,000 → 12,500 under the ceiling: employee PF +₹300.
    f = only(run({"basic": 10000, "hra": 8000, "special": 7000}), "LC-001")
    assert f.status == "FAIL" and f.severity == "WARNING"
    assert "2500.00 is added" in f.reason and "are 12500.00" in f.reason
    assert "employee PF rises by ₹300.00" in f.reason
    assert f.financial_impact == 300.0


def test_lc001_at_the_pf_ceiling_says_pf_does_not_change():
    f = only(run({"basic": 20000, "hra": 15000, "special": 15000}), "LC-001")
    assert f.status == "FAIL" and "5000.00 is added" in f.reason
    assert "PF does not change" in f.reason and f.financial_impact == 0.0


def test_lc001_on_full_wages_pf_follows_the_deemed_wages():
    f = only(run({"basic": 20000, "hra": 15000, "special": 15000}, restrict=False), "LC-001")
    assert "employee PF rises by ₹600.00" in f.reason


def test_lc001_passes_a_compliant_structure_and_says_so():
    f = only(run({"basic": 30000, "hra": 12000, "special": 8000}), "LC-001")
    assert f.status == "PASS" and "60.0%" in f.reason


def test_lc001_skips_a_row_of_arrears_only():
    arrears_only = SimpleNamespace(has_regular=False, any_arrear=False)
    regular = {k: Decimal(str(v)) for k, v in {"basic": 10000, "hra": 8000, "special": 7000}.items()}
    findings = build_findings(
        employee_id="T1", employee_name="Synthetic", row={"employee_id": "T1"},
        comp_by_key=COMPS, regular=regular, arrear_by_base={}, inc_arrear_total=Decimal("0"),
        paid_days=Decimal("30"), lop_days=Decimal("0"), days_in_month=30, pf_calc=_pf_calc(Decimal("10000")),
        esic_calc={"esic_employee": 0, "esic_employer": 0, "esic_eligible": False,
                   "_ceiling": 21000, "_emp_rate": 0.0075, "_er_rate": 0.0325},
        pt_due=Decimal("0"), lwf_eamt=Decimal("0"), lwf_oamt=Decimal("0"),
        prior_components=None, prior_is_joiner=True, lop_diffs=[], inc_info={}, tds_risk=[],
        thresholds=RuleThresholdsConfig(), period_month=date(2026, 4, 1), composition=arrears_only,
    )
    assert only(findings, "LC-001") is None


def test_lc001_is_silent_before_the_codes():
    assert only(run({"basic": 10000, "hra": 8000, "special": 7000}, period=date(2025, 10, 1)), "LC-001") is None


def test_lc001_follows_a_notified_change_of_the_half():
    # A notification moving the cap to 40% is a setting, not a release.
    cfg = RuleThresholdsConfig()
    cfg.labour_codes.wage_exclusion_cap_pct = Decimal("40")
    f = only(run({"basic": 30000, "hra": 12000, "special": 8000}, thresholds=cfg), "LC-001")
    assert f.status == "PASS"
    f = only(run({"basic": 25000, "hra": 15000, "special": 10000}, thresholds=cfg), "LC-001")
    # Remuneration 50,000; allowed 20,000; exclusions 25,000 → 5,000 deemed.
    assert f.status == "FAIL" and "5000.00 is added" in f.reason


# ── gratuity ─────────────────────────────────────────────────────────────────

def _exit(doj, dol, employment_type="", gratuity="20000", period=date(2026, 4, 1)):
    row = {"doj": doj, "dol": dol, "gratuity": gratuity, "employment_type": employment_type}
    return run({"basic": 30000, "hra": 12000, "special": 8000}, row=row, period=period)


def test_fixed_term_gratuity_after_one_year_is_not_flagged():
    assert only(_exit("2024-09-01", "2026-03-31", "Fixed Term"), "GRAT-002") is None
    # The same service as a permanent employee is below five years.
    assert only(_exit("2024-09-01", "2026-03-31", "Permanent"), "GRAT-002").status == "FAIL"


def test_fixed_term_below_one_year_is_flagged_counting_days():
    # Seven months rounds to a completed year, but it is not a year of service.
    f = only(_exit("2025-09-01", "2026-03-31", "fixed-term"), "GRAT-002")
    assert f.status == "FAIL" and "fixed-term employee" in f.reason and f.expected_value == "≥ 1 years service"
    assert f.actual_value == "211 days"


def test_fixed_term_exit_before_the_codes_keeps_five_years():
    f = only(_exit("2023-09-01", "2025-10-31", "fixed term", period=date(2025, 10, 1)), "GRAT-002")
    assert f.status == "FAIL" and f.expected_value == "≥ 5 years service"


def test_gratuity_at_an_exit_under_the_codes_is_on_deemed_wages():
    # Basic 10,000 of 25,000 → wages under the Codes 12,500.
    # 12,500 × 15/26 × 6 years = 43,269.23; on Basic alone it would be 34,615.38.
    row = {"doj": "2020-04-01", "dol": "2026-03-31", "gratuity": "34615.38"}
    f = only(run({"basic": 10000, "hra": 8000, "special": 7000}, row=row), "GRAT-003")
    assert f.status == "FAIL" and f.expected_value == "43269.23"
    assert "wages under the Labour Codes 12500.00" in f.reason
    row["gratuity"] = "43269.23"
    assert only(run({"basic": 10000, "hra": 8000, "special": 7000}, row=row), "GRAT-003") is None


# ── end to end: coverage outcome and the master check ───────────────────────

HEADER = "employee_id,employee_name,state,paid_days,lop_days,basic,hra,special allowance,pf_employee,pf_employer,pan"


def _lc_company(client):
    headers = _company(client, "lc")
    # The history fixture marks Special Allowance PF-applicable; under the
    # Codes it is an exclusion, so name the wage components explicitly.
    cfg = _data(client.get("/api/config/statutory/rule-thresholds", headers=headers))
    cfg["labour_codes"]["wage_component_keys"] = ["basic"]
    r = client.put("/api/config/statutory/rule-thresholds", headers=headers, json=cfg)
    assert r.status_code == 200, r.text
    return headers


def _validate(client, headers, period, rows):
    content = ("\n".join([HEADER, *rows]) + "\n").encode()
    r = client.post("/api/payroll/upload", headers=headers,
                    files={"file": ("r.csv", io.BytesIO(content), "text/csv")},
                    data={"meta": json.dumps({"period_month": period, "strict_header_check": False,
                                              "return_employees": False})})
    assert r.status_code == 200, r.text
    job = _data(client.post("/api/validation/jobs", headers=headers, json={"period_month": period}))["job"]
    _drain()
    job = _data(client.get(f"/api/validation/jobs/{job['id']}", headers=headers))
    assert job["state"] == "succeeded", job
    return job["run_id"]


@pytest.fixture()
def lc_company(client):
    return _lc_company(client)


def test_coverage_shows_failed_passed_and_not_applicable(client, lc_company):
    rows = ["E1,Person E1,Karnataka,30,0,10000,8000,7000,1800,1800,ABCPE1234F",
            "E2,Person E2,Karnataka,30,0,30000,12000,8000,1800,1800,ABCPE1234G"]
    # The 50% test reads the CTC break-up.
    records = [{"employee_id": e, "effective_from": "2025-04-01",
                "annual_components": {"basic": b * 12, "hra": h * 12, "special_allowance": s * 12},
                "annual_ctc": (b + h + s) * 12} for e, b, h, s in (("E1", 10000, 8000, 7000), ("E2", 30000, 12000, 8000))]
    assert client.post("/api/ctc/commit", headers=lc_company, json={"records": records}).status_code == 200
    run_id = _validate(client, lc_company, "2026-06-01", rows)
    assert _outcome(client, lc_company, run_id, "E1", "LC-001")["outcome"] == "failed"
    assert _outcome(client, lc_company, run_id, "E2", "LC-001")["outcome"] == "passed"
    before = _validate(client, lc_company, "2025-10-01", rows)
    na = _outcome(client, lc_company, before, "E1", "LC-001")
    assert na["outcome"] == "not_applicable" and "before the Labour Codes" in na["reason"]


def test_thresholds_round_trip_and_refuse_an_impossible_cap(client, lc_company):
    cfg = _data(client.get("/api/config/statutory/rule-thresholds", headers=lc_company))
    assert cfg["labour_codes"]["effective_from"] == "2025-11-21"
    assert cfg["labour_codes"]["fixed_term_gratuity_min_years"] in ("1", 1, "1.0")
    cfg["labour_codes"]["wage_exclusion_cap_pct"] = "150"
    assert client.put("/api/config/statutory/rule-thresholds", headers=lc_company, json=cfg).status_code in (400, 422)


def test_master_gratuity_check_honours_fixed_term(client, lc_company):
    master = (b"employee_id,employee_name,date_of_joining,date_of_exit,employment_type\n"
              b"E1,Person E1,2024-09-01,2026-05-31,Fixed Term\n"
              b"E2,Person E2,2024-09-01,2026-05-31,Permanent\n")
    r = client.post("/api/workforce/master/commit", headers=lc_company,
                    files={"file": ("m.csv", io.BytesIO(master), "text/csv")},
                    data={"meta": '{"effective_from": "2024-04-01"}'})
    assert r.status_code == 200, r.text
    assert client.post("/api/components", headers=lc_company,
                       json={"component_name": "Gratuity", "taxable": True}).status_code == 201
    header = HEADER + ",gratuity"
    rows = ["E1,Person E1,Karnataka,30,0,30000,12000,8000,1800,1800,ABCPE1234F,30000",
            "E2,Person E2,Karnataka,30,0,30000,12000,8000,1800,1800,ABCPE1234G,30000"]
    content = ("\n".join([header, *rows]) + "\n").encode()
    r = client.post("/api/payroll/upload", headers=lc_company,
                    files={"file": ("r.csv", io.BytesIO(content), "text/csv")},
                    data={"meta": json.dumps({"period_month": "2026-06-01", "strict_header_check": False,
                                              "return_employees": False})})
    assert r.status_code == 200, r.text
    job = _data(client.post("/api/validation/jobs", headers=lc_company, json={"period_month": "2026-06-01"}))["job"]
    _drain()
    run_id = _data(client.get(f"/api/validation/jobs/{job['id']}", headers=lc_company))["run_id"]
    assert _outcome(client, lc_company, run_id, "E1", "GRAT-005")["outcome"] == "passed"
    failed = _outcome(client, lc_company, run_id, "E2", "GRAT-005")
    assert failed["outcome"] == "failed" and "5-year" in failed["reason"]
