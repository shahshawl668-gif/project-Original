"""
Findings must behave as a record, not as a report.

An exception explained once should stay explained; a problem that keeps
recurring should say so; and none of it should leak between entities.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.database import SessionLocal
from app.models import Entity, FindingState, User
from app.services import finding_store


PASSWORD = "Passw0rd!x"


def _signup(client, email: str, company: str) -> dict:
    """Sign up, or log in if a function-scoped fixture already registered this email."""
    r = client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "company_name": company},
    )
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.fixture()
def workspace(client, request):
    """
    A signed-in user with an entity of their own for this test.

    Lifecycle state accumulates by design, so tests that record several months
    must not share an entity — otherwise one test's history becomes another's
    starting point.
    """
    email = f"{request.node.name[:40]}@lifecycle-example.com".replace("_", "-")
    headers = _signup(client, email, "Lifecycle Tests")
    created = client.post(
        "/api/org/entities", json={"name": f"E-{request.node.name[:30]}"}, headers=headers
    )
    assert created.status_code == 200, created.text
    entity_id = created.json()["data"]["id"]
    headers = {**headers, "X-Entity-Id": entity_id}

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        entity = db.get(Entity, uuid.UUID(entity_id))
        db.expunge_all()
    finally:
        db.close()
    return entity, user, headers


def _finding(employee_id: str, rule_id: str, impact: float, severity: str = "CRITICAL") -> dict:
    return {
        "employee_id": employee_id,
        "employee_name": f"Employee {employee_id}",
        "rule_id": rule_id,
        "rule_name": f"Rule {rule_id}",
        "component": "pf_employee",
        "severity": severity,
        "status": "FAIL",
        "expected_value": "1800",
        "actual_value": "0",
        "difference": "1800",
        "reason": "PF not deducted",
        "suggested_fix": "Deduct PF",
        "financial_impact": impact,
    }


def _record(entity, user, period: date, findings: list[dict]):
    db = SessionLocal()
    try:
        run = finding_store.record_run(
            db,
            entity_id=entity.id,
            user_id=user.id,
            period_month=period,
            findings=findings,
            employee_count=len(findings),
        )
        db.commit()
        return run.id
    finally:
        db.close()


@pytest.fixture()
def recorded(workspace):
    """Three months of the same recurring finding, in a fresh entity."""
    entity, user, headers = workspace
    for month in (date(2025, 4, 1), date(2025, 5, 1), date(2025, 6, 1)):
        _record(entity, user, month, [_finding("1001", "STAT-001", 1800.0)])
    return entity, user, headers


def test_the_same_issue_across_months_is_one_finding(recorded):
    entity, _, _ = recorded
    db = SessionLocal()
    try:
        states = db.query(FindingState).filter(FindingState.entity_id == entity.id).all()
        assert len(states) == 1
        assert states[0].occurrence_count == 3
        assert states[0].first_seen_period == date(2025, 4, 1)
        assert states[0].last_seen_period == date(2025, 6, 1)
    finally:
        db.close()


def test_revalidating_a_month_does_not_inflate_recurrence(recorded):
    """A corrected re-upload must not look like another month of the problem."""
    entity, user, _ = recorded
    _record(entity, user, date(2025, 6, 1), [_finding("1001", "STAT-001", 1800.0)])

    db = SessionLocal()
    try:
        state = db.query(FindingState).filter(FindingState.entity_id == entity.id).one()
        assert state.occurrence_count == 3
    finally:
        db.close()


def test_a_finding_that_stops_appearing_resolves_itself(recorded):
    entity, user, _ = recorded
    _record(entity, user, date(2025, 7, 1), [])

    db = SessionLocal()
    try:
        state = db.query(FindingState).filter(FindingState.entity_id == entity.id).one()
        assert state.state == "resolved"
        assert state.resolved_period == date(2025, 7, 1)
    finally:
        db.close()


def test_a_resolved_finding_that_returns_is_reopened(recorded):
    entity, user, _ = recorded
    _record(entity, user, date(2025, 7, 1), [])
    _record(entity, user, date(2025, 8, 1), [_finding("1001", "STAT-001", 1800.0)])

    db = SessionLocal()
    try:
        state = db.query(FindingState).filter(FindingState.entity_id == entity.id).one()
        assert state.state == "open"
        assert state.resolved_period is None
    finally:
        db.close()


def test_worklist_ranks_recurring_and_costly_findings_first(client, workspace):
    entity, user, h = workspace

    _record(entity, user, date(2025, 4, 1), [_finding("1001", "STAT-001", 500.0)])
    _record(
        entity, user, date(2025, 5, 1),
        [
            _finding("1001", "STAT-001", 500.0),       # recurring
            _finding("2002", "STAT-002", 9000.0),      # new, expensive
            _finding("3003", "MOM-002", 100.0, "WARNING"),
        ],
    )

    rows = client.get("/api/findings", headers=h).json()["data"]
    # Severity first, then recurrence, then money: the recurring CRITICAL leads
    # even though a one-off CRITICAL costs more this month.
    assert [r["rule_id"] for r in rows] == ["STAT-001", "STAT-002", "MOM-002"]
    assert rows[0]["occurrence_count"] == 2


def test_a_waiver_requires_a_reason(client, workspace):
    entity, user, h = workspace
    _record(entity, user, date(2025, 4, 1), [_finding("1001", "STAT-001", 1800.0)])

    fp = client.get("/api/findings", headers=h).json()["data"][0]["fingerprint"]

    r = client.post(f"/api/findings/{fp}/decision", json={"state": "waived"}, headers=h)
    assert r.status_code == 400

    r = client.post(
        f"/api/findings/{fp}/decision",
        json={"state": "waived", "reason": "Employee opted out under PF para 26(6)",
              "waived_until": "2026-03-31"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["data"]["state"] == "waived"


def test_a_waiver_carries_forward_to_later_months(client, workspace):
    """This is the whole point: explain it once, not every month."""
    entity, user, h = workspace

    _record(entity, user, date(2025, 4, 1), [_finding("1001", "STAT-001", 1800.0)])
    fp = client.get("/api/findings", headers=h).json()["data"][0]["fingerprint"]
    client.post(
        f"/api/findings/{fp}/decision",
        json={"state": "waived", "reason": "Accepted by CFO", "waived_until": "2026-03-31"},
        headers=h,
    )

    run_id = _record(entity, user, date(2025, 5, 1), [_finding("1001", "STAT-001", 1800.0)])

    db = SessionLocal()
    try:
        from app.models import FindingRecord, ValidationRun

        record = db.query(FindingRecord).filter(FindingRecord.run_id == run_id).one()
        assert record.was_waived is True

        run = db.get(ValidationRun, run_id)
        # Off the worklist, but still counted as exposure — an accepted risk is
        # still a risk.
        assert float(run.open_financial_impact) == 0.0
        assert float(run.total_financial_impact) == 1800.0
    finally:
        db.close()


def test_an_expired_waiver_stops_suppressing(client, workspace):
    entity, user, h = workspace

    _record(entity, user, date(2025, 4, 1), [_finding("1001", "STAT-001", 1800.0)])
    fp = client.get("/api/findings", headers=h).json()["data"][0]["fingerprint"]
    client.post(
        f"/api/findings/{fp}/decision",
        json={"state": "waived", "reason": "Accepted for this financial year",
              "waived_until": "2025-05-31"},
        headers=h,
    )

    run_id = _record(entity, user, date(2025, 6, 1), [_finding("1001", "STAT-001", 1800.0)])

    db = SessionLocal()
    try:
        from app.models import ValidationRun

        run = db.get(ValidationRun, run_id)
        assert float(run.open_financial_impact) == 1800.0
    finally:
        db.close()


def test_every_decision_is_recorded_in_the_audit_trail(client, workspace):
    entity, user, h = workspace
    _record(entity, user, date(2025, 4, 1), [_finding("1001", "STAT-001", 1800.0)])

    fp = client.get("/api/findings", headers=h).json()["data"][0]["fingerprint"]
    client.post(f"/api/findings/{fp}/decision",
                json={"state": "acknowledged", "note": "Checking with the vendor"}, headers=h)
    client.post(f"/api/findings/{fp}/decision",
                json={"state": "waived", "reason": "Confirmed correct at source"}, headers=h)

    detail = client.get(f"/api/findings/{fp}", headers=h).json()["data"]
    transitions = [(e["from_state"], e["to_state"]) for e in detail["history"]]

    assert ("open", "acknowledged") in transitions
    assert ("acknowledged", "waived") in transitions
    assert any(e["actor_email"] == user.email for e in detail["history"])


def test_summary_reports_waived_exposure_separately(client, workspace):
    entity, user, h = workspace

    _record(
        entity, user, date(2025, 4, 1),
        [_finding("1001", "STAT-001", 1800.0), _finding("2002", "STAT-002", 2200.0)],
    )
    fp = [
        r["fingerprint"]
        for r in client.get("/api/findings", headers=h).json()["data"]
        if r["employee_id"] == "1001"
    ][0]
    client.post(f"/api/findings/{fp}/decision",
                json={"state": "waived", "reason": "Accepted"}, headers=h)

    summary = client.get("/api/findings/summary", headers=h).json()["data"]
    assert summary["open_exposure"] == 2200.0
    assert summary["waived_exposure"] == 1800.0  # visible, not netted away


def test_findings_do_not_leak_between_entities(client, workspace):
    entity, user, h = workspace
    _record(entity, user, date(2025, 4, 1), [_finding("1001", "STAT-001", 1800.0)])

    other = client.post(
        "/api/org/entities", json={"name": "Other Client"}, headers=h
    ).json()["data"]["id"]

    assert client.get("/api/findings", headers=h).json()["data"]
    assert client.get("/api/findings", headers={**h, "X-Entity-Id": other}).json()["data"] == []
