"""Boundary tests for identity + deep statutory rules (spec §2, §4-10)."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.schemas.rule_thresholds import RuleThresholdsConfig
from app.services import identity_checks as idc
from app.services.rule_engine_v2 import batch_findings, build_findings


# ── identity validators ──────────────────────────────────────────────────────

def _valid_aadhaar() -> str:
    # brute-force a check digit so the test doesn't embed a real Aadhaar
    for d in "0123456789":
        cand = "23456789012" + d
        if idc._verhoeff_valid(cand):
            return cand
    raise AssertionError("no valid check digit found")


def test_pan_validation():
    assert idc.validate_pan("ABCPE1234F")[0] is True
    assert idc.validate_pan("abcpe1234f")[0] is True  # normalised
    assert idc.validate_pan("ABCDE1234F") == (False, "not_individual")
    assert idc.validate_pan("ABCPE123F")[1] == "format"
    assert idc.validate_pan("")[1] == "missing"


def test_aadhaar_validation():
    good = _valid_aadhaar()
    assert idc.validate_aadhaar(good)[0] is True
    bad = good[:-1] + ("0" if good[-1] != "0" else "1")
    assert idc.validate_aadhaar(bad)[1] == "checksum"
    assert idc.validate_aadhaar("1" + good[1:])[1] == "leading_digit"
    assert idc.validate_aadhaar("12345")[1] == "format"


def test_uan_esi_ifsc_formats():
    assert idc.validate_uan("123456789012")[0] is True
    assert idc.validate_uan("12345678901")[1] == "format"
    assert idc.validate_esi_number("1234567890")[0] is True
    assert idc.validate_esi_number("12345678901234567")[0] is True
    assert idc.validate_esi_number("123456789")[1] == "format"
    assert idc.validate_ifsc("HDFC0001234")[0] is True
    assert idc.validate_ifsc("HDFC1001234")[1] == "format"
    assert idc.clean_id("123456789012.0") == "123456789012"  # Excel float artefact


def test_completed_service_years_rounding():
    doj = date(2020, 1, 1)
    assert idc.completed_service_years(doj, date(2024, 6, 30)) == 4   # 4y ~181d
    assert idc.completed_service_years(doj, date(2024, 7, 15)) == 5   # >6 months rounds up
    assert idc.completed_service_years(doj, date(2025, 1, 1)) == 5


# ── build_findings harness ───────────────────────────────────────────────────

def _comp(name, taxable=True):
    return SimpleNamespace(component_name=name, included_in_wages=True,
                           pf_applicable=(name == "basic"), esic_applicable=False,
                           pt_applicable=False, lwf_applicable=False, taxable=taxable)


def run_engine(row, *, thresholds=None, period=date(2026, 4, 1), pf_wage=None,
               days_in_month=30):
    comp_by_key = {"basic": _comp("basic"), "hra": _comp("hra", taxable=False)}
    regular = {"basic": Decimal(str(row.get("basic", 0))), "hra": Decimal(str(row.get("hra", 0)))}
    wage = pf_wage if pf_wage is not None else regular["basic"]
    return build_findings(
        employee_id=str(row.get("employee_id", "T1")),
        employee_name="Test",
        row=row, comp_by_key=comp_by_key, regular=regular,
        arrear_by_base={}, inc_arrear_total=Decimal("0"),
        paid_days=Decimal(str(row.get("paid_days", 30))), lop_days=Decimal("0"),
        days_in_month=days_in_month,
        pf_calc={"pf_employee": float(wage) * 0.12, "pf_employer_total": float(wage) * 0.12,
                 "pf_wage_capped": float(min(wage, Decimal("15000"))),
                 "_ceiling": 15000, "_emp_rate": 0.12},
        esic_calc={"esic_employee": 0, "esic_employer": 0, "esic_eligible": False,
                   "_ceiling": 21000, "_emp_rate": 0.0075, "_er_rate": 0.0325},
        pt_due=Decimal("0"), lwf_eamt=Decimal("0"), lwf_oamt=Decimal("0"),
        prior_components=None, prior_is_joiner=True,
        lop_diffs=[], inc_info={}, tds_risk=[],
        thresholds=thresholds or RuleThresholdsConfig(),
        period_month=period,
    )


def rules_failed(findings):
    return {f.rule_id for f in findings if f.status == "FAIL"}


# ── §2 identity rules ────────────────────────────────────────────────────────

def test_invalid_pan_and_esi_number_flagged():
    row = {"employee_id": "E1", "basic": 20000, "pan": "BADPAN", "esic_employee": 100,
           "esi_number": "99"}
    got = rules_failed(run_engine(row))
    assert "ID-001" in got and "ID-004" in got


def test_child_labour_and_adolescent():
    row = {"employee_id": "E1", "basic": 10000, "dob": "2014-01-01"}  # age ~12 in Apr 2026
    assert "ID-006" in rules_failed(run_engine(row))
    row2 = {"employee_id": "E1", "basic": 10000, "dob": "2010-01-01"}  # ~16 no permit
    assert "ID-006" in rules_failed(run_engine(row2))
    row3 = {**row2, "adolescent_permit": "1"}
    assert "ID-006" not in rules_failed(run_engine(row3))


def test_salary_after_exit():
    row = {"employee_id": "E1", "basic": 10000, "dol": "2026-02-15"}
    assert "ID-008" in rules_failed(run_engine(row))


def test_duplicate_pan_and_bank_batch():
    employees = [
        {"employee_id": "A", "pan": "ABCPE1234F", "bank_account": "111"},
        {"employee_id": "B", "pan": "ABCPE1234F", "bank_account": "111"},
    ]
    got = {f.rule_id for f in batch_findings(employees)}
    assert "DATA-006" in got and "DATA-009" in got


# ── §4 PF: EPS boundaries ────────────────────────────────────────────────────

def test_eps_cap_at_exactly_15000():
    # 8.33% of 15,000 = 1,249.50 → register 1,250 within ₹1 tolerance
    row = {"employee_id": "E1", "basic": 15000, "eps": 1250, "doj": "2010-05-01"}
    assert "PF-004" not in rules_failed(run_engine(row))
    row_bad = {**row, "eps": 1412}
    assert "PF-004" in rules_failed(run_engine(row_bad))


def test_eps_zero_for_post_2014_high_wage_joiner():
    row = {"employee_id": "E1", "basic": 20000, "eps": 1250, "doj": "2015-01-01"}
    assert "PF-004" in rules_failed(run_engine(row, pf_wage=Decimal("20000")))
    row_ok = {**row, "eps": 0}
    assert "PF-004" not in rules_failed(run_engine(row_ok, pf_wage=Decimal("20000")))


def test_eps_stops_at_age_58():
    row = {"employee_id": "E1", "basic": 15000, "eps": 1250,
           "doj": "2000-01-01", "dob": "1966-01-01"}  # 60 in Apr 2026
    assert "PF-004" in rules_failed(run_engine(row))


def test_international_worker_must_not_be_capped():
    row = {"employee_id": "E1", "basic": 40000, "international_worker": "yes"}
    assert "PF-008" in rules_failed(run_engine(row, pf_wage=Decimal("40000")))


# ── §5-§7 ESI / PT ───────────────────────────────────────────────────────────

def test_esi_daily_wage_exemption():
    # esic wage 0 in harness; use hra as esic component? esic_wage_total sums
    # esic_applicable comps — none in harness, so daily wage is 0 ≤ 176.
    row = {"employee_id": "E1", "basic": 4000, "esic_employee": 30, "esi_number": "1234567890"}
    assert "ESI-006" in rules_failed(run_engine(row))


def test_pt_cap_and_no_pt_state():
    row = {"employee_id": "E1", "basic": 30000, "pt": 2600, "state": "Maharashtra"}
    assert "PT-002" in rules_failed(run_engine(row))
    row2 = {"employee_id": "E1", "basic": 30000, "pt": 200, "state": "Delhi"}
    assert "PT-003" in rules_failed(run_engine(row2))
    row3 = {"employee_id": "E1", "basic": 30000, "pt": 200, "state": "Maharashtra"}
    got = rules_failed(run_engine(row3))
    assert "PT-002" not in got and "PT-003" not in got


# ── §9 bonus band ────────────────────────────────────────────────────────────

def test_bonus_band_boundaries():
    t = RuleThresholdsConfig()
    # eligible: basic 10,000 ≤ 21,000; base = min(10000, 7000) = 7000
    lo, hi = 7000 * 0.0833, 7000 * 0.20  # 583.1 – 1400
    row_ok = {"employee_id": "E1", "basic": 10000, "bonus": round(lo + 1, 2)}
    assert "BON-002" not in rules_failed(run_engine(row_ok, thresholds=t))
    row_hi = {"employee_id": "E1", "basic": 10000, "bonus": hi + 50}
    assert "BON-002" in rules_failed(run_engine(row_hi, thresholds=t))
    row_inelig = {"employee_id": "E1", "basic": 22000, "bonus": 1000}
    got = rules_failed(run_engine(row_inelig, pf_wage=Decimal("22000"), thresholds=t))
    assert "BON-001" in got and "BON-002" not in got


# ── §10 gratuity formula ─────────────────────────────────────────────────────

def test_gratuity_formula_and_service_gate():
    # 10 years, basic 26,000 → 26000 × 15/26 × 10 = 150,000
    row = {"employee_id": "E1", "basic": 26000, "gratuity": 150000,
           "doj": "2016-04-01", "dol": "2026-04-15"}
    assert "GRAT-003" not in rules_failed(run_engine(row, pf_wage=Decimal("26000")))
    row_dev = {**row, "gratuity": 190000}
    assert "GRAT-003" in rules_failed(run_engine(row_dev, pf_wage=Decimal("26000")))
    row_short = {"employee_id": "E1", "basic": 26000, "gratuity": 50000,
                 "doj": "2024-01-01", "dol": "2026-04-15"}
    assert "GRAT-002" in rules_failed(run_engine(row_short))


# ── §8 TDS ───────────────────────────────────────────────────────────────────

def test_no_pan_tds_must_be_20_pct():
    row = {"employee_id": "E1", "basic": 50000, "tds": 2000}  # taxable 50,000 → need 10,000
    assert "TDS-001" in rules_failed(run_engine(row, pf_wage=Decimal("15000")))
    row_ok = {"employee_id": "E1", "basic": 50000, "tds": 10000}
    assert "TDS-001" not in rules_failed(run_engine(row_ok, pf_wage=Decimal("15000")))


def test_tds_projection_deviation():
    row = {"employee_id": "E1", "basic": 150000, "pan": "ABCPE1234F", "tds": 2000}
    f = build_findings(
        employee_id="E1", employee_name="T", row=row,
        comp_by_key={"basic": _comp("basic")}, regular={"basic": Decimal("150000")},
        arrear_by_base={}, inc_arrear_total=Decimal("0"),
        paid_days=Decimal("30"), lop_days=Decimal("0"), days_in_month=30,
        pf_calc={"pf_employee": 1800, "pf_employer_total": 1800, "pf_wage_capped": 15000,
                 "_ceiling": 15000, "_emp_rate": 0.12},
        esic_calc={"esic_employee": 0, "esic_employer": 0, "esic_eligible": False,
                   "_ceiling": 21000, "_emp_rate": 0.0075, "_er_rate": 0.0325},
        pt_due=Decimal("0"), lwf_eamt=Decimal("0"), lwf_oamt=Decimal("0"),
        prior_components=None, prior_is_joiner=True, lop_diffs=[], inc_info={},
        tds_risk=[], thresholds=RuleThresholdsConfig(),
        period_month=date(2026, 4, 1), expected_monthly_tds=8125.0,
    )
    assert "TDS-002" in {x.rule_id for x in f if x.status == "FAIL"}


# ── data-quality extras ──────────────────────────────────────────────────────

def test_negative_deduction_zero_net_paid_days():
    row = {"employee_id": "E1", "basic": 10000, "pf_employee": -100}
    assert "DATA-005" in rules_failed(run_engine(row))
    row2 = {"employee_id": "E1", "basic": 10000, "net": 0, "paid_days": 30}
    assert "AGG-003" in rules_failed(run_engine(row2))
    row3 = {"employee_id": "E1", "basic": 10000, "net": -50}
    assert "AGG-004" in rules_failed(run_engine(row3))
    row4 = {"employee_id": "E1", "basic": 10000, "paid_days": 33}
    assert "LOP-003" in rules_failed(run_engine(row4))
