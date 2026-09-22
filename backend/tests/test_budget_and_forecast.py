"""
Budget, variance and forecast.

The property this suite exists to defend is the boundary between the three:
a budget is a decision, an actual is a measurement, a forecast is arithmetic on
assumptions. The failure mode that matters is not a wrong number — it is a
projection that reaches a board reading as a result, or a draft budget presented
as the approved one. Both are pinned here.
"""
from __future__ import annotations

import io
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import Entity, SalaryRegister, SalaryRegisterRow, User
from app.services import budgeting
from app.services.dimensions import UNASSIGNED

PASSWORD = "Passw0rd!x"


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@budget-example.com".replace("_", "-")
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": PASSWORD, "company_name": "Budget Tests"})
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
    base = dict.fromkeys(("business_unit", "department", "cost_center", "work_location", "work_state", "grade", "designation", "employment_type", "skill_category"), UNASSIGNED)
    base.update(kw)
    return base


def _register(entity, user, period: date, rows: list[dict]) -> None:
    db = SessionLocal()
    try:
        reg = SalaryRegister(user_id=user.id, entity_id=entity.id, period_month=period,
                             filename="t.csv", employee_count=len(rows))
        db.add(reg)
        db.flush()
        for r in rows:
            db.add(SalaryRegisterRow(
                register_id=reg.id, user_id=user.id, entity_id=entity.id,
                period_month=period, employee_id=r["employee_id"],
                components=r.get("components", {"basic": 10000.0}),
                arrears=r.get("arrears", {}), deductions={}, dimensions=r.get("dimensions") or _dims(),
                increment_arrear_total=Decimal(str(r.get("increment", 0))),
            ))
        db.commit()
    finally:
        db.close()


def _upload(client, headers, csv: str, name: str, scope_key="entity", measure="ctc"):
    return client.post(
        "/api/budget/versions",
        files={"file": (f"{name}.csv", io.BytesIO(csv.encode()), "text/csv")},
        data={"name": name, "scope_key": scope_key, "measure": measure},
        headers=headers,
    )


# ── reading a budget file ───────────────────────────────────────────────────

def test_a_budget_month_is_read_in_the_spellings_finance_uses():
    for text, expected in [
        ("2026-04-01", date(2026, 4, 1)),
        ("2026-04", date(2026, 4, 1)),
        ("Apr 2026", date(2026, 4, 1)),
        ("April 2026", date(2026, 4, 1)),
        ("04/2026", date(2026, 4, 1)),
    ]:
        assert budgeting.parse_period(text) == expected, text


def test_an_unreadable_month_is_not_guessed_at():
    assert budgeting.parse_period("sometime in spring") is None


def test_every_bad_row_is_reported_not_just_the_first():
    """A finance team fixing a 200-row file needs the whole list."""
    lines, problems = budgeting.parse_budget_rows([
        {"period": "2026-04", "scope": "Engineering", "amount": 100000},
        {"period": "nonsense", "scope": "Sales", "amount": 50000},
        {"period": "2026-05", "scope": "Sales"},
        {"period": "2026-06", "scope": "Sales", "amount": -100},
    ], "department")
    assert len(lines) == 1
    assert len(problems) == 3


def test_two_budgets_for_one_month_is_a_problem_not_a_sum():
    """Two numbers cannot both be the approved one."""
    lines, problems = budgeting.parse_budget_rows([
        {"period": "2026-04", "scope": "Engineering", "amount": 100000},
        {"period": "2026-04", "scope": "Engineering", "amount": 120000},
    ], "department")
    assert len(lines) == 1
    assert any("already has a line" in p for p in problems)


def test_unrecognised_columns_survive_the_round_trip(workspace):
    lines, _ = budgeting.parse_budget_rows(
        [{"period": "2026-04", "scope": "Eng", "amount": 100, "approved_by": "CFO"}],
        "department",
    )
    assert lines[0]["extra"]["approved_by"] == "CFO"


# ── approval ────────────────────────────────────────────────────────────────

BUDGET = ("period,scope,amount\n"
          "2026-04,entity,700000\n"
          "2026-05,entity,700000\n")


def test_an_uploaded_budget_starts_as_a_draft(client, workspace):
    _, _, headers = workspace
    r = _upload(client, headers, BUDGET, "FY27 plan")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["state"] == "draft"


def test_a_draft_budget_is_never_the_comparison(client, workspace):
    """A draft presented as the approved budget is how a board gets misled."""
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1"}])
    _upload(client, headers, BUDGET, "FY27 draft")

    data = client.get("/api/budget/variance", headers=headers).json()["data"]
    assert data["version"] is None
    assert "No approved budget" in data["note"]


def test_approving_makes_it_the_comparison(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1"}])
    version_id = _upload(client, headers, BUDGET, "FY27 plan").json()["data"]["id"]

    assert client.post(f"/api/budget/versions/{version_id}/approve",
                       headers=headers).status_code == 200
    data = client.get("/api/budget/variance", headers=headers).json()["data"]
    assert data["version"]["name"] == "FY27 plan"
    assert data["version"]["approved_by"] is not None


def test_approving_a_newer_budget_stands_the_older_one_down(client, workspace):
    _, _, headers = workspace
    first = _upload(client, headers, BUDGET, "FY27 original").json()["data"]["id"]
    second = _upload(client, headers, BUDGET, "FY27 revised").json()["data"]["id"]
    client.post(f"/api/budget/versions/{first}/approve", headers=headers)
    client.post(f"/api/budget/versions/{second}/approve", headers=headers)

    versions = client.get("/api/budget/versions", headers=headers).json()["data"]["versions"]
    current = [v for v in versions if v["is_current"]]
    assert [v["name"] for v in current] == ["FY27 revised"]
    # The superseded one is still approved and still there — the variance
    # someone argued about in April stays reconstructable.
    assert {v["name"]: v["state"] for v in versions}["FY27 original"] == "approved"


def test_an_approved_budget_cannot_be_deleted(client, workspace):
    _, _, headers = workspace
    version_id = _upload(client, headers, BUDGET, "FY27 plan").json()["data"]["id"]
    client.post(f"/api/budget/versions/{version_id}/approve", headers=headers)

    r = client.delete(f"/api/budget/versions/{version_id}", headers=headers)
    assert r.status_code == 409


def test_a_draft_can_be_deleted(client, workspace):
    _, _, headers = workspace
    version_id = _upload(client, headers, BUDGET, "FY27 draft").json()["data"]["id"]
    assert client.delete(f"/api/budget/versions/{version_id}", headers=headers).status_code == 200


def test_a_name_collision_is_refused_rather_than_overwriting(client, workspace):
    _, _, headers = workspace
    _upload(client, headers, BUDGET, "FY27 plan")
    assert _upload(client, headers, BUDGET, "FY27 plan").status_code == 409


# ── variance ────────────────────────────────────────────────────────────────

def test_variance_is_actual_less_budget(client, workspace):
    entity, user, headers = workspace
    # One employee on 10,000 basic. No components configured, so CTC is basic
    # plus the gratuity accrual.
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1"}])
    version_id = _upload(
        client, headers, "period,scope,amount\n2026-04,entity,10000\n", "Tight"
    ).json()["data"]["id"]
    client.post(f"/api/budget/versions/{version_id}/approve", headers=headers)

    data = client.get("/api/budget/variance", headers=headers).json()["data"]
    april = data["periods"][0]
    assert april["budget"] == 10000.0
    assert april["variance"] == round(april["actual"] - 10000.0, 2)
    assert april["variance_pct"] == round(april["variance"] / 10000.0 * 100, 2)


def test_percentage_variance_against_no_budget_is_undefined():
    """A department with no budget has not overspent by 100%."""
    result = budgeting.variance(Decimal("50000"), None)
    assert result["variance"] is None and result["variance_pct"] is None
    zero = budgeting.variance(Decimal("50000"), Decimal("0"))
    assert zero["variance"] == 50000.0
    assert zero["variance_pct"] is None


def test_a_budgeted_month_with_no_register_is_reported_as_unspent(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1"}])
    version_id = _upload(client, headers, BUDGET, "FY27 plan").json()["data"]["id"]
    client.post(f"/api/budget/versions/{version_id}/approve", headers=headers)

    data = client.get("/api/budget/variance", headers=headers).json()["data"]
    assert "May 2026" in data["unspent_periods"]
    assert len(data["periods"]) == 2       # both months, not the intersection


def test_a_month_with_a_register_and_no_budget_is_reported_as_unbudgeted(client, workspace):
    entity, user, headers = workspace
    for month in (4, 5, 6):
        _register(entity, user, date(2026, month, 1), [{"employee_id": "E1"}])
    version_id = _upload(
        client, headers, "period,scope,amount\n2026-04,entity,10000\n", "April only"
    ).json()["data"]["id"]
    client.post(f"/api/budget/versions/{version_id}/approve", headers=headers)

    data = client.get("/api/budget/variance", headers=headers).json()["data"]
    assert set(data["unbudgeted_periods"]) == {"May 2026", "Jun 2026"}


def test_a_departmental_budget_reports_by_department(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "dimensions": _dims(department="Engineering")},
        {"employee_id": "E2", "dimensions": _dims(department="Sales")},
    ])
    version_id = _upload(
        client, headers,
        "period,department,amount\n2026-04,Engineering,20000\n2026-04,Sales,5000\n",
        "By department", scope_key="department",
    ).json()["data"]["id"]
    client.post(f"/api/budget/versions/{version_id}/approve", headers=headers)

    data = client.get("/api/budget/variance", headers=headers).json()["data"]
    by_scope = {s["scope"]: s for s in data["scopes"]}
    assert by_scope["Engineering"]["budget"] == 20000.0
    assert by_scope["Sales"]["budget"] == 5000.0
    # Sales is over its budget; Engineering is under its own.
    assert by_scope["Sales"]["variance"] > 0
    assert by_scope["Engineering"]["variance"] < 0


def test_a_budget_set_on_gross_is_compared_against_gross(client, workspace):
    """Comparing a gross budget to CTC would show an overspend that is not one."""
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1"}])
    version_id = _upload(
        client, headers, "period,scope,amount\n2026-04,entity,10000\n",
        "Gross plan", measure="gross",
    ).json()["data"]["id"]
    client.post(f"/api/budget/versions/{version_id}/approve", headers=headers)

    data = client.get("/api/budget/variance", headers=headers).json()["data"]
    assert data["measure"] == "gross"
    assert data["periods"][0]["actual"] == 10000.0   # gross, not gross + gratuity
    assert data["periods"][0]["variance"] == 0.0


# ── forecast ────────────────────────────────────────────────────────────────

def test_a_forecast_is_labelled_as_one_everywhere_it_appears(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1"}])

    data = client.get("/api/budget/forecast?months=3", headers=headers).json()["data"]
    assert all(row["is_forecast"] for row in data["forecast"])
    assert "not a financial result" in data["disclaimer"]
    assert data["assumptions"] is not None
    # No key anywhere calls a projection an actual.
    assert "actual" not in {k for row in data["forecast"] for k in row}


def test_a_forecast_projects_from_the_last_actual_month(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1"}])

    data = client.get("/api/budget/forecast?months=2", headers=headers).json()["data"]
    assert data["base"]["label"] == "Apr 2026"
    assert [row["label"] for row in data["forecast"]] == ["May 2026", "Jun 2026"]


def test_arrears_are_not_projected_forward(client, workspace):
    """A one-off catch-up payment repeated twelve times is not a forecast."""
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "components": {"basic": 10000.0}, "arrears": {"basic": 50000.0}},
    ])

    data = client.get("/api/budget/forecast?months=1", headers=headers).json()["data"]
    assert data["base"]["actual"] < 20000        # the 50,000 arrear is excluded
    assert data["forecast"][0]["components"]["bonus"] == 0.0


def test_an_increment_shows_up_as_its_own_component(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1"}])

    data = client.get("/api/budget/forecast?months=2&increment_pct=10",
                      headers=headers).json()["data"]
    first = data["forecast"][0]
    assert first["components"]["increment"] == round(data["base"]["actual"] * 0.10, 2)
    assert first["forecast"] == round(data["base"]["actual"] * 1.10, 2)
    # And it carries into the following month rather than being applied twice.
    assert data["forecast"][1]["forecast"] == first["forecast"]


def test_hiring_and_exits_move_both_cost_and_headcount(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1"}, {"employee_id": "E2"},
    ])

    data = client.get(
        "/api/budget/forecast?months=2&new_hires_per_month=2&exits_per_month=1",
        headers=headers,
    ).json()["data"]
    assert data["forecast"][0]["headcount"] == 3
    assert data["forecast"][1]["headcount"] == 4
    assert data["forecast"][0]["components"]["joiners"] > 0
    assert data["forecast"][0]["components"]["exits"] < 0


def test_a_bonus_lands_only_in_its_own_month(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1"}])

    data = client.get(
        "/api/budget/forecast?months=3&bonus_month=2026-06&bonus_amount=100000",
        headers=headers,
    ).json()["data"]
    bonuses = {row["label"]: row["components"]["bonus"] for row in data["forecast"]}
    assert bonuses == {"May 2026": 0.0, "Jun 2026": 100000.0, "Jul 2026": 0.0}


def test_a_forecast_with_no_registers_says_so(client, workspace):
    _, _, headers = workspace
    data = client.get("/api/budget/forecast", headers=headers).json()["data"]
    assert data["forecast"] == []
    assert "nothing to project from" in data["note"]


# ── isolation ───────────────────────────────────────────────────────────────

def test_budgets_do_not_leak_between_entities(client, workspace):
    _, _, headers = workspace
    version_id = _upload(client, headers, BUDGET, "FY27 plan").json()["data"]["id"]
    client.post(f"/api/budget/versions/{version_id}/approve", headers=headers)
    other = client.post("/api/org/entities", json={"name": "Other"},
                        headers=headers).json()["data"]["id"]

    elsewhere = {**headers, "X-Entity-Id": other}
    assert client.get("/api/budget/versions", headers=elsewhere).json()["data"]["versions"] == []
    assert client.get("/api/budget/variance", headers=elsewhere).json()["data"]["version"] is None
    assert client.post(f"/api/budget/versions/{version_id}/approve",
                       headers=elsewhere).status_code == 404
