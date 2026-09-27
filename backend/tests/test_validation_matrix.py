"""Decision matrix contract: scope, approval, date selection and auditable findings."""
from datetime import date
import uuid
from decimal import Decimal

from app.database import SessionLocal
from app.models import FindingRecord, SalaryRegister, SalaryRegisterRow
from app.services import finding_store, validation_matrix

PASSWORD = "Passw0rd!x"


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def owner(client, name):
    response = client.post("/api/auth/signup", json={
        "email": f"{name}@matrix-example.com", "password": PASSWORD, "company_name": name,
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def rule_body(key="CUST-LOP-01", category="custom", effective="2026-08-01"):
    return {
        "rule_key": key, "name": "LOP within policy limit", "category": category,
        "effective_from": effective, "source_reference": "Official notification URL" if category == "statutory" else "HR policy 2026",
        "change_reason": "New approved company payroll policy",
        "assertion": {
            "left": {"source": "field", "key": "lop_days"},
            "operator": "lte", "right": {"source": "literal", "value": "2"},
            "tolerance": "0",
        },
        "severity": "WARNING", "blocks_signoff": True,
    }


def test_draft_simulation_publish_and_version_date_selection(client):
    headers = owner(client, "matrix-owner")
    entity = data(client.get("/api/org/context", headers=headers))["active_entity"]
    draft = data(client.post("/api/validation-matrix", headers=headers, json=rule_body()))
    assert draft["status"] == "draft"
    db = SessionLocal()
    try:
        register = SalaryRegister(
            entity_id=uuid.UUID(entity["id"]), user_id=uuid.UUID(draft["created_by"]),
            period_month=date(2026, 8, 1), employee_count=1,
        )
        db.add(register)
        db.flush()
        db.add(SalaryRegisterRow(
            register_id=register.id, entity_id=uuid.UUID(entity["id"]), user_id=uuid.UUID(draft["created_by"]),
            period_month=date(2026, 8, 1), employee_id="E01", employee_name="Test",
            lop_days=Decimal("3"), components={"Basic": 10000}, dimensions={},
            arrears={}, deductions={}, net_pay=Decimal("10000"),
        ))
        db.commit()
    finally:
        db.close()
    simulation = data(client.post(
        f"/api/validation-matrix/{draft['id']}/simulate", headers=headers,
        json={"period_month": "2026-08-01"},
    ))
    assert simulation["sampled"] == 1
    assert simulation["findings"][0]["rule_version_id"] == draft["id"]
    assert simulation["findings"][0]["severity"] == "CRITICAL"
    assert data(client.post(f"/api/validation-matrix/{draft['id']}/submit", headers=headers))["status"] == "pending"
    assert data(client.post(f"/api/validation-matrix/{draft['id']}/publish", headers=headers))["status"] == "published"
    db = SessionLocal()
    try:
        assert validation_matrix.published_for(db, uuid.UUID(entity["id"]), date(2026, 7, 1)) == []
        selected = validation_matrix.published_for(db, uuid.UUID(entity["id"]), date(2026, 8, 1))
        assert [str(row.id) for row in selected] == [draft["id"]]
        issue = validation_matrix.evaluate(
            selected[0], {"employee_id": "E01", "lop_days": Decimal("3")}
        )
        run = finding_store.record_run(
            db, entity_id=uuid.UUID(entity["id"]),
            user_id=uuid.UUID(draft["created_by"]),
            period_month=date(2026, 8, 1), findings=[issue],
            employee_count=1,
        )
        db.commit()
        stored = db.query(FindingRecord).filter(FindingRecord.run_id == run.id).one()
        assert str(stored.rule_version_id) == draft["id"]
        assert stored.evidence["source_reference"] == "HR policy 2026"
    finally:
        db.close()
    data(client.post("/api/signoff/submit", headers=headers, json={"period_month": "2026-08-01"}))
    blocked = client.post("/api/signoff/sign", headers=headers, json={"period_month": "2026-08-01"})
    assert blocked.status_code == 409
    assert "blocking matrix" in blocked.json()["error"]["detail"]
    assert client.post(f"/api/validation-matrix/{draft['id']}/publish", headers=headers).status_code == 409
    new = data(client.post("/api/validation-matrix", headers=headers, json=rule_body(effective="2026-09-01")))
    assert new["version"] == 2
    db = SessionLocal()
    try:
        assert validation_matrix.published_for(db, uuid.UUID(entity["id"]), date(2026, 9, 1))[0].version == 1
    finally:
        db.close()


def test_statutory_publication_requires_group_owner(client):
    headers = owner(client, "matrix-statutory")
    draft = data(client.post("/api/validation-matrix", headers=headers,
                             json=rule_body("STATX-LOP-01", "statutory")))
    data(client.post(f"/api/validation-matrix/{draft['id']}/submit", headers=headers))
    manager_invite = data(client.post("/api/org/invitations", headers=headers, json={
        "email": "matrix-manager@matrix-example.com", "role": "manager",
    }))
    joined = data(client.post("/api/org/invitations/register", json={
        "token": manager_invite["token"], "password": PASSWORD,
    }))
    manager = {"Authorization": f"Bearer {joined['access_token']}"}
    assert client.post(f"/api/validation-matrix/{draft['id']}/publish", headers=manager).status_code == 403
    assert data(client.post(f"/api/validation-matrix/{draft['id']}/publish", headers=headers))["status"] == "published"


def test_missing_inputs_and_unknown_component_are_not_silent_passes(client):
    headers = owner(client, "matrix-missing")
    body = rule_body("CUST-BASIC-01")
    body["assertion"]["left"] = {"source": "component", "key": "Basic"}
    assert client.post("/api/validation-matrix", headers=headers, json=body).status_code == 400
    assert client.post("/api/components", headers=headers, json={
        "component_name": "Basic", "pf_applicable": True, "taxable": True,
    }).status_code == 201
    draft = data(client.post("/api/validation-matrix", headers=headers, json=body))
    db = SessionLocal()
    try:
        from app.models import ValidationRuleVersion
        row = db.get(ValidationRuleVersion, uuid.UUID(draft["id"]))
        issue = validation_matrix.evaluate(row, {"employee_id": "E02", "components": {}})
        assert issue["evidence"]["unverifiable"] is True
        assert issue["status"] == "FAIL"
    finally:
        db.close()
