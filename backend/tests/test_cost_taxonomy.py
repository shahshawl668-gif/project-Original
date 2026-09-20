"""
The Indian payroll cost taxonomy.

Three properties decide whether this can be put in front of a finance team:

* **the layers add up** — gross is the earnings, CTC is gross plus the employer's
  own contributions, and nothing is counted twice;
* **deductions stay inside gross** — adding EPF employee share to CTC is the
  single most common way a payroll cost report overstates itself, so it is
  pinned here rather than left to code review;
* **the register's own figure wins** — where a payroll system stated what it
  deducted, that is what the cost report shows. A cost dashboard quietly
  substituting its own arithmetic puts two irreconcilable totals in front of
  the same reader.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import ComponentConfig, Entity, SalaryRegister, SalaryRegisterRow, User
from app.services import analytics
from app.services.cost_model import (
    DEDUCTION_KEYS,
    EARNING_KEYS,
    EMPLOYER_KEYS,
    GRATUITY_FRACTION,
    capture_reported,
    classify_component,
)
from app.services.dimensions import UNASSIGNED

PASSWORD = "Passw0rd!x"


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@ctc-example.com".replace("_", "-")
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": PASSWORD, "company_name": "CTC Tests"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    entity_id = client.post("/api/org/entities", json={"name": f"E-{request.node.name[:26]}"},
                            headers=headers).json()["data"]["id"]
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        entity = db.get(Entity, uuid.UUID(entity_id))
        db.expunge_all()
    finally:
        db.close()
    return entity, user, {**headers, "X-Entity-Id": entity_id}


def _dims(**kw) -> dict:
    base = {k: UNASSIGNED for k in
            ("business_unit", "department", "cost_center", "work_location",
             "work_state", "grade", "designation", "employment_type", "skill_category")}
    base.update(kw)
    return base


def _components(entity, user, names: dict[str, dict]) -> None:
    """Configure earning components, with their statutory applicability."""
    db = SessionLocal()
    try:
        for name, flags in names.items():
            db.add(ComponentConfig(user_id=user.id, entity_id=entity.id,
                                   component_name=name, **flags))
        db.commit()
    finally:
        db.close()


def _register(entity, user, period: date, rows: list[dict]) -> None:
    db = SessionLocal()
    try:
        reg = SalaryRegister(user_id=user.id, entity_id=entity.id, period_month=period,
                             filename="t.csv", employee_count=len(rows))
        db.add(reg); db.flush()
        for r in rows:
            db.add(SalaryRegisterRow(
                register_id=reg.id, user_id=user.id, entity_id=entity.id,
                period_month=period, employee_id=r["employee_id"],
                employee_name=r.get("name"), paid_days=Decimal("30"), lop_days=Decimal("0"),
                components=r.get("components", {}), arrears=r.get("arrears", {}),
                deductions=r.get("deductions", {}),
                pf_restricted=r.get("pf_restricted"),
                increment_arrear_total=Decimal(str(r.get("increment", 0))),
                dimensions=r.get("dimensions") or _dims(),
            ))
        db.commit()
    finally:
        db.close()


def _analyse(entity, **kw):
    db = SessionLocal()
    try:
        return analytics.cost_analysis(db, entity.id, **kw)
    finally:
        db.close()


def _compare(entity, **kw):
    db = SessionLocal()
    try:
        return analytics.cost_compare(db, entity.id, **kw)
    finally:
        db.close()


# ── classifying an earning ──────────────────────────────────────────────────

@pytest.mark.parametrize("name,bucket", [
    ("Basic", "basic_da"),
    ("basic_salary", "basic_da"),
    ("DA", "basic_da"),
    ("Dearness Allowance", "basic_da"),
    ("HRA", "hra"),
    ("House Rent Allowance", "hra"),
    ("Conveyance", "allowances"),
    ("Medical Allowance", "allowances"),
    ("Special Allowance", "allowances"),
    ("Performance Bonus", "variable_pay"),
    ("Overtime", "variable_pay"),
    ("Statutory Bonus", "variable_pay"),
    ("Sales Incentive", "variable_pay"),
    ("Ex Gratia", "variable_pay"),
])
def test_components_land_in_the_right_bucket(name, bucket):
    assert classify_component(name) == bucket


def test_an_unrecognised_earning_is_an_allowance_not_a_loss():
    """Dropping what we cannot name would stop the parts summing to gross."""
    assert classify_component("Site Uplift Payment") == "allowances"


# ── the layers ──────────────────────────────────────────────────────────────

def test_gross_is_the_earnings_and_ctc_is_gross_plus_employer_cost(workspace):
    entity, user, _ = workspace
    _components(entity, user, {
        "Basic": {"pf_applicable": True, "esic_applicable": True},
        "HRA": {"esic_applicable": True},
        "Special Allowance": {"esic_applicable": True},
    })
    _register(entity, user, date(2026, 4, 1), [{
        "employee_id": "E1",
        "components": {"basic": 20000.0, "hra": 8000.0, "special_allowance": 2000.0},
    }])

    totals = _analyse(entity, group_by="department")["totals"]

    assert totals["basic_da"] == 20000.0
    assert totals["hra"] == 8000.0
    assert totals["allowances"] == 2000.0
    assert totals["gross"] == 30000.0

    employer = sum(totals[k] for k in EMPLOYER_KEYS)
    assert round(totals["employer_cost"], 2) == round(employer, 2)
    assert round(totals["ctc"], 2) == round(totals["gross"] + employer, 2)


def test_deductions_are_inside_gross_and_never_added_to_ctc(workspace):
    """The commonest way a cost report overstates itself. Pinned, not reviewed."""
    entity, user, _ = workspace
    _components(entity, user, {"Basic": {"pf_applicable": True}})
    _register(entity, user, date(2026, 4, 1), [{
        "employee_id": "E1",
        "components": {"basic": 20000.0},
        "deductions": {"ee_pf": 1800.0, "pt": 200.0, "tds": 3000.0},
    }])

    totals = _analyse(entity, group_by="department")["totals"]

    assert totals["deductions"] == 5000.0
    assert totals["net"] == totals["gross"] - 5000.0
    # CTC is earnings plus employer cost. Nothing on the deduction layer is in it.
    assert round(totals["ctc"] - totals["gross"] - totals["employer_cost"], 2) == 0.0


def test_gratuity_accrues_on_basic_and_da(workspace):
    entity, user, _ = workspace
    _components(entity, user, {"Basic": {}, "HRA": {}})
    _register(entity, user, date(2026, 4, 1), [{
        "employee_id": "E1", "components": {"basic": 26000.0, "hra": 10000.0},
    }])

    totals = _analyse(entity, group_by="department")["totals"]
    # 15 days on a 26-day month, spread over twelve — about 4.81%, and on Basic
    # alone: HRA never enters the gratuity base.
    assert totals["gratuity"] == float(round(Decimal("26000") * GRATUITY_FRACTION, 2))


def test_the_employer_pays_twelve_percent_on_pf_wages(workspace):
    entity, user, _ = workspace
    _components(entity, user, {"Basic": {"pf_applicable": True}, "HRA": {}})
    _register(entity, user, date(2026, 4, 1), [{
        "employee_id": "E1", "components": {"basic": 10000.0, "hra": 5000.0},
    }])

    totals = _analyse(entity, group_by="department")["totals"]
    assert totals["er_pf"] == 1200.0     # HRA is not PF wage
    assert totals["ee_pf"] == 1200.0


def test_an_unrestricted_employee_contributes_on_full_wage(workspace):
    """Two people, same payroll, different bases — the difference is not rounding."""
    entity, user, _ = workspace
    _components(entity, user, {"Basic": {"pf_applicable": True}})
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "CAPPED", "components": {"basic": 50000.0}, "pf_restricted": True,
         "dimensions": _dims(department="A")},
        {"employee_id": "FULL", "components": {"basic": 50000.0}, "pf_restricted": False,
         "dimensions": _dims(department="B")},
    ])

    by_group = {g["group"]: g["measures"] for g in
                _analyse(entity, group_by="department")["matrix"]}
    assert by_group["A"]["er_pf"] == 1800.0        # 12% of the 15,000 ceiling
    assert by_group["B"]["er_pf"] == 6000.0        # 12% of full basic


# ── what the register said wins ─────────────────────────────────────────────

def test_the_registers_own_figure_is_used_over_the_computed_one(workspace):
    entity, user, _ = workspace
    _components(entity, user, {"Basic": {"pf_applicable": True}})
    _register(entity, user, date(2026, 4, 1), [{
        "employee_id": "E1", "components": {"basic": 10000.0},
        # The payroll system deducted 1,000, not the 1,200 the engine computes.
        # That disagreement is a finding; the cost report shows what was paid.
        "deductions": {"ee_pf": 1000.0},
    }])

    result = _analyse(entity, group_by="department")
    assert result["totals"]["ee_pf"] == 1000.0
    assert result["sources"]["reported"] == 1000.0
    assert result["sources"]["computed"] > 0        # everything else was derived


def test_a_gap_in_the_register_is_filled_by_the_engine(workspace):
    entity, user, _ = workspace
    _components(entity, user, {"Basic": {"pf_applicable": True}})
    _register(entity, user, date(2026, 4, 1), [{
        "employee_id": "E1", "components": {"basic": 10000.0}, "deductions": {},
    }])

    result = _analyse(entity, group_by="department")
    assert result["totals"]["er_pf"] == 1200.0
    assert result["sources"]["reported"] == 0.0


def test_capture_reads_the_statutory_columns_a_register_carries():
    reported = capture_reported({
        "Employee ID": "E1", "Basic": 20000,
        "PF Employee": 1800, "PF Employer": 1800,
        "ESIC Employee": 150, "PT": 200, "TDS": 4500,
    })
    assert reported == {"ee_pf": 1800.0, "er_pf": 1800.0,
                        "ee_esi": 150.0, "pt": 200.0, "tds": 4500.0}


def test_an_absent_column_is_not_a_zero():
    """A register that never mentioned ESI is not one that deducted nothing."""
    assert "ee_esi" not in capture_reported({"Employee ID": "E1", "Basic": 20000})
    assert capture_reported({"ESIC Employee": 0})["ee_esi"] == 0.0


def test_tds_is_reported_or_absent_never_invented(workspace):
    """Projecting a month's tax needs the whole year. A cost query must not guess."""
    entity, user, _ = workspace
    _components(entity, user, {"Basic": {}})
    _register(entity, user, date(2026, 4, 1), [{
        "employee_id": "E1", "components": {"basic": 200000.0},
    }])
    assert _analyse(entity, group_by="department")["totals"]["tds"] == 0.0


# ── every measure is reachable ──────────────────────────────────────────────

def test_any_measure_can_drive_the_breakdown(workspace):
    entity, user, _ = workspace
    _components(entity, user, {"Basic": {"pf_applicable": True}})
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "components": {"basic": 30000.0},
         "dimensions": _dims(department="Engineering")},
        {"employee_id": "E2", "components": {"basic": 10000.0},
         "dimensions": _dims(department="Sales")},
    ])

    for measure in EARNING_KEYS + EMPLOYER_KEYS + DEDUCTION_KEYS + ("gross", "ctc", "net"):
        result = _analyse(entity, group_by="department", measure=measure)
        assert result["measure"] == measure
        assert sum(g["total"] for g in result["matrix"]) == pytest.approx(
            result["totals"][measure], abs=0.02
        )


def test_an_unknown_measure_is_rejected(workspace):
    entity, _, _ = workspace
    with pytest.raises(ValueError):
        _analyse(entity, group_by="department", measure="vibes")


def test_period_totals_carry_the_whole_taxonomy(workspace):
    """Headcount and variance analysis are read off these, not re-queried."""
    entity, user, _ = workspace
    _components(entity, user, {"Basic": {}})
    for month, headcount in ((4, 1), (5, 2)):
        _register(entity, user, date(2026, month, 1), [
            {"employee_id": f"E{i}", "components": {"basic": 10000.0}}
            for i in range(headcount)
        ])

    points = _analyse(entity, group_by="department")["period_totals"]
    assert [p["label"] for p in points] == ["Apr 2026", "May 2026"]
    assert [p["headcount"] for p in points] == [1, 2]
    assert points[1]["measures"]["gross"] == 20000.0


# ── comparison ──────────────────────────────────────────────────────────────

def test_two_months_compare_measure_by_measure(workspace):
    entity, user, _ = workspace
    _components(entity, user, {"Basic": {"pf_applicable": True}})
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "components": {"basic": 10000.0}}])
    _register(entity, user, date(2026, 5, 1), [
        {"employee_id": "E1", "components": {"basic": 12000.0}}])

    result = _compare(entity, period_a=date(2026, 4, 1), period_b=date(2026, 5, 1))

    by_key = {m["key"]: m for m in result["by_measure"]}
    assert by_key["basic_da"]["a"] == 10000.0
    assert by_key["basic_da"]["b"] == 12000.0
    assert by_key["basic_da"]["delta"] == 2000.0
    assert by_key["basic_da"]["delta_pct"] == 20.0
    assert by_key["er_pf"]["delta"] == 240.0


def test_the_same_month_a_year_apart_is_the_same_operation(workspace):
    """Within a year or across years — one comparison, the caller names the pair."""
    entity, user, _ = workspace
    _components(entity, user, {"Basic": {}})
    _register(entity, user, date(2025, 6, 1), [
        {"employee_id": "E1", "components": {"basic": 10000.0}}])
    _register(entity, user, date(2026, 6, 1), [
        {"employee_id": "E1", "components": {"basic": 11000.0}}])

    result = _compare(entity, period_a=date(2025, 6, 1), period_b=date(2026, 6, 1))
    assert result["a"]["label"] == "Jun 2025"
    assert result["b"]["label"] == "Jun 2026"
    derived = {m["key"]: m for m in result["by_derived"]}
    assert derived["gross"]["delta"] == 1000.0
    assert derived["gross"]["delta_pct"] == 10.0


def test_a_group_present_in_only_one_month_is_still_reported(workspace):
    """A department that closed is exactly what a comparison is for."""
    entity, user, _ = workspace
    _components(entity, user, {"Basic": {}})
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "components": {"basic": 10000.0},
         "dimensions": _dims(department="Closed")},
        {"employee_id": "E2", "components": {"basic": 10000.0},
         "dimensions": _dims(department="Kept")},
    ])
    _register(entity, user, date(2026, 5, 1), [
        {"employee_id": "E2", "components": {"basic": 10000.0},
         "dimensions": _dims(department="Kept")},
        {"employee_id": "E3", "components": {"basic": 5000.0},
         "dimensions": _dims(department="New")},
    ])

    result = _compare(entity, period_a=date(2026, 4, 1), period_b=date(2026, 5, 1),
                      measure="gross")
    by_group = {g["group"]: g for g in result["by_group"]}
    assert set(by_group) == {"Closed", "Kept", "New"}
    assert by_group["Closed"]["delta"] == -10000.0
    assert by_group["New"]["a"] == 0.0
    # No percentage against a zero base: a new department has not grown by infinity.
    assert by_group["New"]["delta_pct"] is None
    assert result["headcount"] == {"a": 2, "b": 2, "delta": 0}


def test_comparing_against_a_month_with_no_register_says_so(workspace):
    entity, user, _ = workspace
    _components(entity, user, {"Basic": {}})
    _register(entity, user, date(2026, 5, 1), [
        {"employee_id": "E1", "components": {"basic": 10000.0}}])

    result = _compare(entity, period_a=date(2026, 4, 1), period_b=date(2026, 5, 1))
    assert result["a"]["present"] is False
    assert result["b"]["present"] is True
    assert result["a"]["measures"]["gross"] == 0.0


def test_a_filter_applies_to_both_sides_of_a_comparison(workspace):
    entity, user, _ = workspace
    _components(entity, user, {"Basic": {}})
    for month in (4, 5):
        _register(entity, user, date(2026, month, 1), [
            {"employee_id": "E1", "components": {"basic": 10000.0},
             "dimensions": _dims(work_location="Bangalore")},
            {"employee_id": "E2", "components": {"basic": 90000.0},
             "dimensions": _dims(work_location="Chennai")},
        ])

    result = _compare(entity, period_a=date(2026, 4, 1), period_b=date(2026, 5, 1),
                      filters={"work_location": ["Bangalore"]})
    assert result["a"]["measures"]["gross"] == 10000.0
    assert result["b"]["measures"]["gross"] == 10000.0


# ── through the API ─────────────────────────────────────────────────────────

def test_the_comparison_endpoint_serves_two_periods(client, workspace):
    entity, user, headers = workspace
    _components(entity, user, {"Basic": {}})
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "components": {"basic": 10000.0}}])
    _register(entity, user, date(2026, 5, 1), [
        {"employee_id": "E1", "components": {"basic": 15000.0}}])

    r = client.get("/api/bi/cost-compare?period_a=2026-04-01&period_b=2026-05-01",
                   headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["a"]["measures"]["gross"] == 10000.0
    assert data["b"]["measures"]["gross"] == 15000.0


def test_the_measure_catalogue_is_served(client, workspace):
    _, _, headers = workspace
    data = client.get("/api/bi/measures", headers=headers).json()["data"]
    keys = {m["key"] for m in data["measures"]}
    assert {"basic_da", "hra", "er_pf", "gratuity", "pt", "tds"} <= keys
    assert {m["key"] for m in data["derived"]} >= {"gross", "employer_cost", "ctc", "net"}


def test_periods_lists_only_months_that_hold_a_register(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "components": {"basic": 10000.0}}])

    data = client.get("/api/bi/periods", headers=headers).json()["data"]
    assert [p["label"] for p in data["periods"]] == ["Apr 2026"]


def test_a_comparison_does_not_leak_between_entities(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "components": {"basic": 10000.0}}])
    other = client.post("/api/org/entities", json={"name": "Other"},
                        headers=headers).json()["data"]["id"]

    data = client.get("/api/bi/cost-compare?period_a=2026-04-01&period_b=2026-05-01",
                      headers={**headers, "X-Entity-Id": other}).json()["data"]
    assert data["a"]["measures"]["gross"] == 0.0
