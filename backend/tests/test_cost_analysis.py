"""
Payroll cost by dimension.

The property that matters most is that a breakdown always sums to the total.
A chart whose parts do not reconcile to the payroll everyone already agrees on
is worse than no chart — it gets argued with instead of acted on.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import Entity, SalaryRegister, SalaryRegisterRow, User
from app.services import analytics
from app.services.dimensions import UNASSIGNED, snapshot

PASSWORD = "Passw0rd!x"


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@cost-example.com".replace("_", "-")
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": PASSWORD, "company_name": "Cost Tests"})
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
                components={"basic": r["basic"]}, arrears=r.get("arrears", {}),
                increment_arrear_total=Decimal(str(r.get("increment", 0))),
                dimensions=r["dimensions"],
            ))
        db.commit()
    finally:
        db.close()


def _dims(**kw) -> dict:
    base = {k: UNASSIGNED for k in
            ("business_unit", "department", "cost_center", "work_location",
             "work_state", "grade", "designation", "employment_type", "skill_category")}
    base.update(kw)
    return base


def _analyse(entity, **kw):
    db = SessionLocal()
    try:
        return analytics.cost_analysis(db, entity.id, **kw)
    finally:
        db.close()


# ── the snapshot ────────────────────────────────────────────────────────────

def test_the_master_is_authoritative():
    class Rec:
        business_unit, department, work_location = "Manufacturing", "Assembly", "Pune"
        cost_center = grade = designation = None
        work_state = "Maharashtra"
        employment_type = skill_category = None

    dims = snapshot(Rec(), {"Department": "Ignored"})
    assert dims["department"] == "Assembly"
    assert dims["business_unit"] == "Manufacturing"


def test_the_register_fills_a_gap_the_master_leaves():
    """A client with no master still gets a breakdown from their register."""
    dims = snapshot(None, {"Department": "Finance", "Location": "Chennai", "Grade": "M3"})
    assert dims["department"] == "Finance"
    assert dims["work_location"] == "Chennai"
    assert dims["grade"] == "M3"


def test_every_dimension_is_always_present():
    """A breakdown whose parts do not sum to the whole is worse than an unknown bucket."""
    dims = snapshot(None, {})
    assert set(dims) == {"business_unit", "department", "cost_center", "work_location",
                         "work_state", "grade", "designation", "employment_type", "skill_category"}
    assert all(v == UNASSIGNED for v in dims.values())


# ── grouping and reconciliation ─────────────────────────────────────────────

APRIL = [
    {"employee_id": "E1", "basic": 50000.0, "dimensions": _dims(department="Engineering", work_location="Bangalore", grade="M3", business_unit="Technology")},
    {"employee_id": "E2", "basic": 30000.0, "dimensions": _dims(department="Engineering", work_location="Pune", grade="M2", business_unit="Technology")},
    {"employee_id": "E3", "basic": 20000.0, "dimensions": _dims(department="Sales", work_location="Bangalore", grade="M2", business_unit="Commercial")},
]


def test_a_breakdown_sums_to_the_total(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 4, 1), APRIL)

    result = _analyse(entity, group_by="department")
    assert result["totals"]["total"] == 100000.0
    assert sum(g["total"] for g in result["matrix"]) == result["totals"]["total"]


def test_groups_are_ranked_by_cost(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 4, 1), APRIL)

    result = _analyse(entity, group_by="department")
    assert [g["group"] for g in result["matrix"]] == ["Engineering", "Sales"]
    assert result["matrix"][0]["total"] == 80000.0
    assert result["matrix"][0]["share_pct"] == 80.0


def test_the_same_data_regroups_by_any_dimension(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 4, 1), APRIL)

    for dimension, expected in [
        ("work_location", {"Bangalore": 70000.0, "Pune": 30000.0}),
        ("grade", {"M3": 50000.0, "M2": 50000.0}),
        ("business_unit", {"Technology": 80000.0, "Commercial": 20000.0}),
    ]:
        result = _analyse(entity, group_by=dimension)
        assert {g["group"]: g["total"] for g in result["matrix"]} == expected
        assert sum(g["total"] for g in result["matrix"]) == 100000.0


def test_an_unknown_dimension_is_rejected(workspace):
    entity, _, _ = workspace
    with pytest.raises(ValueError):
        _analyse(entity, group_by="favourite_colour")


# ── time ────────────────────────────────────────────────────────────────────

def test_months_are_reported_in_order(workspace):
    entity, user, _ = workspace
    for month in (6, 4, 5):   # inserted out of order on purpose
        _register(entity, user, date(2026, month, 1),
                  [{"employee_id": "E1", "basic": 10000.0 * month,
                    "dimensions": _dims(department="Engineering")}])

    result = _analyse(entity, group_by="department")
    assert [p["label"] for p in result["periods"]] == ["Apr 2026", "May 2026", "Jun 2026"]


def test_quarters_follow_the_indian_financial_year(workspace):
    """April is Q1. A payroll report calling January Q1 reconciles with nothing."""
    entity, user, _ = workspace
    for month in (4, 7, 1):
        _register(entity, user, date(2026 if month != 1 else 2027, month, 1),
                  [{"employee_id": "E1", "basic": 10000.0, "dimensions": _dims(department="Eng")}])

    result = _analyse(entity, group_by="department", granularity="quarter")
    labels = [p["label"] for p in result["periods"]]
    assert labels == ["FY27 Q1", "FY27 Q2", "FY27 Q4"]


def test_years_roll_up(workspace):
    entity, user, _ = workspace
    for month in (4, 5, 6):
        _register(entity, user, date(2026, month, 1),
                  [{"employee_id": "E1", "basic": 10000.0, "dimensions": _dims(department="Eng")}])

    result = _analyse(entity, group_by="department", granularity="year")
    assert len(result["periods"]) == 1
    assert result["matrix"][0]["total"] == 30000.0


def test_a_date_range_narrows_the_result(workspace):
    entity, user, _ = workspace
    for month in (4, 5, 6):
        _register(entity, user, date(2026, month, 1),
                  [{"employee_id": "E1", "basic": 10000.0, "dimensions": _dims(department="Eng")}])

    result = _analyse(entity, group_by="department",
                      date_from=date(2026, 5, 1), date_to=date(2026, 6, 1))
    assert len(result["periods"]) == 2
    assert result["totals"]["total"] == 20000.0


# ── filters ─────────────────────────────────────────────────────────────────

def test_a_filter_narrows_to_matching_rows(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 4, 1), APRIL)

    result = _analyse(entity, group_by="department", filters={"work_location": ["Bangalore"]})
    assert result["totals"]["total"] == 70000.0
    assert {g["group"] for g in result["matrix"]} == {"Engineering", "Sales"}


def test_filters_combine_across_dimensions(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 4, 1), APRIL)

    result = _analyse(entity, group_by="department",
                      filters={"work_location": ["Bangalore"], "business_unit": ["Technology"]})
    assert result["totals"]["total"] == 50000.0   # E1 only


def test_a_filter_accepts_several_values(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 4, 1), APRIL)

    result = _analyse(entity, group_by="grade", filters={"work_location": ["Bangalore", "Pune"]})
    assert result["totals"]["total"] == 100000.0


# ── measures ────────────────────────────────────────────────────────────────

def test_arrears_are_reported_apart_from_regular_pay(workspace):
    """A month inflated by back-pay must not read as a permanent cost rise."""
    entity, user, _ = workspace
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "basic": 40000.0, "arrears": {"basic": 12000.0},
         "increment": 3000.0, "dimensions": _dims(department="Eng")},
    ])

    result = _analyse(entity, group_by="department")
    assert result["totals"]["regular"] == 40000.0
    assert result["totals"]["arrears"] == 15000.0
    assert result["totals"]["total"] == 55000.0


def test_headcount_counts_people_not_rows(workspace):
    entity, user, _ = workspace
    for month in (4, 5):
        _register(entity, user, date(2026, month, 1), APRIL)

    result = _analyse(entity, group_by="department")
    assert result["totals"]["headcount"] == 3          # not 6
    assert result["totals"]["cost_per_head"] == round(200000 / 3, 2)


def test_an_entity_with_no_registers_returns_an_empty_shape(workspace):
    entity, _, _ = workspace
    result = _analyse(entity, group_by="department")
    assert result["matrix"] == []
    assert result["totals"]["total"] == 0.0


# ── through the API ─────────────────────────────────────────────────────────

def test_the_endpoint_serves_a_filtered_breakdown(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), APRIL)

    r = client.get("/api/bi/cost-analysis?group_by=grade&granularity=month"
                   "&work_location=Bangalore", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["group_by_label"] == "Grade"
    assert data["totals"]["total"] == 70000.0


def test_an_invalid_dimension_is_a_400(client, workspace):
    _, _, headers = workspace
    assert client.get("/api/bi/cost-analysis?group_by=nope", headers=headers).status_code == 400


def test_dimension_values_offer_only_what_exists(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), APRIL)

    data = client.get("/api/bi/dimensions", headers=headers).json()["data"]
    by_key = {d["key"]: d for d in data["dimensions"]}
    assert by_key["department"]["values"] == ["Engineering", "Sales"]
    assert by_key["work_location"]["label"] == "Location"
    # Unassigned sorts last — it is a gap in the data, not a unit.
    assert by_key["cost_center"]["values"] == [UNASSIGNED]


def test_cost_analysis_does_not_leak_between_entities(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), APRIL)
    other = client.post("/api/org/entities", json={"name": "Other"}, headers=headers).json()["data"]["id"]

    data = client.get("/api/bi/cost-analysis?group_by=department",
                      headers={**headers, "X-Entity-Id": other}).json()["data"]
    assert data["totals"]["total"] == 0.0
