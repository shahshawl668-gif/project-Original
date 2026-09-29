"""
BI accuracy: the figures describe the register they claim to.

* An arrears run uploaded for June is not June's register. It used to replace
  it, so June's cost in every report collapsed to the arrears alone and the
  month looked "changed" after its validation.
"""
from __future__ import annotations

import io
import json
import uuid

from app.database import SessionLocal
from app.models import SalaryRegister, SalaryRegisterRow
from tests.test_coverage import BASE_ROWS, _register, _run
from tests.test_run_history import PERIOD, _company, _data, _empty_queue  # noqa: F401


def test_an_arrears_run_does_not_replace_the_months_register(client):
    headers = _company(client, "bi-arr")
    run_id = _run(client, headers, _register(BASE_ROWS))
    arrears = "employee_id,employee_name,basic_arrear\nE001,Person E001,5000\n"
    r = client.post("/api/payroll/upload", headers=headers,
                    files={"file": ("arrears.csv", io.BytesIO(arrears.encode()), "text/csv")},
                    data={"meta": json.dumps({"period_month": PERIOD, "run_type": "arrear",
                                              "effective_month_from": "2026-04-01", "effective_month_to": "2026-05-01",
                                              "strict_header_check": False, "return_employees": False})})
    assert r.status_code == 200, r.text
    assert any("not added" in w for w in r.json()["data"].get("warnings", []))
    db = SessionLocal()
    try:
        entity_id = uuid.UUID(headers["X-Entity-Id"])
        register = db.query(SalaryRegister).filter(SalaryRegister.entity_id == entity_id).one()
        employees = {row.employee_id for row in db.query(SalaryRegisterRow).filter(
            SalaryRegisterRow.register_id == register.id)}
        assert employees == {"E001", "E002", "E003"}
    finally:
        db.close()
    # June's run is still current for June's register.
    status = _data(client.get(f"/api/validation/periods/{PERIOD}/status", headers=headers))
    assert status["upload"]["run_type"] == "regular"
    assert status["current_run"]["id"] == run_id
    assert status["freshness"]["revalidation_required"] is False
    analysis = _data(client.get("/api/bi/cost-analysis?group_by=department", headers=headers))
    assert analysis["totals"]["headcount"] == 3
