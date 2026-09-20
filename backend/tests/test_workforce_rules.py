"""
Register-versus-inputs checks.

These are the rules that see what internal consistency cannot: an employee paid
before they joined, or months after they left, is arithmetically perfect on the
register itself.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import (
    AttendanceRegister,
    AttendanceRow,
    EmployeeMasterUpload,
    EmployeeRecord,
    Entity,
    User,
)
from app.services.workforce_rules import check_against_inputs

PASSWORD = "Passw0rd!x"
PERIOD = date(2025, 4, 1)


def _signup(client, email: str) -> dict:
    r = client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "company_name": "Rules Tests"},
    )
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@rules-example.com".replace("_", "-")
    headers = _signup(client, email)
    entity_id = client.post(
        "/api/org/entities", json={"name": f"E-{request.node.name[:26]}"}, headers=headers
    ).json()["data"]["id"]
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        entity = db.get(Entity, uuid.UUID(entity_id))
        db.expunge_all()
    finally:
        db.close()
    return entity, user


def _master(entity, user, records: list[dict]) -> None:
    db = SessionLocal()
    try:
        upload = EmployeeMasterUpload(
            user_id=user.id, entity_id=entity.id,
            effective_from=PERIOD, filename="m.csv", employee_count=len(records),
        )
        db.add(upload)
        db.flush()
        for record in records:
            db.add(
                EmployeeRecord(
                    upload_id=upload.id, user_id=user.id, entity_id=entity.id,
                    employee_id=record["employee_id"], effective_from=PERIOD,
                    employee_name=record.get("employee_name"),
                    date_of_joining=record.get("date_of_joining"),
                    date_of_exit=record.get("date_of_exit"),
                    uan=record.get("uan"),
                    esic_ip_number=record.get("esic_ip_number"),
                    extra={},
                )
            )
        db.commit()
    finally:
        db.close()


def _attendance(entity, user, rows: list[dict]) -> None:
    db = SessionLocal()
    try:
        register = AttendanceRegister(
            user_id=user.id, entity_id=entity.id,
            period_month=PERIOD, filename="a.csv", employee_count=len(rows),
        )
        db.add(register)
        db.flush()
        for row in rows:
            db.add(
                AttendanceRow(
                    register_id=register.id, user_id=user.id, entity_id=entity.id,
                    period_month=PERIOD, employee_id=row["employee_id"],
                    calendar_days=Decimal(str(row.get("calendar_days", 30))),
                    paid_days=Decimal(str(row["paid_days"])) if "paid_days" in row else None,
                    lop_days=Decimal(str(row["lop_days"])) if "lop_days" in row else None,
                    extra={},
                )
            )
        db.commit()
    finally:
        db.close()


def _check(entity, rows: list[dict]) -> dict:
    db = SessionLocal()
    try:
        return check_against_inputs(db, entity.id, period_month=PERIOD, rows=rows)
    finally:
        db.close()


def _rule_ids(findings: dict, employee_id: str) -> list[str]:
    return [f["rule_id"] for f in findings.get(employee_id, [])]


def test_paid_after_exit_is_caught(workspace):
    """The register itself is perfectly consistent; only the master reveals this."""
    entity, user = workspace
    _master(entity, user, [
        {"employee_id": "1001", "date_of_joining": date(2020, 1, 1), "date_of_exit": date(2025, 1, 31)},
    ])

    findings = _check(entity, [{"employee_id": "1001", "gross": 45000}])
    assert "MST-003" in _rule_ids(findings, "1001")

    finding = next(f for f in findings["1001"] if f["rule_id"] == "MST-003")
    assert finding["severity"] == "CRITICAL"
    assert finding["financial_impact"] == 45000.0


def test_an_exit_inside_the_period_is_not_flagged(workspace):
    """Someone who left mid-month is legitimately on that month's register."""
    entity, user = workspace
    _master(entity, user, [
        {"employee_id": "1001", "date_of_joining": date(2020, 1, 1), "date_of_exit": date(2025, 4, 20)},
    ])

    findings = _check(entity, [{"employee_id": "1001", "gross": 45000}])
    assert "MST-003" not in _rule_ids(findings, "1001")


def test_paid_before_joining_is_caught(workspace):
    entity, user = workspace
    _master(entity, user, [{"employee_id": "1001", "date_of_joining": date(2025, 6, 1)}])

    findings = _check(entity, [{"employee_id": "1001", "gross": 30000}])
    assert "MST-002" in _rule_ids(findings, "1001")


def test_an_employee_missing_from_the_master_is_flagged(workspace):
    entity, user = workspace
    _master(entity, user, [{"employee_id": "1001", "date_of_joining": date(2020, 1, 1)}])

    findings = _check(entity, [
        {"employee_id": "1001", "gross": 30000},
        {"employee_id": "9999", "gross": 55000},
    ])
    assert _rule_ids(findings, "1001") == []
    assert "MST-001" in _rule_ids(findings, "9999")


def test_pf_without_a_uan_blocks_the_filing(workspace):
    entity, user = workspace
    _master(entity, user, [{"employee_id": "1001", "date_of_joining": date(2020, 1, 1)}])

    findings = _check(entity, [{"employee_id": "1001", "gross": 30000, "pf_employee": 1800}])
    assert "MST-004" in _rule_ids(findings, "1001")


def test_identifiers_are_only_required_where_a_deduction_implies_one(workspace):
    entity, user = workspace
    _master(entity, user, [{"employee_id": "1001", "date_of_joining": date(2020, 1, 1)}])

    findings = _check(entity, [{"employee_id": "1001", "gross": 30000, "pf_employee": 0}])
    assert "MST-004" not in _rule_ids(findings, "1001")
    assert "MST-005" not in _rule_ids(findings, "1001")


def test_paid_days_disagreeing_with_attendance_is_valued(workspace):
    entity, user = workspace
    _attendance(entity, user, [{"employee_id": "1001", "paid_days": 27, "lop_days": 3}])

    findings = _check(entity, [
        {"employee_id": "1001", "gross": 30000, "paid_days": 30, "lop_days": 0},
    ])
    ids = _rule_ids(findings, "1001")
    assert "ATT-001" in ids
    assert "ATT-002" in ids

    att = next(f for f in findings["1001"] if f["rule_id"] == "ATT-001")
    # Three days at the employee's own daily rate of 1,000.
    assert att["financial_impact"] == 3000.0


def test_half_day_rounding_is_not_a_discrepancy(workspace):
    entity, user = workspace
    _attendance(entity, user, [{"employee_id": "1001", "paid_days": 27.0}])

    findings = _check(entity, [{"employee_id": "1001", "gross": 27000, "paid_days": 27.01}])
    assert "ATT-001" not in _rule_ids(findings, "1001")


def test_more_paid_days_than_the_month_holds(workspace):
    entity, user = workspace
    _attendance(entity, user, [{"employee_id": "1001", "paid_days": 31, "calendar_days": 30}])

    findings = _check(entity, [{"employee_id": "1001", "gross": 31000, "paid_days": 31}])
    assert "ATT-004" in _rule_ids(findings, "1001")


def test_an_employee_absent_from_attendance_is_flagged(workspace):
    entity, user = workspace
    _attendance(entity, user, [{"employee_id": "1001", "paid_days": 30}])

    findings = _check(entity, [
        {"employee_id": "1001", "gross": 30000, "paid_days": 30},
        {"employee_id": "2002", "gross": 20000, "paid_days": 30},
    ])
    assert "ATT-003" in _rule_ids(findings, "2002")


def test_rules_stay_silent_when_their_input_was_never_uploaded(workspace):
    """A client without attendance gets silence, not a screenful of false positives."""
    entity, user = workspace

    findings = _check(entity, [{"employee_id": "1001", "gross": 30000, "paid_days": 30}])
    assert findings == {}


def test_gratuity_below_the_service_threshold_is_flagged(workspace):
    entity, user = workspace
    _master(entity, user, [
        {"employee_id": "1001", "date_of_joining": date(2023, 1, 1), "date_of_exit": date(2025, 4, 30)},
    ])

    findings = _check(entity, [{"employee_id": "1001", "gross": 50000, "gratuity": 40000}])
    assert "GRAT-005" in _rule_ids(findings, "1001")


def test_gratuity_with_enough_service_passes(workspace):
    entity, user = workspace
    _master(entity, user, [
        {"employee_id": "1001", "date_of_joining": date(2015, 1, 1), "date_of_exit": date(2025, 4, 30)},
    ])

    findings = _check(entity, [{"employee_id": "1001", "gross": 50000, "gratuity": 40000}])
    assert "GRAT-005" not in _rule_ids(findings, "1001")


def test_gratuity_without_a_joining_date_says_it_cannot_tell(workspace):
    """"Not eligible" and "cannot say" must not look the same when money moves."""
    entity, user = workspace
    _master(entity, user, [{"employee_id": "1001", "date_of_joining": None}])

    findings = _check(entity, [{"employee_id": "1001", "gross": 50000, "gratuity": 40000}])
    finding = next(f for f in findings["1001"] if f["rule_id"] == "GRAT-004")
    assert finding["severity"] == "INFO"
