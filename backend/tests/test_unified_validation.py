"""
One register, one pass.

A real register carries people paid normally, people receiving arrears, and
people whose increment is being settled — often the same person carrying two of
the three. What a row contains is read from the row rather than declared for the
whole file, so nobody has to split a register or accept the wrong checks on most
of it.
"""
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from app.services.row_composition import describe, months_between

PASSWORD = "Passw0rd!x"


# ── classifying a row ───────────────────────────────────────────────────────

def _describe(row, regular=None, arrear=None, increment=Decimal("0"), **kw):
    return describe(
        row,
        regular if regular is not None else {"basic": Decimal("20000")},
        arrear or {},
        increment,
        **kw,
    )


def test_a_plain_row_is_regular_only():
    c = _describe({"Basic": 20000})
    assert c.kinds == ["regular"]
    assert not c.any_arrear
    assert c.arrear_months is None   # no window implied where there are no arrears


def test_a_row_can_be_regular_and_arrear_at_once():
    c = _describe({"Basic": 20000, "Arrear From": "01/04/2026"},
                  arrear={"basic": Decimal("6000")}, period_month=date(2026, 8, 1))
    assert c.kinds == ["regular", "arrear"]
    assert c.is_mixed


def test_all_three_kinds_in_one_row():
    c = _describe({"Basic": 20000, "Arrear Months": 3},
                  arrear={"basic": Decimal("6000")}, increment=Decimal("4500"))
    assert c.kinds == ["regular", "arrear", "increment arrear"]
    assert c.label == "regular + arrear + increment arrear"


def test_the_window_comes_from_the_row_first():
    c = _describe(
        {"Arrear From": "01/05/2026", "Arrear To": "31/07/2026"},
        arrear={"basic": Decimal("9000")},
        ctc_effective_from=date(2026, 1, 1),
        run_effective_from=date(2025, 4, 1),
    )
    assert c.window_source == "row"
    assert c.arrear_months == 3          # May, June, July


def test_the_ctc_revision_is_the_next_source():
    c = _describe(
        {"Basic": 20000},
        arrear={"basic": Decimal("9000")},
        ctc_effective_from=date(2026, 6, 1),
        period_month=date(2026, 8, 1),
        run_effective_from=date(2025, 4, 1),
    )
    assert c.window_source == "ctc"
    assert c.arrear_months == 3          # June, July, August


def test_run_parameters_are_the_last_resort():
    c = _describe(
        {"Basic": 20000},
        arrear={"basic": Decimal("9000")},
        period_month=date(2026, 8, 1),
        run_effective_from=date(2026, 7, 1),
    )
    assert c.window_source == "run parameters"
    assert c.arrear_months == 2


def test_two_employees_can_settle_different_periods():
    """The point of per-row windows: one file, two different arrear spans."""
    a = _describe({"Arrear From": "01/07/2026"}, arrear={"basic": Decimal("5000")},
                  period_month=date(2026, 8, 1))
    b = _describe({"Arrear From": "01/02/2026"}, arrear={"basic": Decimal("5000")},
                  period_month=date(2026, 8, 1))
    assert a.arrear_months == 2
    assert b.arrear_months == 7


def test_an_unstated_window_is_not_guessed():
    """Every arrear expectation multiplies by a month count; inventing one lies."""
    c = _describe({"Basic": 20000}, arrear={"basic": Decimal("9000")})
    assert c.arrear_months is None
    assert c.window_source == "unknown"


def test_a_stated_month_count_is_used_directly():
    c = _describe({"Arrear Months": 4}, arrear={"basic": Decimal("8000")})
    assert c.arrear_months == 4
    assert c.window_source == "row"


@pytest.mark.parametrize("start,end,expected", [
    (date(2026, 8, 1), date(2026, 8, 1), 1),
    (date(2026, 4, 1), date(2026, 8, 1), 5),
    (date(2025, 12, 1), date(2026, 2, 1), 3),
])
def test_month_counting_is_inclusive(start, end, expected):
    assert months_between(start, end) == expected


# ── the rules that follow from it ───────────────────────────────────────────

def _findings(composition, pf_calc=None):
    from app.services.rule_engine_v2 import build_findings

    return build_findings(
        employee_id="E1", employee_name="Test", row={}, comp_by_key={},
        regular={"basic": Decimal("20000")}, arrear_by_base={}, inc_arrear_total=Decimal("0"),
        paid_days=Decimal("30"), lop_days=Decimal("0"), days_in_month=30,
        pf_calc=pf_calc or {"pf_employee": 0, "pf_employer_total": 0, "_ceiling": 15000,
                            "_pf_wage_full": 20000, "_restrict": True},
        esic_calc={"esic_eligible": False, "esic_employee": 0, "esic_employer": 0},
        pt_due=Decimal("0"), lwf_eamt=Decimal("0"), lwf_oamt=Decimal("0"),
        prior_components=None, prior_is_joiner=False, lop_diffs=[], inc_info={}, tds_risk=[],
        composition=composition,
    )


def _ids(findings):
    return {f.rule_id for f in findings}


def test_arrears_with_no_stated_period_are_reported():
    c = _describe({"Basic": 20000}, arrear={"basic": Decimal("9000")})
    assert "ARR-001" in _ids(_findings(c))


def test_a_stated_period_raises_no_arr001():
    c = _describe({"Arrear Months": 3}, arrear={"basic": Decimal("9000")})
    assert "ARR-001" not in _ids(_findings(c))


def test_an_unusually_long_arrear_is_flagged():
    c = _describe({"Arrear Months": 18}, arrear={"basic": Decimal("50000")})
    assert "ARR-003" in _ids(_findings(c))


def test_arrear_pf_is_not_due_when_the_wage_already_caps():
    """A frequent and expensive over-deduction."""
    c = _describe({"Arrear Months": 3}, arrear={"basic": Decimal("9000")})
    findings = _findings(c, pf_calc={
        "pf_employee": 1800, "pf_employer_total": 1800,
        "_ceiling": 15000, "_pf_wage_full": 40000, "_restrict": True,
    })
    assert "ARR-004" in _ids(findings)


def test_no_arrear_rules_fire_on_a_plain_row():
    c = _describe({"Basic": 20000})
    assert not ({"ARR-001", "ARR-002", "ARR-003", "ARR-004"} & _ids(_findings(c)))


# ── every rule must be classified ───────────────────────────────────────────

def test_every_emitted_rule_has_a_category():
    """
    An unclassified rule would be filed under the fallback and land in the wrong
    part of the report, which sends the reader to the wrong action.
    """
    import pathlib
    import re

    from app.services.finding_taxonomy import is_classified

    pattern = re.compile(r'"([A-Z]{2,6}-\d{3})"')
    found = set()
    for path in pathlib.Path("app/services").rglob("*.py"):
        found.update(pattern.findall(path.read_text()))

    unclassified = sorted(r for r in found if not is_classified(r))
    assert not unclassified, f"rules with no taxonomy entry: {unclassified}"


def test_categories_map_to_the_three_actions():
    from app.services.finding_taxonomy import ISSUE, MISMATCH, MISSING, categorise

    assert categorise("COMP-002") == MISSING          # a column was not supplied
    assert categorise("ARR-001") == MISSING           # the arrear period was not stated
    assert categorise("STAT-001") == MISMATCH         # PF disagrees with the computation
    assert categorise("ATT-001") == MISMATCH          # paid days disagree with attendance
    assert categorise("MST-003") == ISSUE             # paid after exit — a decision
    assert categorise("STRUCT-001") == ISSUE          # structural risk


def test_a_missing_column_is_missing_not_a_mismatch():
    """Several rules report an absent column through the actual value."""
    from app.services.finding_taxonomy import MISSING, categorise

    assert categorise("STAT-001", "(missing)") == MISSING
    assert categorise("STAT-001", "1800.00") == "mismatch"


# ── end to end ──────────────────────────────────────────────────────────────

MIXED_REGISTER = [
    # Regular only.
    {"Employee ID": "E001", "Employee Name": "Asha", "Paid Days": 30, "LOP Days": 0,
     "Basic": 20000, "HRA": 8000, "Gross": 28000, "PF Employee": 2400},
    # Regular plus arrears, with its own window.
    {"Employee ID": "E002", "Employee Name": "Rahul", "Paid Days": 30, "LOP Days": 0,
     "Basic": 18000, "HRA": 7200, "Basic Arrear": 6000, "Arrear From": "01/06/2026",
     "Gross": 31200, "PF Employee": 2160},
    # Regular plus an increment arrear, different window.
    {"Employee ID": "E003", "Employee Name": "Neha", "Paid Days": 30, "LOP Days": 0,
     "Basic": 25000, "HRA": 10000, "Increment Arrear": 9000, "Arrear Months": 3,
     "Gross": 44000, "PF Employee": 1800},
]


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@unified-example.com".replace("_", "-")
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": PASSWORD, "company_name": "Unified Tests"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    entity_id = client.post("/api/org/entities",
                            json={"name": f"E-{request.node.name[:26]}"},
                            headers=headers).json()["data"]["id"]
    headers["X-Entity-Id"] = entity_id
    for name in ("Basic", "HRA"):
        client.post("/api/components",
                    json={"component_name": name, "pf_applicable": name == "Basic",
                          "esic_applicable": True, "pt_applicable": True, "taxable": True},
                    headers=headers)
    return headers


def _validate(client, headers, rows=MIXED_REGISTER):
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    up = client.post(
        "/api/payroll/upload",
        files={"file": ("mixed.csv", buf.getvalue().encode(), "text/csv")},
        data={"meta": '{"run_type":"regular","period_month":"2026-08-01","strict_header_check":false}'},
        headers=headers,
    ).json()["data"]
    return client.post(
        "/api/payroll/validate",
        json={"employees": up["employees"], "run_type": "regular",
              "period_month": "2026-08-01", "as_of_date": "2026-08-31"},
        headers=headers,
    )


def test_a_mixed_register_validates_in_one_pass(client, workspace):
    """No mode to choose, no file to split, no error about effective months."""
    r = _validate(client, workspace)
    assert r.status_code == 200, r.text
    results = r.json()["data"]["results"]
    assert len(results) == 3

    kinds = {row["employee_id"]: row["row_kinds"] for row in results}
    assert kinds["E001"] == ["regular"]
    assert "arrear" in kinds["E002"]
    assert "increment arrear" in kinds["E003"]


def test_each_employee_keeps_their_own_arrear_window(client, workspace):
    results = _validate(client, workspace).json()["data"]["results"]
    windows = {row["employee_id"]: row["arrear_window"] for row in results}

    assert windows["E002"]["source"] == "row"
    assert windows["E002"]["months"] == 3        # June → August
    assert windows["E003"]["months"] == 3        # stated directly
    assert windows["E001"]["months"] is None     # no arrears, no window


def test_the_report_groups_by_what_to_do_about_it(client, workspace):
    summary = _validate(client, workspace).json()["data"]["findings_summary"]
    categories = {c["key"]: c for c in summary["by_category"]}

    assert set(categories) == {"missing", "mismatch", "issue"}
    for bucket in categories.values():
        assert "meaning" in bucket and bucket["meaning"]
        for rule in bucket["rules"]:
            # Every rule in the report carries its remediation.
            assert rule["solution"], f"{rule['rule_id']} has no stated solution"

    assert sum(c["count"] for c in summary["by_category"]) > 0
