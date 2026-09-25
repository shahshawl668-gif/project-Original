"""The worker must validate the same thing the endpoint does.

A background worker reads the *stored* register rather than a posted payload.
That is only safe if the two produce identical findings — otherwise moving
validation off the request path quietly changes what the product reports, which
is the worst possible way to ship a performance improvement.

So this does not test the reconstruction field by field. It uploads a register
through the real endpoint, validates it twice — once from the payload the
browser sent, once from the rows that were stored — and compares the findings.
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import date

import pytest

from app.database import SessionLocal
from app.models.register import SalaryRegister
from app.models.component import ComponentConfig
from app.models.register import SalaryRegisterRow
from app.services.register_rows import load_employees, row_to_employee

PASSWORD = "Passw0rd!x"
PERIOD = date(2026, 6, 1)

COMPONENTS = [
    {"component_name": "Basic", "pf_applicable": True, "esic_applicable": True,
     "pt_applicable": True, "lwf_applicable": True, "included_in_wages": True, "taxable": True},
    {"component_name": "HRA", "esic_applicable": True, "pt_applicable": True, "taxable": True},
    {"component_name": "Special Allowance", "pf_applicable": True, "esic_applicable": True,
     "pt_applicable": True, "taxable": True},
]

#: Deliberately rich: arrears, an increment arrear, attendance, dimensions,
#: stated statutory amounts, a PF flag and a net pay. Every branch of the
#: reconstruction is exercised by at least one column here.
REGISTER_CSV = """employee_id,employee_name,basic,hra,special_allowance,basic_arrear,increment_arrear,paid_days,lop_days,state,department,employment_type,gender,pf_employee,pf_employer,esic_employee,esic_employer,pt,lwf_employee,tds,pf_restricted,net_pay
E001,Asha Rao,30000,12000,8000,0,0,30,0,Karnataka,Engineering,permanent,F,1800,1800,0,0,200,0,2500,TRUE,43700
E002,Bharat Singh,18000,7000,3000,1500,900,28,2,Maharashtra,Operations,permanent,M,2160,2160,210,884,200,12,0,FALSE,24018
E003,Chitra Menon,12000,4000,2000,0,0,30,0,Tamil Nadu,Sales,contract,F,1440,1440,135,569,0,0,0,TRUE,15985
"""


@pytest.fixture()
def uploaded(client, request):
    """A signed-up entity with components configured and one register stored."""
    email = f"rr-{request.node.name[:36]}@rows-example.com".replace("_", "-")
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": PASSWORD, "company_name": "Rows Tests"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    entity_id = client.post("/api/org/entities",
                            json={"name": f"RR-{request.node.name[:24]}",
                                  "primary_state": "Karnataka"},
                            headers=headers).json()["data"]["id"]
    headers["X-Entity-Id"] = entity_id

    for comp in COMPONENTS:
        client.post("/api/components", json=comp, headers=headers)

    response = client.post(
        "/api/payroll/upload",
        files={"file": ("register.csv", io.BytesIO(REGISTER_CSV.encode()), "text/csv")},
        data={"meta": json.dumps({"period_month": PERIOD.isoformat()})},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    posted = response.json()["data"]["employees"]

    db = SessionLocal()
    try:
        # Scoped to this entity: the suite runs other tests that store a June
        # 2026 register, and picking "the newest one" would grab theirs.
        register = (
            db.query(SalaryRegister)
            .filter(
                SalaryRegister.entity_id == uuid.UUID(entity_id),
                SalaryRegister.period_month == PERIOD,
            )
            .one()
        )
        register_id = register.id
    finally:
        db.close()

    return headers, register_id, posted


def _comp_map(db, headers) -> dict:
    """The entity's components, keyed the way the rule engine keys them."""
    import uuid as _uuid

    from app.routers.payroll import _component_key_map

    comps = (
        db.query(ComponentConfig)
        .filter(ComponentConfig.entity_id == _uuid.UUID(headers["X-Entity-Id"]))
        .all()
    )
    return _component_key_map(comps)


def _findings(client, headers, employees) -> list[tuple]:
    """Validate and reduce to a comparable shape: who, which rule, how much."""
    response = client.post(
        "/api/payroll/validate",
        json={"employees": employees, "period_month": PERIOD.isoformat()},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    out = []
    for finding in data["findings"]:
        out.append((
            finding.get("employee_id"),
            finding.get("rule_id") or finding.get("code"),
            finding.get("severity"),
            round(float(finding.get("financial_impact") or 0), 2),
        ))
    return sorted(out, key=lambda t: tuple("" if v is None else str(v) for v in t))


def test_validating_the_stored_rows_finds_what_the_posted_payload_finds(client, uploaded):
    """The whole point. If these diverge, the worker reports something else."""
    headers, register_id, posted = uploaded

    from_payload = _findings(client, headers, posted)

    db = SessionLocal()
    try:
        rebuilt = load_employees(db, register_id, _comp_map(db, headers))
    finally:
        db.close()

    from_storage = _findings(client, headers, rebuilt)

    assert from_storage == from_payload, (
        "validating the stored register found different things from validating "
        "the posted payload — the reconstruction is lossy.\n"
        f"only in payload: {sorted(set(from_payload) - set(from_storage))}\n"
        f"only in storage: {sorted(set(from_storage) - set(from_payload))}"
    )
    assert from_payload, "the fixture register should produce findings to compare"


def test_every_employee_survives_the_round_trip(client, uploaded):
    _, register_id, posted = uploaded
    db = SessionLocal()
    try:
        rebuilt = load_employees(db, register_id)
    finally:
        db.close()
    assert {e["employee_id"] for e in rebuilt} == {str(e["employee_id"]) for e in posted}


def test_an_unassigned_dimension_is_absent_rather_than_the_word_unassigned(client, uploaded):
    """`Unassigned` is how a breakdown shows a gap, not a value to validate against.

    Handed back as `work_state` it would send the PT lookup hunting for a state
    of that name instead of reporting that it could not tell.
    """
    _, register_id, _ = uploaded
    db = SessionLocal()
    try:
        rebuilt = load_employees(db, register_id)
    finally:
        db.close()
    for employee in rebuilt:
        assert "Unassigned" not in employee.values(), employee


def test_a_register_that_never_mentioned_esi_does_not_come_back_deducting_zero(client, uploaded):
    """Absent and zero are different claims, and conflating them hides a finding."""
    _, register_id, _ = uploaded
    db = SessionLocal()
    try:
        row = (
            db.query(SalaryRegisterRow)
            .filter(SalaryRegisterRow.register_id == register_id)
            .order_by(SalaryRegisterRow.employee_id)
            .first()
        )
        row.deductions = {k: v for k, v in (row.deductions or {}).items()
                          if not k.endswith("esi")}
        db.flush()
        rebuilt = row_to_employee(row)
        db.rollback()
    finally:
        db.close()
    assert "esic_employee" not in rebuilt
    assert "esic_employer" not in rebuilt
