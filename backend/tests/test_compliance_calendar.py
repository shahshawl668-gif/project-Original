"""
Filing readiness against the statutory calendar.

The point this suite defends is the honest one: this product cannot see EPFO,
ESIC, a state PT portal or TRACES, so it must never report that anything was
*filed*. Everything here is about the due date and about what would make a
filing wrong — a missing register, an unresolved shortfall, an unsigned period.
A green tick nobody earned is worse than no panel at all, because the tick is
exactly what stops someone checking.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import (
    Entity,
    FindingState,
    PeriodSignOff,
    SalaryRegister,
    SalaryRegisterRow,
    User,
)
from app.services import compliance_calendar as cal

PASSWORD = "Passw0rd!x"


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@cal-example.com".replace("_", "-")
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": PASSWORD, "company_name": "Calendar Tests"})
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


def _register(entity, user, period: date) -> None:
    db = SessionLocal()
    try:
        reg = SalaryRegister(user_id=user.id, entity_id=entity.id, period_month=period,
                             filename="t.csv", employee_count=1)
        db.add(reg); db.flush()
        db.add(SalaryRegisterRow(
            register_id=reg.id, user_id=user.id, entity_id=entity.id,
            period_month=period, employee_id="E1", components={"basic": 20000.0},
            arrears={}, deductions={}, dimensions={},
        ))
        db.commit()
    finally:
        db.close()


def _finding(entity, period: date, rule_id: str, impact: float = 1200.0,
             state: str = "open") -> None:
    db = SessionLocal()
    try:
        db.add(FindingState(
            entity_id=entity.id, fingerprint=f"{rule_id}-{period}-{state}",
            employee_id="E1", employee_name="A", rule_id=rule_id,
            rule_name=rule_id, severity="high", state=state,
            first_seen_period=period, last_seen_period=period,
            last_financial_impact=Decimal(str(impact)),
        ))
        db.commit()
    finally:
        db.close()


def _sign(entity, user, period: date) -> None:
    db = SessionLocal()
    try:
        db.add(PeriodSignOff(entity_id=entity.id, period_month=period, state="signed"))
        db.commit()
    finally:
        db.close()


def _readiness(entity, period: date, as_of: date):
    db = SessionLocal()
    try:
        return cal.filing_readiness(db, entity.id, period, as_of)
    finally:
        db.close()


def _by_key(result) -> dict:
    return {o["key"]: o for o in result["obligations"]}


# ── the calendar itself ─────────────────────────────────────────────────────

def test_epf_and_esi_fall_due_on_the_fifteenth():
    assert cal.due_date("epf_ecr", date(2026, 8, 1))[0] == date(2026, 9, 15)
    assert cal.due_date("esic", date(2026, 8, 1))[0] == date(2026, 9, 15)


def test_tds_is_deposited_by_the_seventh():
    assert cal.due_date("tds_deposit", date(2026, 8, 1))[0] == date(2026, 9, 7)


def test_march_tds_gets_until_the_end_of_april():
    """The one month that does not follow the seventh-of-next rule."""
    due, basis = cal.due_date("tds_deposit", date(2026, 3, 1))
    assert due == date(2026, 4, 30)
    assert "30 April" in basis


def test_form_24q_follows_the_financial_year_quarters():
    for month, expected in (
        (4, date(2026, 7, 31)),      # Q1 Apr-Jun
        (8, date(2026, 10, 31)),     # Q2 Jul-Sep
        (11, date(2027, 1, 31)),     # Q3 Oct-Dec
    ):
        assert cal.due_date("form_24q", date(2026, month, 1))[0] == expected
    # Q4 Jan-Mar of the same financial year, which starts in the prior April.
    assert cal.due_date("form_24q", date(2027, 2, 1))[0] == date(2027, 5, 31)


def test_professional_tax_says_that_it_varies():
    """PT is state law. Quoting one date as though it were uniform is a lie."""
    _, basis = cal.due_date("pt", date(2026, 8, 1))
    assert "varies by state" in basis


def test_april_is_the_first_quarter():
    assert cal.fy_quarter(date(2026, 4, 1)) == (2026, 1)
    assert cal.fy_quarter(date(2027, 1, 1)) == (2026, 4)


# ── status ──────────────────────────────────────────────────────────────────

def test_nothing_uploaded_means_nothing_to_file_from(workspace):
    entity, _, _ = workspace
    result = _readiness(entity, date(2026, 8, 1), date(2026, 9, 1))
    assert all(o["status"] == "no_register" for o in result["obligations"])
    assert result["register_uploaded"] is False


def test_an_open_shortfall_blocks_the_head_it_belongs_to(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 8, 1))
    _finding(entity, date(2026, 8, 1), "PF-003", impact=4500.0)

    obligations = _by_key(_readiness(entity, date(2026, 8, 1), date(2026, 9, 1)))
    assert obligations["epf_ecr"]["status"] == "blocked"
    assert obligations["epf_ecr"]["open_findings"] == 1
    assert obligations["epf_ecr"]["at_risk_amount"] == 4500.0
    # An ESI filing is not wrong because PF is.
    assert obligations["esic"]["status"] != "blocked"


def test_a_shortfall_blocks_only_its_own_statute(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 8, 1))
    _finding(entity, date(2026, 8, 1), "ESIC-002")

    obligations = _by_key(_readiness(entity, date(2026, 8, 1), date(2026, 9, 1)))
    assert obligations["esic"]["status"] == "blocked"
    assert obligations["epf_ecr"]["open_findings"] == 0


def test_a_passed_date_on_an_unsigned_period_is_overdue(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 8, 1))

    obligations = _by_key(_readiness(entity, date(2026, 8, 1), date(2026, 9, 20)))
    assert obligations["epf_ecr"]["status"] == "overdue"
    assert obligations["epf_ecr"]["days_left"] < 0


def test_the_week_before_is_due_soon(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 8, 1))

    obligations = _by_key(_readiness(entity, date(2026, 8, 1), date(2026, 9, 10)))
    assert obligations["epf_ecr"]["status"] == "due_soon"
    assert obligations["epf_ecr"]["days_left"] == 5


def test_a_signed_period_with_nothing_outstanding_is_ready(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 8, 1))
    _sign(entity, user, date(2026, 8, 1))

    result = _readiness(entity, date(2026, 8, 1), date(2026, 9, 1))
    assert result["signed_off"] is True
    assert _by_key(result)["epf_ecr"]["status"] == "ready"


def test_signing_off_does_not_clear_a_known_shortfall(workspace):
    """Signing says someone looked. It does not say the money stopped being owed."""
    entity, user, _ = workspace
    _register(entity, user, date(2026, 8, 1))
    _sign(entity, user, date(2026, 8, 1))
    _finding(entity, date(2026, 8, 1), "PF-003")

    assert _by_key(_readiness(entity, date(2026, 8, 1), date(2026, 9, 1)))["epf_ecr"]["status"] == "blocked"


def test_a_resolved_finding_no_longer_blocks(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 8, 1))
    _finding(entity, date(2026, 8, 1), "PF-003", state="resolved")

    assert _by_key(_readiness(entity, date(2026, 8, 1), date(2026, 9, 1)))["epf_ecr"]["open_findings"] == 0


# ── the promise it must not break ───────────────────────────────────────────

def test_no_status_ever_claims_a_return_was_filed(workspace):
    entity, user, _ = workspace
    _register(entity, user, date(2026, 8, 1))
    _sign(entity, user, date(2026, 8, 1))

    result = _readiness(entity, date(2026, 8, 1), date(2026, 9, 1))
    statuses = {o["status"] for o in result["obligations"]}
    assert not statuses & {"filed", "submitted", "acknowledged", "complete"}
    assert "cannot confirm that any return was filed" in result["disclaimer"]


# ── through the API ─────────────────────────────────────────────────────────

def test_the_endpoint_serves_one_period(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 8, 1))

    r = client.get("/api/bi/compliance?period=2026-08-01", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["period_label"] == "Aug 2026"
    assert len(data["obligations"]) == len(cal.OBLIGATIONS)


def test_the_endpoint_serves_a_calendar_newest_first(client, workspace):
    entity, user, headers = workspace
    for month in (6, 7, 8):
        _register(entity, user, date(2026, month, 1))

    data = client.get("/api/bi/compliance?months=2", headers=headers).json()["data"]
    assert [p["period_label"] for p in data["periods"]] == ["Aug 2026", "Jul 2026"]


def test_compliance_does_not_leak_between_entities(client, workspace):
    entity, user, headers = workspace
    _register(entity, user, date(2026, 8, 1))
    other = client.post("/api/org/entities", json={"name": "Other"},
                        headers=headers).json()["data"]["id"]

    data = client.get("/api/bi/compliance?period=2026-08-01",
                      headers={**headers, "X-Entity-Id": other}).json()["data"]
    assert data["register_uploaded"] is False
