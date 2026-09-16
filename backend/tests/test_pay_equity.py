"""
The gender pay gap.

This is the most sensitive analytic in the product and the one most easily
misread, so most of this suite is about what it must refuse to do rather than
what it computes:

* it must not run at all until the employer authorises it, per entity;
* it must not be readable by the tier that can see individual salaries;
* it must never emit an individual, at any permission level;
* it must withhold any group small enough that a median discloses someone's pay,
  and say that it withheld it;
* it must not fold a third gender into the binary, or drop the employees whose
  gender nobody recorded.

The arithmetic is the easy half.
"""
from __future__ import annotations

import io
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import (
    ComponentConfig,
    EmployeeMasterUpload,
    EmployeeRecord,
    Entity,
    SalaryRegister,
    SalaryRegisterRow,
    User,
)
from app.services import pay_equity as pe
from app.services.dimensions import UNASSIGNED

PASSWORD = "Passw0rd!x"


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@equity-example.com".replace("_", "-")
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": PASSWORD, "company_name": "Equity Tests"})
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


def _people(entity, user, people: list[dict], period=date(2026, 4, 1)) -> None:
    """One register month plus the employee master that records gender."""
    db = SessionLocal()
    try:
        upload = EmployeeMasterUpload(user_id=user.id, entity_id=entity.id,
                                      effective_from=period, filename="master.csv",
                                      employee_count=len(people))
        db.add(upload); db.flush()
        register = SalaryRegister(user_id=user.id, entity_id=entity.id, period_month=period,
                                  filename="register.csv", employee_count=len(people))
        db.add(register); db.flush()

        for person in people:
            db.add(EmployeeRecord(
                upload_id=upload.id, user_id=user.id, entity_id=entity.id,
                employee_id=person["employee_id"], effective_from=period,
                employee_name=person.get("name"), gender=person.get("gender"),
                grade=person.get("grade"), department=person.get("department"),
            ))
            components = {"basic": float(person["pay"])}
            if person.get("variable"):
                components["performance_bonus"] = float(person["variable"])
            db.add(SalaryRegisterRow(
                register_id=register.id, user_id=user.id, entity_id=entity.id,
                period_month=period, employee_id=person["employee_id"],
                employee_name=person.get("name"), components=components,
                arrears={}, deductions={},
                dimensions=_dims(grade=person.get("grade") or UNASSIGNED,
                                 department=person.get("department") or UNASSIGNED),
                increment_arrear_total=Decimal("0"),
            ))
        db.commit()
    finally:
        db.close()


def _components(entity, user) -> None:
    db = SessionLocal()
    try:
        for name in ("Basic", "Performance Bonus"):
            db.add(ComponentConfig(user_id=user.id, entity_id=entity.id, component_name=name))
        db.commit()
    finally:
        db.close()


def _analyse(entity, **kw):
    db = SessionLocal()
    try:
        return pe.pay_equity(db, entity.id, **kw)
    finally:
        db.close()


def _cohort(count: int, gender: str, pay: float, prefix: str, **kw) -> list[dict]:
    return [
        {"employee_id": f"{prefix}{i}", "gender": gender, "pay": pay, **kw}
        for i in range(count)
    ]


# ── the gate ────────────────────────────────────────────────────────────────

def test_the_analysis_is_off_until_the_employer_turns_it_on(client, workspace):
    """India mandates no gender pay reporting. Running it is the employer's call."""
    _, _, headers = workspace
    r = client.get("/api/bi/pay-equity", headers=headers)
    assert r.status_code == 403
    assert "not enabled" in r.json()["error"]["detail"]


def test_enabling_it_records_who_did_so(client, workspace):
    entity, user, headers = workspace

    client.put("/api/bi/pay-equity/settings",
               json={"enabled": True, "authorisation_note": "Board approved 12 Mar"},
               headers=headers)
    settings = client.get("/api/bi/pay-equity/settings", headers=headers).json()["data"]
    assert settings["enabled"] is True
    assert settings["enabled_by"] == user.email
    assert settings["enabled_at"]

    # And the authorisation itself is in the trail, with its note.
    events = client.get("/api/audit?action=pay_equity.enabled",
                        headers=headers).json()["data"]["events"]
    assert events and events[0]["detail"]["note"] == "Board approved 12 Mar"


def test_authorisation_can_be_withdrawn(client, workspace):
    _, _, headers = workspace
    client.put("/api/bi/pay-equity/settings", json={"enabled": True}, headers=headers)
    client.put("/api/bi/pay-equity/settings", json={"enabled": False}, headers=headers)

    assert client.get("/api/bi/pay-equity", headers=headers).status_code == 403
    events = client.get("/api/audit?action=pay_equity.disabled",
                        headers=headers).json()["data"]["events"]
    assert events


def test_one_clients_authorisation_does_not_enable_it_for_the_book(client, workspace):
    """A bureau holds many entities. Consent belongs to one of them."""
    _, _, headers = workspace
    client.put("/api/bi/pay-equity/settings", json={"enabled": True}, headers=headers)
    other = client.post("/api/org/entities", json={"name": "Other client"},
                        headers=headers).json()["data"]["id"]

    elsewhere = {**headers, "X-Entity-Id": other}
    assert client.get("/api/bi/pay-equity", headers=elsewhere).status_code == 403


def test_every_view_is_written_to_the_trail(client, workspace):
    """Who looked at this is itself a governance question."""
    entity, user, headers = workspace
    _components(entity, user)
    _people(entity, user, _cohort(6, "F", 50000, "W"))
    client.put("/api/bi/pay-equity/settings", json={"enabled": True}, headers=headers)
    client.get("/api/bi/pay-equity", headers=headers)

    events = client.get("/api/audit?action=pay_equity.viewed",
                        headers=headers).json()["data"]["events"]
    assert events and events[0]["user_email"] == user.email


def test_no_individual_is_returned_at_any_permission_level(client, workspace):
    """Unlike every other analytic here, there is no employee-level row."""
    entity, user, headers = workspace
    _components(entity, user)
    _people(entity, user, _cohort(6, "F", 50000, "W", name="Priya Sharma")
                          + _cohort(6, "M", 60000, "M", name="Rahul Verma"))
    client.put("/api/bi/pay-equity/settings", json={"enabled": True}, headers=headers)

    body = client.get("/api/bi/pay-equity", headers=headers).text
    assert "Priya Sharma" not in body
    assert "Rahul Verma" not in body
    assert "employees" not in client.get("/api/bi/pay-equity", headers=headers).json()["data"]


# ── suppression ─────────────────────────────────────────────────────────────

def test_a_group_below_the_minimum_is_withheld_and_says_so(workspace):
    """A median over two people discloses two salaries."""
    entity, user, _ = workspace
    _components(entity, user)
    _people(entity, user, _cohort(2, "F", 50000, "W") + _cohort(8, "M", 60000, "M"))

    result = _analyse(entity)
    assert result["headline"]["comparable"] is False
    assert result["headline"]["median_gap_pct"] is None
    assert result["headline"]["women"]["suppressed"] is True
    assert result["headline"]["women"]["median"] is None
    # The count is still shown — the absence of women is itself the finding.
    assert result["headline"]["women"]["count"] == 2
    assert "Fewer than 5" in result["headline"]["reason"]


def test_a_caller_may_raise_the_threshold_but_never_lower_it(workspace):
    entity, user, _ = workspace
    _components(entity, user)
    _people(entity, user, _cohort(6, "F", 50000, "W") + _cohort(6, "M", 60000, "M"))

    assert _analyse(entity)["headline"]["comparable"] is True
    assert _analyse(entity, min_group_size=10)["headline"]["comparable"] is False
    # Asking for 1 does not get 1.
    lowered = _analyse(entity, min_group_size=1)
    assert lowered["min_group_size"] == pe.MIN_GROUP_SIZE
    assert lowered["headline"]["comparable"] is True


def test_withheld_groups_are_listed_rather_than_vanishing(workspace):
    entity, user, _ = workspace
    _components(entity, user)
    _people(
        entity, user,
        _cohort(6, "F", 50000, "W", grade="M2") + _cohort(6, "M", 60000, "M", grade="M2")
        + _cohort(1, "F", 90000, "WS", grade="M5") + _cohort(6, "M", 95000, "MS", grade="M5"),
    )

    result = _analyse(entity, group_by="grade")
    withheld = {g["group"] for g in result["suppressed_groups"]}
    assert withheld == {"M5"}
    assert result["suppressed_groups"][0]["women"] == 1


# ── the arithmetic ──────────────────────────────────────────────────────────

def test_a_positive_gap_means_women_are_paid_less(workspace):
    """The convention every published pay gap uses, and the one readers misremember."""
    entity, user, _ = workspace
    _components(entity, user)
    _people(entity, user, _cohort(6, "F", 40000, "W") + _cohort(6, "M", 50000, "M"))

    result = _analyse(entity)
    assert result["headline"]["median_gap_pct"] == pytest.approx(20.0, abs=0.1)
    assert "positive figure means women are paid less" in result["direction"]


def test_a_negative_gap_means_women_are_paid_more(workspace):
    entity, user, _ = workspace
    _components(entity, user)
    _people(entity, user, _cohort(6, "F", 50000, "W") + _cohort(6, "M", 40000, "M"))

    assert _analyse(entity)["headline"]["median_gap_pct"] == pytest.approx(-25.0, abs=0.1)


def test_mean_and_median_are_both_reported(workspace):
    """A mean is moved by one large package; a median is not. Both, always."""
    entity, user, _ = workspace
    _components(entity, user)
    _people(
        entity, user,
        _cohort(5, "F", 40000, "W") + [{"employee_id": "WX", "gender": "F", "pay": 400000}]
        + _cohort(6, "M", 40000, "M"),
    )

    headline = _analyse(entity)["headline"]
    assert headline["median_gap_pct"] == pytest.approx(0.0, abs=0.1)   # same middle
    assert headline["mean_gap_pct"] < -100                             # skewed by one package


def test_the_unadjusted_gap_can_be_large_with_no_like_for_like_gap(workspace):
    """
    The distinction the whole analysis exists to make: a firm whose senior roles
    are held by men has a wide headline gap while paying equally within a grade.
    """
    entity, user, _ = workspace
    _components(entity, user)
    _people(
        entity, user,
        _cohort(6, "F", 30000, "WJ", grade="M1") + _cohort(6, "M", 30000, "MJ", grade="M1")
        + _cohort(1, "F", 90000, "WS", grade="M5") + _cohort(11, "M", 90000, "MS", grade="M5"),
    )

    result = _analyse(entity, group_by="grade")
    assert result["headline"]["median_gap_pct"] > 40          # the headline is wide
    junior = next(g for g in result["like_for_like"] if g["group"] == "M1")
    assert junior["median_gap_pct"] == pytest.approx(0.0, abs=0.1)   # and equal within grade


def test_variable_pay_is_compared_separately(workspace):
    """The bonus gap is routinely much wider than the base pay gap."""
    entity, user, _ = workspace
    _components(entity, user)
    _people(
        entity, user,
        _cohort(6, "F", 50000, "W", variable=1000) + _cohort(6, "M", 50000, "M", variable=5000),
    )

    result = _analyse(entity)
    headline = result["headline"]
    # Ordinary pay is identical; the whole gap is in the bonus. Folding variable
    # pay into the headline would have hidden that.
    assert headline["median_gap_pct"] == pytest.approx(0.0, abs=0.1)
    assert headline["variable_gap_pct"] == pytest.approx(80.0, abs=0.1)
    assert headline["women"]["variable_receipt_pct"] == 100.0
    assert "excluding arrears and variable pay" in result["basis"]


def test_a_gap_against_zero_pay_is_undefined_not_infinite(workspace):
    assert pe.gap_pct(Decimal("0"), Decimal("100")) is None
    assert pe.gap_pct(Decimal("100"), Decimal("0")) == 100.0


# ── representation ──────────────────────────────────────────────────────────

def test_pay_quartiles_show_representation_directly(workspace):
    """An organisation can have no like-for-like gap and every woman in the lowest band."""
    entity, user, _ = workspace
    _components(entity, user)
    _people(
        entity, user,
        _cohort(6, "F", 20000, "W") + _cohort(6, "M", 80000, "M"),
    )

    quartiles = _analyse(entity)["quartiles"]
    assert [q["band"] for q in quartiles] == ["Lower", "Lower middle", "Upper middle", "Upper"]
    assert sum(q["count"] for q in quartiles) == 12
    assert quartiles[0]["female_pct"] == 100.0
    assert quartiles[-1]["female_pct"] == 0.0


def test_quartiles_divide_an_uneven_population_without_losing_anyone(workspace):
    entity, user, _ = workspace
    _components(entity, user)
    _people(entity, user, [
        {"employee_id": f"E{i}", "gender": "F" if i % 2 else "M", "pay": 10000 + i * 1000}
        for i in range(13)
    ])

    quartiles = _analyse(entity)["quartiles"]
    assert sum(q["count"] for q in quartiles) == 13
    assert [q["count"] for q in quartiles] == [4, 3, 3, 3]


# ── the categories ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("M", "male"), ("Male", "male"), ("male", "male"),
    ("F", "female"), ("Female", "female"), ("WOMAN", "female"),
    ("Transgender", "other"), ("Non-binary", "other"), ("Other", "other"),
    ("prefer not to say", "other"),
    (None, "not_recorded"), ("", "not_recorded"), ("  ", "not_recorded"),
    ("nan", "not_recorded"), ("unknown", "not_recorded"),
    ("dragon", "not_recorded"),
])
def test_gender_values_are_read_without_guessing(raw, expected):
    assert pe.normalise_gender(raw) == expected


def test_a_third_gender_is_counted_in_its_own_right(workspace):
    """Never folded into the binary, and never silently discarded."""
    entity, user, _ = workspace
    _components(entity, user)
    _people(
        entity, user,
        _cohort(6, "F", 50000, "W") + _cohort(6, "M", 50000, "M")
        + _cohort(2, "Transgender", 50000, "T"),
    )

    coverage = {row["key"]: row["count"] for row in _analyse(entity)["coverage"]["by_gender"]}
    assert coverage["other"] == 2
    assert coverage["female"] == 6 and coverage["male"] == 6
    # Two people is below the threshold, so their figures are withheld — a fact
    # about group size, not a judgement about the group.
    assert _analyse(entity)["headline"]["other"]["suppressed"] is True


def test_employees_with_no_gender_recorded_are_counted_not_dropped(workspace):
    """Dropping them silently changes the denominator of everything above."""
    entity, user, _ = workspace
    _components(entity, user)
    _people(entity, user, _cohort(6, "F", 50000, "W") + _cohort(6, "M", 50000, "M")
                          + _cohort(4, None, 50000, "U"))

    coverage = _analyse(entity)["coverage"]
    assert coverage["total"] == 16
    assert coverage["recorded"] == 12
    assert coverage["recorded_pct"] == pytest.approx(75.0, abs=0.1)


def test_quartile_shares_are_of_known_gender_and_say_so(workspace):
    """A share of the whole band would treat a gap in the master as a third gender."""
    entity, user, _ = workspace
    _components(entity, user)
    # The unrecorded employees are paid least, so they land in the lower band
    # together with one woman — a share of the whole band would read as 25%.
    _people(entity, user, [
        {"employee_id": f"U{i}", "gender": None, "pay": 20000 + i} for i in range(3)
    ] + [
        {"employee_id": f"W{i}", "gender": "F", "pay": 60000 + i} for i in range(5)
    ])

    quartile = _analyse(entity)["quartiles"][0]
    assert quartile["count"] == 2
    assert quartile["known"] == 0
    # No gender recorded in this band at all, so there is no share to report.
    assert quartile["female_pct"] is None

    top = _analyse(entity)["quartiles"][-1]
    assert top["known"] == top["count"]
    assert top["female_pct"] == 100.0


def test_no_master_means_no_coverage_rather_than_a_confident_zero(workspace):
    entity, user, _ = workspace
    _components(entity, user)
    db = SessionLocal()
    try:
        register = SalaryRegister(user_id=user.id, entity_id=entity.id,
                                  period_month=date(2026, 4, 1), filename="r.csv",
                                  employee_count=1)
        db.add(register); db.flush()
        db.add(SalaryRegisterRow(
            register_id=register.id, user_id=user.id, entity_id=entity.id,
            period_month=date(2026, 4, 1), employee_id="E1",
            components={"basic": 50000.0}, arrears={}, deductions={}, dimensions=_dims(),
        ))
        db.commit()
    finally:
        db.close()

    result = _analyse(entity)
    assert result["coverage"]["recorded"] == 0
    assert result["coverage"]["recorded_pct"] == 0.0
    assert result["headline"]["comparable"] is False


def test_an_entity_with_no_register_returns_an_empty_shape(workspace):
    entity, _, _ = workspace
    result = _analyse(entity)
    assert result["headline"] is None
    assert result["quartiles"] == []
    assert result["caveats"]


def test_an_unknown_grouping_is_rejected(workspace):
    entity, _, _ = workspace
    with pytest.raises(ValueError):
        _analyse(entity, group_by="star_sign")


# ── what it refuses to claim ────────────────────────────────────────────────

def test_the_output_says_what_it_is_not(workspace):
    entity, user, _ = workspace
    _components(entity, user)
    _people(entity, user, _cohort(6, "F", 50000, "W") + _cohort(6, "M", 50000, "M"))

    caveats = " ".join(_analyse(entity)["caveats"])
    assert "not a measure of unequal pay for the same work" in caveats
    assert "not a finding of discrimination" in caveats
    assert "Code on Wages" in caveats


# ── the export ──────────────────────────────────────────────────────────────

def test_the_export_carries_the_same_suppression(client, workspace):
    entity, user, headers = workspace
    _components(entity, user)
    _people(entity, user, _cohort(2, "F", 50000, "W") + _cohort(8, "M", 60000, "M"))
    client.put("/api/bi/pay-equity/settings", json={"enabled": True}, headers=headers)

    import openpyxl

    payload = client.get("/api/reports/pay-equity.xlsx", headers=headers).content
    wb = openpyxl.load_workbook(io.BytesIO(payload))
    assert "How to read this" in wb.sheetnames

    headline = {row[0]: row[1] for row in wb["Headline gap"].iter_rows(values_only=True) if row[0]}
    assert headline["Median gap %"] is None
    assert headline["Women — count"] == 2
    assert headline["Comparable"] == "no"
