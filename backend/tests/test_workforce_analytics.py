"""
Headcount movement, pay distribution, and who is allowed to see a name.

Three things worth pinning:

* movement is measured by **presence on the register**, because that is a
  verified statement. A joining date on a master that has not been re-uploaded
  since March would otherwise silently rewrite every month after it;
* the **median** is reported, not only the mean. One large package moves an
  average and nothing else does;
* an identity is **masked by default** for anyone whose role does not include
  employee-level pay, and the pseudonym is stable, per entity, and not
  reversible by hashing a staff list.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import ComponentConfig, Entity, SalaryRegister, SalaryRegisterRow, User
from app.services import workforce_analytics as wa
from app.services.dimensions import UNASSIGNED
from app.services.masking import Identity, mask_name, pseudonym

PASSWORD = "Passw0rd!x"


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@people-example.com".replace("_", "-")
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": PASSWORD, "company_name": "People Tests"})
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
                employee_name=r.get("name"),
                components=r.get("components", {"basic": 10000.0}),
                arrears=r.get("arrears", {}), deductions={},
                dimensions=r.get("dimensions") or _dims(),
                increment_arrear_total=Decimal(str(r.get("increment", 0))),
            ))
        db.commit()
    finally:
        db.close()


def _movement(entity, **kw):
    db = SessionLocal()
    try:
        return wa.headcount_movement(db, entity.id, **kw)
    finally:
        db.close()


def _comp(entity, **kw):
    db = SessionLocal()
    try:
        return wa.compensation_analysis(db, entity.id, **kw)
    finally:
        db.close()


# ── headcount movement ──────────────────────────────────────────────────────

def test_a_joiner_is_someone_paid_this_month_and_not_last(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1"}, {"employee_id": "E2"}])
    _register(entity, user, date(2026, 5, 1), [
        {"employee_id": "E1"}, {"employee_id": "E2"}, {"employee_id": "E3"},
    ])

    may = _movement(entity)["periods"][1]
    assert may["opening"] == 2
    assert may["joiners"] == 1
    assert may["exits"] == 0
    assert may["closing"] == 3
    assert may["net_change"] == 1
    assert may["joiner_ids"] == ["E3"]


def test_an_exit_is_someone_paid_last_month_and_not_this(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1"}, {"employee_id": "E2"}])
    _register(entity, user, date(2026, 5, 1), [{"employee_id": "E1"}])

    may = _movement(entity)["periods"][1]
    assert may["exits"] == 1
    assert may["exit_ids"] == ["E2"]
    assert may["closing"] == 1


def test_the_first_month_opens_against_nothing_not_against_zero(workspace):
    """Zero would say the company had nobody, which is a different, false claim."""
    entity, user, _ = workspace
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1"}])

    april = _movement(entity)["periods"][0]
    assert april["opening"] is None
    assert april["net_change"] is None
    assert april["closing"] == 1


def test_average_headcount_is_the_documented_denominator(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1"}, {"employee_id": "E2"}])
    _register(entity, user, date(2026, 5, 1), [
        {"employee_id": "E1"}, {"employee_id": "E2"},
        {"employee_id": "E3"}, {"employee_id": "E4"},
    ])

    result = _movement(entity)
    may = result["periods"][1]
    assert may["average_headcount"] == 3.0            # (2 + 4) / 2
    assert may["cost_per_head_closing"] == round(may["total_ctc"] / 4, 2)
    assert may["cost_per_head_average"] == round(may["total_ctc"] / 3, 2)
    assert "(opening + closing) / 2" in result["denominator_note"]


def test_a_filter_narrows_the_population(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "dimensions": _dims(department="Engineering")},
        {"employee_id": "E2", "dimensions": _dims(department="Sales")},
    ])
    result = _movement(entity, filters={"department": ["Engineering"]})
    assert result["periods"][0]["closing"] == 1


def test_movement_is_served_by_the_endpoint(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1"}])
    _register(entity, user, date(2026, 5, 1), [{"employee_id": "E1"}, {"employee_id": "E2"}])

    data = client.get("/api/bi/headcount-movement", headers=headers).json()["data"]
    assert [p["label"] for p in data["periods"]] == ["Apr 2026", "May 2026"]
    assert data["totals"]["joiners"] == 1


# ── compensation distribution ───────────────────────────────────────────────

def _payroll(entity, user, salaries: list[float], period=date(2026, 4, 1), **kw):
    _register(entity, user, period, [
        {"employee_id": f"E{i}", "components": {"basic": s}, **kw}
        for i, s in enumerate(salaries, start=1)
    ])


def test_the_median_is_reported_not_only_the_mean(workspace):
    """One founder's package moves an average and nothing else does."""
    entity, user, _ = workspace
    _payroll(entity, user, [10000, 10000, 10000, 10000, 1000000])

    overall = _comp(entity)["overall"]
    assert overall["count"] == 5
    assert overall["median"] < overall["mean"]
    # Median is the middle employee, annualised: 10,000 monthly plus gratuity.
    assert 120000 <= overall["median"] <= 130000


def test_quartiles_and_the_range_ratio_describe_the_spread(workspace):
    entity, user, _ = workspace
    _payroll(entity, user, [10000, 20000, 30000, 40000, 50000])

    overall = _comp(entity)["overall"]
    assert overall["p25"] < overall["median"] < overall["p75"] < overall["p90"]
    assert overall["min"] < overall["max"]
    assert overall["range_ratio"] == pytest.approx(5.0, abs=0.01)


def test_pay_is_reported_annualised_and_says_so(workspace):
    entity, user, _ = workspace
    _payroll(entity, user, [10000])

    result = _comp(entity)
    assert "× 12" in result["basis"]
    assert result["overall"]["median"] > 120000       # twelve months, plus gratuity


def test_arrears_are_excluded_from_annualisation(workspace):
    """A catch-up payment is not twelve times a year."""
    entity, user, _ = workspace
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "components": {"basic": 10000.0}, "arrears": {"basic": 90000.0}},
    ])
    assert _comp(entity)["overall"]["median"] < 200000


def test_distribution_groups_by_any_dimension(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "components": {"basic": 50000.0}, "dimensions": _dims(grade="M3")},
        {"employee_id": "E2", "components": {"basic": 20000.0}, "dimensions": _dims(grade="M1")},
        {"employee_id": "E3", "components": {"basic": 22000.0}, "dimensions": _dims(grade="M1")},
    ])

    result = _comp(entity, group_by="grade")
    by_grade = {g["group"]: g for g in result["groups"]}
    assert by_grade["M3"]["count"] == 1
    assert by_grade["M1"]["count"] == 2
    # Ranked by median, highest first.
    assert [g["group"] for g in result["groups"]] == ["M3", "M1"]


def test_salary_bands_count_every_employee_once(workspace):
    """The top band is closed, so the highest earner does not fall off the end."""
    entity, user, _ = workspace
    _payroll(entity, user, [10000, 20000, 30000, 40000, 50000, 60000, 70000, 80000])

    result = _comp(entity)
    assert sum(b["count"] for b in result["distribution"]) == 8


def test_fixed_and_variable_are_separated(workspace):
    entity, user, _ = workspace
    db = SessionLocal()
    try:
        for name in ("Basic", "Performance Bonus"):
            db.add(ComponentConfig(user_id=user.id, entity_id=entity.id, component_name=name))
        db.commit()
    finally:
        db.close()
    _register(entity, user, date(2026, 4, 1), [
        {"employee_id": "E1", "components": {"basic": 40000.0, "performance_bonus": 10000.0}},
    ])

    mix = _comp(entity)["mix"]
    assert mix["fixed"] == 40000.0
    assert mix["variable"] == 10000.0
    assert mix["variable_pct"] == 20.0


def test_an_entity_with_no_register_returns_an_empty_shape(workspace):
    entity, _, _ = workspace
    result = _comp(entity)
    assert result["overall"]["count"] == 0
    assert result["groups"] == []


def test_an_unknown_grouping_is_rejected(workspace):
    entity, _, _ = workspace
    with pytest.raises(ValueError):
        _comp(entity, group_by="astrological_sign")


# ── masking ─────────────────────────────────────────────────────────────────

def test_a_pseudonym_is_stable_within_an_entity_and_differs_across_them():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert pseudonym(a, "E1") == pseudonym(a, "E1")
    assert pseudonym(a, "E1") != pseudonym(a, "E2")
    assert pseudonym(a, "E1") != pseudonym(b, "E1")
    assert pseudonym(a, "E1").startswith("EMP-")


def test_a_pseudonym_is_not_a_plain_hash_of_the_employee_id():
    """Anyone holding a staff list could reverse that in a second."""
    import hashlib

    entity = uuid.uuid4()
    plain = hashlib.sha256(b"E1").hexdigest()[:6].upper()
    assert pseudonym(entity, "E1") != f"EMP-{plain}"


def test_a_name_is_reduced_to_initials():
    assert mask_name("Priya Sharma") == "P. S."
    assert mask_name(None) is None
    assert mask_name("   ") is None


def test_masking_removes_every_sensitive_field():
    identity = Identity(uuid.uuid4(), True, "test")
    row = identity.apply({
        "employee_id": "E1", "employee_name": "Priya Sharma", "pan": "ABCDE1234F",
        "bank_account": "123456789", "annual_ctc": 1200000,
    })
    assert row["employee_id"].startswith("EMP-")
    assert row["employee_name"] == "P. S."
    assert row["pan"] is None and row["bank_account"] is None
    # The figure everyone came for is untouched.
    assert row["annual_ctc"] == 1200000
    assert row["masked"] is True


def test_an_unmasked_identity_passes_a_row_through_unchanged():
    identity = Identity(uuid.uuid4(), False, "test")
    row = {"employee_id": "E1", "employee_name": "Priya Sharma"}
    assert identity.apply(row) == row


def test_a_caller_can_mask_a_session_deliberately(client, workspace):
    """What someone presenting to a room wants."""
    entity, user, headers = workspace
    _register(entity, user, date(2026, 4, 1), [{"employee_id": "E1", "name": "Priya Sharma"}])

    plain = client.get("/api/bi/compensation", headers=headers).json()["data"]
    assert plain["identity"]["masked"] is False
    assert plain["employees"][0]["employee_name"] == "Priya Sharma"

    masked = client.get(
        "/api/bi/compensation", headers={**headers, "X-Mask-Identity": "on"},
    ).json()["data"]
    assert masked["identity"]["masked"] is True
    assert masked["employees"][0]["employee_id"].startswith("EMP-")
    assert masked["employees"][0]["employee_name"] == "P. S."
    assert masked["employees"][0]["annual_ctc"] == plain["employees"][0]["annual_ctc"]
