"""
Minimum wage lookup, proration and compliance.

The behaviour that matters most here is the negative case: an employee the
engine cannot assess must say so, never pass quietly.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import Entity, MinimumWageRate, User
from app.services import minimum_wage as mw

PASSWORD = "Passw0rd!x"


def _signup(client, email: str) -> dict:
    r = client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "company_name": "MW Tests"},
    )
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@mw-example.com".replace("_", "-")
    headers = _signup(client, email)
    created = client.post(
        "/api/org/entities", json={"name": f"E-{request.node.name[:30]}"}, headers=headers
    )
    entity_id = created.json()["data"]["id"]
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        entity = db.get(Entity, uuid.UUID(entity_id))
        db.expunge_all()
    finally:
        db.close()
    return entity, user, {**headers, "X-Entity-Id": entity_id}


def _add_rate(entity, user, **kw) -> None:
    db = SessionLocal()
    try:
        db.add(
            MinimumWageRate(
                entity_id=entity.id,
                user_id=user.id,
                state=kw.get("state", "Karnataka"),
                zone=kw.get("zone", "*"),
                scheduled_employment=kw.get("scheduled_employment", "*"),
                skill_category=kw.get("skill_category", "skilled"),
                basic_per_month=Decimal(str(kw.get("basic", 15000))),
                vda_per_month=Decimal(str(kw.get("vda", 1000))),
                working_days_basis=Decimal("26"),
                effective_from=kw.get("effective_from", date(2025, 4, 1)),
                effective_to=kw.get("effective_to"),
                source_reference=kw.get("source", "Notification XYZ"),
            )
        )
        db.commit()
    finally:
        db.close()


def _check(entity, **kw):
    db = SessionLocal()
    try:
        return mw.check_employee(
            db, entity.id,
            employee_id=kw.get("employee_id", "1001"),
            employee_name="Test Employee",
            components=kw["components"],
            state=kw.get("state", "Karnataka"),
            skill_category=kw.get("skill_category", "skilled"),
            paid_days=kw.get("paid_days", Decimal("30")),
            calendar_days=kw.get("calendar_days", Decimal("30")),
            as_of=kw.get("as_of", date(2025, 6, 30)),
            basis=kw.get("basis", "wages_excl_hra"),
        )
    finally:
        db.close()


def test_pay_above_the_floor_produces_no_finding(workspace):
    entity, user, _ = workspace
    _add_rate(entity, user, basic=15000, vda=1000)   # floor 16,000

    assert _check(entity, components={"basic": 12000, "special_allowance": 6000}) is None


def test_pay_below_the_floor_is_critical_and_quantified(workspace):
    entity, user, _ = workspace
    _add_rate(entity, user, basic=15000, vda=1000)

    finding = _check(entity, components={"basic": 10000, "special_allowance": 4000})
    assert finding["rule_id"] == "MW-001"
    assert finding["severity"] == "CRITICAL"
    assert finding["financial_impact"] == 2000.0
    assert "Notification XYZ" in finding["reason"]


def test_hra_does_not_count_towards_the_floor_by_default(workspace):
    entity, user, _ = workspace
    _add_rate(entity, user, basic=15000, vda=1000)

    # 14,000 of wages plus 5,000 HRA: above the floor only if HRA counts.
    finding = _check(entity, components={"basic": 14000, "hra": 5000})
    assert finding is not None
    assert finding["financial_impact"] == 2000.0

    # On the widest basis the same pay clears the floor.
    assert _check(entity, components={"basic": 14000, "hra": 5000}, basis="gross") is None


def test_the_basis_used_is_stated_in_the_finding(workspace):
    """A reviewer should be able to disagree with the setting, not just the number."""
    entity, user, _ = workspace
    _add_rate(entity, user, basic=15000, vda=1000)

    finding = _check(entity, components={"basic": 10000}, basis="basic_da")
    assert "'basic_da' basis" in finding["reason"]


def test_the_floor_is_prorated_for_unpaid_days(workspace):
    """Otherwise every employee who took leave manufactures a violation."""
    entity, user, _ = workspace
    _add_rate(entity, user, basic=15000, vda=1000)   # floor 16,000

    # 15 of 30 days paid, and pay of 8,000 — exactly half the floor.
    assert _check(
        entity,
        components={"basic": 8000},
        paid_days=Decimal("15"),
        calendar_days=Decimal("30"),
    ) is None


def test_a_missing_rate_reports_that_it_could_not_verify(workspace):
    """Silence here would let an unmaintained table read as a clean bill of health."""
    entity, _, _ = workspace

    finding = _check(entity, components={"basic": 1000}, state="Kerala")
    assert finding["rule_id"] == "MW-003"
    assert finding["severity"] == "INFO"
    assert "No minimum wage rate on file" in finding["reason"]


def test_missing_master_classification_also_reports_a_gap(workspace):
    entity, user, _ = workspace
    _add_rate(entity, user)

    finding = _check(entity, components={"basic": 1000}, skill_category=None)
    assert finding["rule_id"] == "MW-003"
    assert "skill category" in finding["reason"]


def test_a_more_specific_rate_beats_a_wildcard(workspace):
    """Specificity wins over recency, so a general row cannot mask a schedule."""
    entity, user, _ = workspace
    _add_rate(entity, user, basic=10000, vda=0, effective_from=date(2025, 5, 1))
    _add_rate(
        entity, user, basic=20000, vda=0,
        scheduled_employment="Engineering Industry",
        effective_from=date(2025, 4, 1),
    )

    db = SessionLocal()
    try:
        rate = mw.lookup_rate(
            db, entity.id,
            state="Karnataka", skill_category="skilled",
            as_of=date(2025, 6, 1),
            scheduled_employment="Engineering Industry",
        )
    finally:
        db.close()
    assert rate.total_per_month == Decimal("20000.00")


def test_the_latest_rate_in_force_is_used(workspace):
    entity, user, _ = workspace
    _add_rate(entity, user, basic=15000, vda=500, effective_from=date(2025, 4, 1))
    _add_rate(entity, user, basic=15000, vda=1500, effective_from=date(2025, 10, 1))

    db = SessionLocal()
    try:
        before = mw.lookup_rate(db, entity.id, state="Karnataka",
                                skill_category="skilled", as_of=date(2025, 6, 1))
        after = mw.lookup_rate(db, entity.id, state="Karnataka",
                               skill_category="skilled", as_of=date(2025, 11, 1))
    finally:
        db.close()

    assert before.total_per_month == Decimal("15500.00")
    assert after.total_per_month == Decimal("16500.00")


def test_an_expired_rate_is_not_used(workspace):
    entity, user, _ = workspace
    _add_rate(entity, user, effective_from=date(2024, 4, 1), effective_to=date(2025, 3, 31))

    db = SessionLocal()
    try:
        rate = mw.lookup_rate(db, entity.id, state="Karnataka",
                              skill_category="skilled", as_of=date(2025, 6, 1))
    finally:
        db.close()
    assert rate is None


def test_reimporting_a_corrected_sheet_updates_rather_than_duplicates(client, workspace):
    entity, user, h = workspace
    payload = {
        "rates": [
            {
                "state": "Maharashtra", "skill_category": "unskilled",
                "basic_per_month": "12000", "vda_per_month": "800",
                "effective_from": "2025-04-01",
            }
        ]
    }
    first = client.post("/api/minimum-wage/rates/import", json=payload, headers=h).json()["data"]
    assert first == {"created": 1, "updated": 0}

    payload["rates"][0]["vda_per_month"] = "900"
    second = client.post("/api/minimum-wage/rates/import", json=payload, headers=h).json()["data"]
    assert second == {"created": 0, "updated": 1}

    rates = client.get("/api/minimum-wage/rates", headers=h).json()["data"]
    assert len(rates) == 1
    assert Decimal(rates[0]["vda_per_month"]) == Decimal("900")


def test_coverage_report_names_the_gaps(client, workspace):
    entity, user, h = workspace
    _add_rate(entity, user, state="Karnataka", skill_category="skilled")

    import io
    import pandas as pd

    buf = io.StringIO()
    pd.DataFrame([
        {"Emp Code": "1001", "State": "Karnataka", "Skill": "skilled"},
        {"Emp Code": "1002", "State": "Tamil Nadu", "Skill": "unskilled"},
        {"Emp Code": "1003", "State": "", "Skill": ""},
    ]).to_csv(buf, index=False)

    client.post(
        "/api/workforce/master/commit",
        files={"file": ("m.csv", buf.getvalue().encode(), "text/csv")},
        data={"meta": '{"effective_from": "2025-04-01"}'},
        headers=h,
    )

    report = client.get("/api/minimum-wage/coverage?as_of=2025-06-30", headers=h).json()["data"]
    assert report["covered"] == [{"state": "Karnataka", "skill_category": "skilled"}]
    assert report["missing"] == [{"state": "Tamil Nadu", "skill_category": "unskilled"}]
    assert report["employees_without_classification"] == 1
    assert report["coverage_pct"] == 50.0


def test_minimum_wage_requires_an_explicit_effective_dated_yes_or_no(client, workspace):
    _, _, headers = workspace
    unconfigured = client.post("/api/minimum-wage/check?period=2025-06-01", headers=headers)
    assert unconfigured.status_code == 409

    no_reason = client.post("/api/minimum-wage/applicability", headers=headers, json={
        "effective_from": "2025-04-01", "applicable": False,
    })
    assert no_reason.status_code == 422

    excluded = client.post("/api/minimum-wage/applicability", headers=headers, json={
        "effective_from": "2025-04-01", "applicable": False,
        "reason": "Reviewed scope for this entity", "source_reference": "Legal review A",
    })
    assert excluded.status_code == 200, excluded.text
    skipped = client.post("/api/minimum-wage/check?period=2025-06-01", headers=headers)
    assert skipped.status_code == 200
    assert skipped.json()["data"]["status"] == "not_applicable"
    assert skipped.json()["data"]["findings"] == []

    included = client.post("/api/minimum-wage/applicability", headers=headers, json={
        "effective_from": "2026-04-01", "applicable": True,
        "source_reference": "Notification B",
    })
    assert included.status_code == 200, included.text
    historical = client.get("/api/minimum-wage/applicability?as_of=2025-06-30", headers=headers)
    assert historical.json()["data"]["current"]["applicable"] is False
    current = client.get("/api/minimum-wage/applicability?as_of=2026-06-30", headers=headers)
    assert current.json()["data"]["current"]["applicable"] is True
    assert len(current.json()["data"]["history"]) == 2
