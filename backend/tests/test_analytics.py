"""
Coverage for the cost bridge and the exposure ledger.

The bridge's contract is that its bars sum to the observed change. A
decomposition that leaves money unaccounted for is worse than none, so several
of these tests assert reconciliation rather than individual figures.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import Entity, FindingState, SalaryRegister, SalaryRegisterRow, User
from app.schemas.exposure_config import ExposureConfig
from app.services import analytics

PASSWORD = "Passw0rd!x"


def _signup(client, email: str) -> dict:
    r = client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "company_name": "Analytics Tests"},
    )
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.fixture()
def workspace(client, request):
    """A signed-in user with an entity of their own for this test."""
    email = f"{request.node.name[:40]}@analytics-example.com".replace("_", "-")
    headers = _signup(client, email)
    created = client.post(
        "/api/org/entities", json={"name": f"E-{request.node.name[:30]}"}, headers=headers
    )
    assert created.status_code == 200, created.text
    entity_id = created.json()["data"]["id"]

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        entity = db.get(Entity, uuid.UUID(entity_id))
        db.expunge_all()
    finally:
        db.close()
    return entity, user, {**headers, "X-Entity-Id": entity_id}


def _register(entity, user, period: date, rows: list[dict]) -> None:
    """Write a salary register directly, bypassing file upload."""
    db = SessionLocal()
    try:
        register = SalaryRegister(
            user_id=user.id,
            entity_id=entity.id,
            period_month=period,
            filename="test.csv",
            employee_count=len(rows),
        )
        db.add(register)
        db.flush()
        for row in rows:
            db.add(
                SalaryRegisterRow(
                    register_id=register.id,
                    user_id=user.id,
                    entity_id=entity.id,
                    period_month=period,
                    employee_id=row["employee_id"],
                    employee_name=row.get("employee_name"),
                    paid_days=Decimal(str(row["paid_days"])) if row.get("paid_days") else None,
                    lop_days=Decimal(str(row.get("lop_days", 0))),
                    components=row.get("components", {}),
                    arrears=row.get("arrears", {}),
                    increment_arrear_total=Decimal(str(row.get("increment_arrear", 0))),
                )
            )
        db.commit()
    finally:
        db.close()


def _emp(eid: str, basic: float, hra: float = 0.0, paid_days: float = 30, **kw) -> dict:
    return {
        "employee_id": eid,
        "employee_name": f"Employee {eid}",
        "paid_days": paid_days,
        "components": {"basic": basic, "hra": hra},
        **kw,
    }


def _bridge(entity, period: date) -> dict:
    db = SessionLocal()
    try:
        return analytics.cost_bridge(db, entity.id, period)
    finally:
        db.close()


def _effect(bridge: dict, key: str) -> float:
    return next(e["amount"] for e in bridge["effects"] if e["key"] == key)


def test_a_joiner_is_attributed_whole(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2025, 4, 1), [_emp("1001", 30000)])
    _register(entity, user, date(2025, 5, 1), [_emp("1001", 30000), _emp("2002", 20000)])

    bridge = _bridge(entity, date(2025, 5, 1))
    assert _effect(bridge, "joiners") == 20000.0
    assert bridge["headcount"] == {"opening": 1, "closing": 2, "joiners": 1, "leavers": 0}


def test_a_leaver_reduces_cost(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2025, 4, 1), [_emp("1001", 30000), _emp("2002", 20000)])
    _register(entity, user, date(2025, 5, 1), [_emp("1001", 30000)])

    bridge = _bridge(entity, date(2025, 5, 1))
    assert _effect(bridge, "leavers") == -20000.0
    assert bridge["net_change"] == -20000.0


def test_a_raise_is_a_pay_change_not_an_attendance_effect(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2025, 4, 1), [_emp("1001", 30000, paid_days=30)])
    _register(entity, user, date(2025, 5, 1), [_emp("1001", 33000, paid_days=30)])

    bridge = _bridge(entity, date(2025, 5, 1))
    assert _effect(bridge, "pay_change") == 3000.0
    assert _effect(bridge, "attendance") == 0.0


def test_lop_is_separated_from_pay(workspace):
    """A short month must not read as a pay cut."""
    entity, user, _ = workspace
    _register(entity, user, date(2025, 4, 1), [_emp("1001", 30000, paid_days=30)])
    # Same rate, three days of LOP: 27/30 of 30000 = 27000.
    _register(entity, user, date(2025, 5, 1), [_emp("1001", 27000, paid_days=27)])

    bridge = _bridge(entity, date(2025, 5, 1))
    assert _effect(bridge, "attendance") == -3000.0
    assert _effect(bridge, "pay_change") == 0.0


def test_arrears_are_not_mistaken_for_a_raise(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2025, 4, 1), [_emp("1001", 30000)])
    _register(
        entity, user, date(2025, 5, 1),
        [_emp("1001", 30000, arrears={"basic": 12000.0})],
    )

    bridge = _bridge(entity, date(2025, 5, 1))
    assert _effect(bridge, "arrears") == 12000.0
    assert _effect(bridge, "pay_change") == 0.0


def test_the_bridge_reconciles_on_a_mixed_month(workspace):
    """Joiners, leavers, a raise, LOP and arrears at once must still add up."""
    entity, user, _ = workspace
    _register(
        entity, user, date(2025, 4, 1),
        [
            _emp("1001", 30000, paid_days=30),
            _emp("2002", 25000, paid_days=30),
            _emp("3003", 40000, paid_days=30),   # leaves
        ],
    )
    _register(
        entity, user, date(2025, 5, 1),
        [
            _emp("1001", 34500, paid_days=30),                        # raise
            _emp("2002", 20833.33, paid_days=25),                     # LOP
            _emp("4004", 28000, paid_days=30),                        # joiner
            _emp("5005", 15000, paid_days=30, arrears={"basic": 5000.0}),  # joiner with arrears
        ],
    )

    bridge = _bridge(entity, date(2025, 5, 1))
    total = sum(e["amount"] for e in bridge["effects"])

    assert abs(total - bridge["net_change"]) < 0.02
    assert abs(bridge["unexplained"]) < 0.02


def test_a_month_without_a_prior_register_reads_as_all_joiners(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2025, 4, 1), [_emp("1001", 30000), _emp("2002", 20000)])

    bridge = _bridge(entity, date(2025, 4, 1))
    assert _effect(bridge, "joiners") == 50000.0
    assert bridge["opening_cost"] == 0.0
    assert abs(bridge["unexplained"]) < 0.01


def test_an_employee_with_no_prior_paid_days_falls_back_to_pay_change(workspace):
    """Without a daily rate to value it, attendance cannot be separated honestly."""
    entity, user, _ = workspace
    _register(entity, user, date(2025, 4, 1), [_emp("1001", 30000, paid_days=None)])
    _register(entity, user, date(2025, 5, 1), [_emp("1001", 27000, paid_days=27)])

    bridge = _bridge(entity, date(2025, 5, 1))
    assert _effect(bridge, "attendance") == 0.0
    assert _effect(bridge, "pay_change") == -3000.0
    assert abs(bridge["unexplained"]) < 0.01


def test_trend_reports_cost_per_head(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2025, 4, 1), [_emp("1001", 30000)])
    _register(entity, user, date(2025, 5, 1), [_emp("1001", 30000), _emp("2002", 20000)])

    db = SessionLocal()
    try:
        trend = analytics.cost_trend(db, entity.id, months=12)
    finally:
        db.close()

    assert [p["period"] for p in trend["points"]] == ["2025-04-01", "2025-05-01"]
    assert trend["points"][0]["cost_per_head"] == 30000.0
    assert trend["points"][1]["cost_per_head"] == 25000.0


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------
def _state(entity, **kw) -> None:
    db = SessionLocal()
    try:
        db.add(
            FindingState(
                entity_id=entity.id,
                fingerprint=uuid.uuid4().hex[:32],
                employee_id=kw.get("employee_id", "1001"),
                employee_name="Employee",
                rule_id=kw["rule_id"],
                rule_name="Rule",
                component="pf_employee",
                severity="CRITICAL",
                state=kw.get("state", "open"),
                first_seen_period=kw["first_seen_period"],
                last_seen_period=kw.get("last_seen_period", kw["first_seen_period"]),
                occurrence_count=1,
                last_financial_impact=Decimal(str(kw["impact"])),
            )
        )
        db.commit()
    finally:
        db.close()


def _exposure(entity, as_of: date) -> dict:
    db = SessionLocal()
    try:
        return analytics.statutory_exposure(db, entity.id, ExposureConfig(), as_of)
    finally:
        db.close()


def test_a_fresh_shortfall_carries_almost_no_interest(workspace):
    entity, _, _ = workspace
    _state(entity, rule_id="STAT-001", impact=10000, first_seen_period=date(2025, 6, 1))

    result = _exposure(entity, date(2025, 6, 15))
    pf = next(h for h in result["by_head"] if h["head"] == "pf")

    assert pf["principal"] == 10000.0
    assert pf["interest"] == 0.0
    assert pf["damages"] == 0.0


def test_an_aged_shortfall_accrues_interest_and_damages(workspace):
    """A year-old PF shortfall is worth materially more than its principal."""
    entity, _, _ = workspace
    _state(entity, rule_id="STAT-001", impact=10000, first_seen_period=date(2024, 6, 1))

    result = _exposure(entity, date(2025, 6, 1))
    pf = next(h for h in result["by_head"] if h["head"] == "pf")

    assert pf["principal"] == 10000.0
    assert pf["interest"] == 1200.0    # 12% for one year
    assert pf["damages"] == 2500.0     # 25% band beyond six months
    assert pf["total"] == 13700.0


def test_damages_are_capped_at_the_arrear_amount(workspace):
    entity, _, _ = workspace
    _state(entity, rule_id="STAT-001", impact=10000, first_seen_period=date(2015, 1, 1))

    result = _exposure(entity, date(2025, 1, 1))
    pf = next(h for h in result["by_head"] if h["head"] == "pf")
    # Ten years at 25% would be 250% of principal without the ceiling.
    assert pf["damages"] == 10000.0


def test_esic_accrues_interest_but_not_damages(workspace):
    entity, _, _ = workspace
    _state(entity, rule_id="STAT-004", impact=5000, first_seen_period=date(2024, 6, 1))

    result = _exposure(entity, date(2025, 6, 1))
    esic = next(h for h in result["by_head"] if h["head"] == "esic")

    assert esic["principal"] == 5000.0
    assert esic["interest"] == 600.0
    assert esic["damages"] == 0.0


def test_waived_exposure_is_counted_and_disclosed(workspace):
    """A waiver is a decision not to act, not a reason the money stops being owed."""
    entity, _, _ = workspace
    _state(entity, rule_id="STAT-001", impact=8000,
           first_seen_period=date(2025, 6, 1), state="waived")

    result = _exposure(entity, date(2025, 6, 15))
    assert result["total_principal"] == 8000.0
    assert result["waived_principal_included"] == 8000.0


def test_resolved_findings_leave_the_exposure(workspace):
    entity, _, _ = workspace
    _state(entity, rule_id="STAT-001", impact=8000,
           first_seen_period=date(2025, 1, 1), state="resolved")

    assert _exposure(entity, date(2025, 6, 1))["total_principal"] == 0.0


def test_exposure_is_aged_into_buckets(workspace):
    entity, _, _ = workspace
    _state(entity, rule_id="STAT-001", impact=1000, employee_id="a", first_seen_period=date(2025, 5, 1))
    _state(entity, rule_id="STAT-001", impact=2000, employee_id="b", first_seen_period=date(2025, 1, 1))
    _state(entity, rule_id="STAT-001", impact=4000, employee_id="c", first_seen_period=date(2023, 1, 1))

    ageing = _exposure(entity, date(2025, 6, 1))["ageing"]
    assert ageing["0-3m"] == 1000.0
    assert ageing["3-6m"] == 2000.0
    assert ageing["12m+"] == 4000.0


def test_an_unrecognised_rule_is_reported_rather_than_dropped(workspace):
    entity, _, _ = workspace
    _state(entity, rule_id="CUSTOM-999", impact=3000, first_seen_period=date(2025, 5, 1))

    result = _exposure(entity, date(2025, 6, 1))
    assert result["total_principal"] == 0.0
    assert result["unclassified_principal"] == 3000.0
