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


def test_grouped_conditions_are_scoped_and_missing_inputs_are_reported(client):
    headers = owner(client, "matrix-grouped")
    body = rule_body("CUST-GROUP-01")
    body["conditions"] = [
        {"left": {"source": "field", "key": "department"}, "operator": "eq",
         "right": {"source": "literal", "value": "Stores"}, "tolerance": "0"},
        {"left": {"source": "field", "key": "paid_days"}, "operator": "gte",
         "right": {"source": "literal", "value": "20"}, "tolerance": "0"},
    ]
    body["condition_mode"] = "all"
    draft = data(client.post("/api/validation-matrix", headers=headers, json=body))
    from app.models import ValidationRuleVersion
    db = SessionLocal()
    try:
        rule = db.get(ValidationRuleVersion, uuid.UUID(draft["id"]))
        assert validation_matrix.evaluate(rule, {"employee_id": "E1", "department": "Office", "lop_days": 3}) is None
        missing = validation_matrix.evaluate(rule, {"employee_id": "E1", "department": "Stores", "lop_days": 3})
        assert missing["evidence"]["unverifiable"] is True
        failed = validation_matrix.evaluate(rule, {"employee_id": "E1", "department": "Stores", "paid_days": 24, "lop_days": 3})
        assert failed["rule_version_id"] == draft["id"]
        rule.condition["mode"] = "any"
        assert validation_matrix.evaluate(rule, {"employee_id": "E1", "department": "Stores", "lop_days": 3})["evidence"]["unverifiable"] is False
    finally:
        db.close()


def test_prefilled_catalog_and_company_rule_toggle(client):
    headers = owner(client, "matrix-catalog")
    catalog = data(client.get("/api/validation-matrix/catalog", headers=headers))
    indexed = {item["rule_id"]: item for item in catalog["built_in_rules"]}
    assert indexed["AGG-002"]["name"] == "Net Pay Mismatch"
    assert indexed["STAT-001"]["family"] == "Statutory and wage"
    assert indexed["ATT-001"]["family"] == "Attendance and LOP"
    assert data(client.put("/api/rule-preferences", headers=headers, json={
        "rule_id": "AGG-002", "suppressed": True,
    }))["suppressed"] is True
    preferences = data(client.get("/api/rule-preferences", headers=headers))
    assert {"rule_id": "AGG-002", "suppressed": True} in preferences
    from app.services.validation import apply_suppressed_rules
    results = [{"employee_id": "E1", "findings": [
        {"rule_id": "AGG-002", "status": "FAIL", "severity": "CRITICAL"},
        {"rule_id": "DATA-004", "status": "FAIL", "severity": "WARNING"},
    ]}]
    summary = apply_suppressed_rules(results, {"AGG-002"})
    assert [item["rule_id"] for item in results[0]["findings"]] == ["DATA-004"]
    assert summary["total_findings"] == 1


def test_required_field_and_approved_list_operators(client):
    headers = owner(client, "matrix-required")
    body = rule_body("CUST-STATE-01")
    body["assertion"] = {
        "left": {"source": "field", "key": "location_state"}, "operator": "present",
        "right": {"source": "literal", "value": "1"}, "tolerance": "0",
    }
    draft = data(client.post("/api/validation-matrix", headers=headers, json=body))
    from app.models import ValidationRuleVersion
    db = SessionLocal()
    try:
        rule = db.get(ValidationRuleVersion, uuid.UUID(draft["id"]))
        missing = validation_matrix.evaluate(rule, {"employee_id": "E1", "location_state": ""})
        assert missing["evidence"]["unverifiable"] is True
        assert validation_matrix.evaluate(rule, {"employee_id": "E1", "location_state": "Maharashtra"}) is None
    finally:
        db.close()
    body = rule_body("CUST-TYPE-01")
    body["assertion"] = {
        "left": {"source": "field", "key": "employment_type"}, "operator": "in",
        "right": {"source": "literal", "value": "Permanent|Contract"}, "tolerance": "0",
    }
    draft = data(client.post("/api/validation-matrix", headers=headers, json=body))
    db = SessionLocal()
    try:
        rule = db.get(ValidationRuleVersion, uuid.UUID(draft["id"]))
        assert validation_matrix.evaluate(rule, {"employee_id": "E1", "employment_type": "contract"}) is None
        assert validation_matrix.evaluate(rule, {"employee_id": "E1", "employment_type": "Intern"})["status"] == "FAIL"
    finally:
        db.close()


def test_maharashtra_lwf_is_due_in_june_and_december(client):
    headers = owner(client, "lwf-timing")
    entity = data(client.get("/api/org/context", headers=headers))["active_entity"]
    response = client.post(
        "/api/rule-engine/slabs/import-defaults?state=Maharashtra&rule_type=LWF",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    db = SessionLocal()
    try:
        from app.services.validation import lookup_lwf
        entity_id = uuid.UUID(entity["id"])
        for month, expected in ((5, Decimal("0")), (6, Decimal("25")), (7, Decimal("0")), (12, Decimal("25"))):
            period, employer, due, employer_due = lookup_lwf(
                db, "Maharashtra", Decimal("20000"), date(2026, month, 1), entity_id=entity_id,
            )
            assert (period, employer) == (Decimal("25"), Decimal("75"))
            assert (due, employer_due) == (expected, expected * 3)
    finally:
        db.close()
