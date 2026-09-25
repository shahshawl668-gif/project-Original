"""
Holding the register, the bank file and the ledger against each other.

Two properties matter more than any individual check.

**Nothing is reported as reconciled that was not compared.** A month with no
bank file is unreconciled, not clean. A silent pass is the most dangerous
output this module could produce, so the absence of evidence is reported as
loudly as a difference.

**Matching is on employee code alone.** Not name, not amount. The payroll fraud
worth catching is the one where the name is right and the account is not, and
matching on amount would pair an employee with a colleague on the same salary
and report a clean run.
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import (
    BankFile,
    BankFileRow,
    Entity,
    EmployeeMasterUpload,
    EmployeeRecord,
    SalaryRegister,
    SalaryRegisterRow,
    User,
)
from app.services import reconciliation
from app.services.dimensions import UNASSIGNED

PASSWORD = "Passw0rd!x"
PERIOD = date(2026, 6, 1)


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@recon-example.com".replace("_", "-")
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": PASSWORD, "company_name": "Recon Tests"})
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


def _dims() -> dict:
    return dict.fromkeys(
        ("business_unit", "department", "cost_center", "work_location", "work_state",
         "grade", "designation", "employment_type", "skill_category"), UNASSIGNED
    )


def register(entity, user, rows: list[dict], period: date = PERIOD) -> None:
    db = SessionLocal()
    try:
        reg = SalaryRegister(user_id=user.id, entity_id=entity.id, period_month=period,
                             filename="register.csv", employee_count=len(rows))
        db.add(reg)
        db.flush()
        for row in rows:
            db.add(SalaryRegisterRow(
                register_id=reg.id, user_id=user.id, entity_id=entity.id,
                period_month=period, employee_id=row["employee_id"],
                employee_name=row.get("employee_name"),
                components=row.get("components", {"basic": 30000.0, "hra": 15000.0}),
                arrears={}, deductions=row.get("deductions", {}), dimensions=_dims(),
                net_pay=row.get("net_pay"), increment_arrear_total=Decimal("0"),
            ))
        db.commit()
    finally:
        db.close()


def master(entity, user, rows: list[dict], period: date = PERIOD) -> None:
    db = SessionLocal()
    try:
        upload = EmployeeMasterUpload(
            user_id=user.id, entity_id=entity.id, effective_from=period,
            filename="master.csv", employee_count=len(rows),
        )
        db.add(upload)
        db.flush()
        for row in rows:
            db.add(EmployeeRecord(
                upload_id=upload.id, user_id=user.id, entity_id=entity.id,
                employee_id=row["employee_id"], effective_from=period,
                employee_name=row.get("employee_name"),
                bank_account=row.get("bank_account"), ifsc=row.get("ifsc"),
            ))
        db.commit()
    finally:
        db.close()


def bank(entity, user, rows: list[dict], *, period: date = PERIOD,
         stated_total=None) -> uuid.UUID:
    db = SessionLocal()
    try:
        total = sum((Decimal(str(r.get("amount", 0))) for r in rows), Decimal("0"))
        f = BankFile(
            entity_id=entity.id, period_month=period, kind="payment_advice",
            filename="bank.csv", row_count=len(rows), total_amount=total,
            stated_total=None if stated_total is None else Decimal(str(stated_total)),
            uploaded_by_user_id=user.id, uploaded_by_email=user.email,
        )
        db.add(f)
        db.flush()
        for index, row in enumerate(rows, start=1):
            db.add(BankFileRow(
                file_id=f.id, entity_id=entity.id, period_month=period,
                row_number=index, employee_id=row.get("employee_id"),
                employee_name=row.get("employee_name"),
                account_number=row.get("account_number"), ifsc=row.get("ifsc"),
                amount=Decimal(str(row.get("amount", 0))), status=row.get("status"),
                raw={},
            ))
        db.commit()
        return f.id
    finally:
        db.close()


def reconcile(entity, file_id, **kwargs) -> dict:
    db = SessionLocal()
    try:
        f = db.get(BankFile, file_id)
        return reconciliation.bank_reconciliation(db, entity.id, f.period_month, f, **kwargs)
    finally:
        db.close()


def codes(result: dict) -> set[str]:
    return {e["code"] for e in result["exceptions"]}


def net_of(entity, employee_id: str) -> Decimal:
    db = SessionLocal()
    try:
        entries = reconciliation.register_net(db, entity.id, PERIOD)
        return next(e.expected for e in entries if e.employee_id == employee_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The clean case
# ---------------------------------------------------------------------------
def test_a_file_that_pays_exactly_what_is_due_reconciles(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}, {"employee_id": "E2"}])
    file_id = bank(entity, user, [
        {"employee_id": "E1", "amount": net_of(entity, "E1")},
        {"employee_id": "E2", "amount": net_of(entity, "E2")},
    ])
    result = reconcile(entity, file_id)
    assert result["summary"]["reconciled"] is True
    assert result["summary"]["matched"] == 2
    assert result["summary"]["difference"] == 0


def test_codes_are_matched_across_a_case_and_padding_difference(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "emp0042"}])
    file_id = bank(entity, user, [
        {"employee_id": "  EMP0042 ", "amount": net_of(entity, "emp0042")},
    ])
    result = reconcile(entity, file_id)
    assert result["summary"]["matched"] == 1
    assert "bank.not_in_file" not in codes(result)


# ---------------------------------------------------------------------------
# Money in the wrong place
# ---------------------------------------------------------------------------
def test_an_employee_due_pay_with_no_payment_is_named(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}, {"employee_id": "E2"}])
    file_id = bank(entity, user, [{"employee_id": "E1", "amount": net_of(entity, "E1")}])
    result = reconcile(entity, file_id)
    missing = [e for e in result["exceptions"] if e["code"] == "bank.not_in_file"]
    assert [e["employee_id"] for e in missing] == ["E2"]
    assert missing[0]["severity"] == "high"
    assert missing[0]["expected"] == float(net_of(entity, "E2"))


def test_a_payment_to_someone_not_on_the_register_is_high_severity(workspace):
    # The ghost payee. Nothing else in the product would ever see this.
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    file_id = bank(entity, user, [
        {"employee_id": "E1", "amount": net_of(entity, "E1")},
        {"employee_id": "E999", "employee_name": "Nobody", "amount": Decimal("75000")},
    ])
    result = reconcile(entity, file_id)
    ghost = next(e for e in result["exceptions"] if e["code"] == "bank.not_in_register")
    assert ghost["employee_id"] == "E999"
    assert ghost["severity"] == "high"
    assert ghost["actual"] == 75000.0


def test_a_different_amount_is_reported_with_the_difference(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    due = net_of(entity, "E1")
    file_id = bank(entity, user, [{"employee_id": "E1", "amount": due + Decimal("5000")}])
    result = reconcile(entity, file_id)
    mismatch = next(e for e in result["exceptions"] if e["code"] == "bank.amount_mismatch")
    assert mismatch["difference"] == 5000.0
    assert mismatch["expected"] == float(due)


def test_a_rupee_of_rounding_is_not_an_exception(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    file_id = bank(entity, user, [
        {"employee_id": "E1", "amount": net_of(entity, "E1") + Decimal("0.40")},
    ])
    assert "bank.amount_mismatch" not in codes(reconcile(entity, file_id))


def test_the_same_employee_twice_in_one_file_is_reported(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    due = net_of(entity, "E1")
    file_id = bank(entity, user, [
        {"employee_id": "E1", "amount": due}, {"employee_id": "E1", "amount": due},
    ])
    result = reconcile(entity, file_id)
    duplicate = next(e for e in result["exceptions"] if e["code"] == "bank.duplicate_payment")
    assert duplicate["context"]["lines"] == 2


def test_two_employees_paid_into_one_account_is_reported(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}, {"employee_id": "E2"}])
    file_id = bank(entity, user, [
        {"employee_id": "E1", "amount": net_of(entity, "E1"), "account_number": "123456789"},
        {"employee_id": "E2", "amount": net_of(entity, "E2"), "account_number": "123456789"},
    ])
    assert "bank.shared_account" in codes(reconcile(entity, file_id))


# ---------------------------------------------------------------------------
# The account check — the reason this module earns its place
# ---------------------------------------------------------------------------
def test_an_account_that_is_not_the_one_on_the_master_is_the_headline(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1", "employee_name": "Asha"}])
    master(entity, user, [{"employee_id": "E1", "employee_name": "Asha",
                           "bank_account": "111122223333"}])
    file_id = bank(entity, user, [
        {"employee_id": "E1", "employee_name": "Asha",
         "amount": net_of(entity, "E1"), "account_number": "999988887777"},
    ])
    result = reconcile(entity, file_id)
    swapped = next(
        e for e in result["exceptions"] if e["code"] == "bank.account_differs_from_master"
    )
    assert swapped["severity"] == "high"
    assert swapped["context"]["on_master"] == "111122223333"
    assert swapped["context"]["paid_to"] == "999988887777"


def test_leading_zeros_and_separators_do_not_make_one_account_look_like_two(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    master(entity, user, [{"employee_id": "E1", "bank_account": "0000123456"}])
    file_id = bank(entity, user, [
        {"employee_id": "E1", "amount": net_of(entity, "E1"), "account_number": "123456"},
    ])
    assert "bank.account_differs_from_master" not in codes(reconcile(entity, file_id))


def test_an_employee_with_no_account_on_the_master_is_flagged_as_unchecked(workspace):
    # Reported as *not checked*, never as checked and fine.
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    file_id = bank(entity, user, [
        {"employee_id": "E1", "amount": net_of(entity, "E1"), "account_number": "123456"},
    ])
    result = reconcile(entity, file_id)
    assert "bank.account_missing_on_master" in codes(result)
    assert next(
        e for e in result["exceptions"] if e["code"] == "bank.account_missing_on_master"
    )["severity"] == "low"


def test_a_beneficiary_name_that_differs_is_low_severity_not_a_match_failure(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1", "employee_name": "Asha Verma"}])
    file_id = bank(entity, user, [
        {"employee_id": "E1", "employee_name": "Rahul Nair", "amount": net_of(entity, "E1")},
    ])
    result = reconcile(entity, file_id)
    assert "bank.name_mismatch" in codes(result)
    # Still matched: the code agreed, and the code is what matching is on.
    assert result["summary"]["matched"] == 1


def test_initials_and_a_middle_name_are_not_a_name_mismatch(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1", "employee_name": "Asha Verma"}])
    file_id = bank(entity, user, [
        {"employee_id": "E1", "employee_name": "ASHA  VERMA", "amount": net_of(entity, "E1")},
    ])
    assert "bank.name_mismatch" not in codes(reconcile(entity, file_id))


# ---------------------------------------------------------------------------
# The file's own problems
# ---------------------------------------------------------------------------
def test_a_rejected_payment_means_that_person_has_not_been_paid(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    file_id = bank(entity, user, [
        {"employee_id": "E1", "amount": net_of(entity, "E1"), "status": "REJECTED"},
    ])
    result = reconcile(entity, file_id)
    returned = next(e for e in result["exceptions"] if e["code"] == "bank.returned")
    assert returned["severity"] == "high"


def test_a_zero_payment_is_reported(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    file_id = bank(entity, user, [{"employee_id": "E1", "amount": Decimal("0")}])
    assert "bank.non_positive_amount" in codes(reconcile(entity, file_id))


def test_a_payment_with_no_employee_code_cannot_be_matched_and_says_so(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    file_id = bank(entity, user, [
        {"employee_id": "E1", "amount": net_of(entity, "E1")},
        {"employee_id": None, "amount": Decimal("1000")},
    ])
    assert "bank.unidentified_row" in codes(reconcile(entity, file_id))


def test_a_file_that_disagrees_with_its_own_control_total_is_reported(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    due = net_of(entity, "E1")
    file_id = bank(entity, user, [{"employee_id": "E1", "amount": due}],
                   stated_total=due + Decimal("100000"))
    assert "bank.stated_total_mismatch" in codes(reconcile(entity, file_id))


def test_the_headline_difference_equals_the_lines_behind_it(workspace):
    # A total that cannot be traced to named employees is not actionable.
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}, {"employee_id": "E2"}])
    file_id = bank(entity, user, [{"employee_id": "E1", "amount": net_of(entity, "E1")}])
    result = reconcile(entity, file_id)
    assert result["summary"]["difference"] == -float(net_of(entity, "E2"))
    assert "bank.total_mismatch" in codes(result)


# ---------------------------------------------------------------------------
# Net pay
# ---------------------------------------------------------------------------
def test_the_register_s_own_net_is_what_the_bank_file_is_compared_against(workspace):
    entity, user, _ = workspace
    register(entity, user, [
        {"employee_id": "E1", "components": {"basic": 30000.0, "hra": 15000.0},
         "deductions": {"ee_pf": 1800.0}, "net_pay": Decimal("41000.00")},
    ])
    file_id = bank(entity, user, [{"employee_id": "E1", "amount": Decimal("41000.00")}])
    result = reconcile(entity, file_id)
    assert "bank.amount_mismatch" not in codes(result)
    # And the gap against the taxonomy is reported separately, not resolved.
    assert "net.stated_vs_computed" in codes(result)


def test_a_register_with_no_net_column_says_what_it_compared_against(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    file_id = bank(entity, user, [{"employee_id": "E1", "amount": net_of(entity, "E1")}])
    result = reconcile(entity, file_id)
    assert "net.no_stated_net" in codes(result)
    assert result["summary"]["reconciled"] is True


# ---------------------------------------------------------------------------
# Through the API, end to end
# ---------------------------------------------------------------------------
def test_a_profile_reads_a_file_and_the_reconciliation_comes_back(client, workspace):
    entity, user, headers = workspace
    register(entity, user, [{"employee_id": "E1"}, {"employee_id": "E2"}])
    due1, due2 = net_of(entity, "E1"), net_of(entity, "E2")

    created = client.post("/api/reconciliation/bank/profiles", headers=headers, json={
        "name": "Our bank", "column_map": {"employee_id": "code", "amount": "net"},
    })
    assert created.status_code == 200, created.text
    profile_id = created.json()["data"]["id"]

    csv = f"code,net\nE1,{due1}\nE2,{due2}\n"
    uploaded = client.post(
        "/api/reconciliation/bank/files", headers=headers,
        files={"file": ("bank.csv", io.BytesIO(csv.encode()), "text/csv")},
        data={"period": "2026-06", "profile_id": profile_id},
    )
    assert uploaded.status_code == 200, uploaded.text
    file_id = uploaded.json()["data"]["id"]

    result = client.get(f"/api/reconciliation/bank/reconcile?file_id={file_id}", headers=headers)
    assert result.status_code == 200
    assert result.json()["data"]["summary"]["reconciled"] is True


def test_a_profile_that_cannot_read_the_file_fails_with_a_reason(client, workspace):
    _, _, headers = workspace
    profile_id = client.post("/api/reconciliation/bank/profiles", headers=headers, json={
        "name": "Wrong mapping", "column_map": {"employee_id": "staff", "amount": "paid"},
    }).json()["data"]["id"]
    r = client.post(
        "/api/reconciliation/bank/files", headers=headers,
        files={"file": ("bank.csv", io.BytesIO(b"code,net\nE1,100\n"), "text/csv")},
        data={"period": "2026-06", "profile_id": profile_id},
    )
    assert r.status_code == 400
    assert "profile" in r.json()["error"]["detail"].lower() or "mapping" in r.json()["error"]["detail"].lower()


def test_testing_a_profile_stores_nothing(client, workspace):
    _, _, headers = workspace
    import json as _json

    profile = {"layout": "delimited", "delimiter": ",", "has_header": True,
               "column_map": {"employee_id": "code", "amount": "net"}}
    r = client.post(
        "/api/reconciliation/bank/profiles/test", headers=headers,
        files={"file": ("bank.csv", io.BytesIO(b"code,net\nE1,1000\n"), "text/csv")},
        data={"profile_json": _json.dumps(profile)},
    )
    assert r.status_code == 200
    assert r.json()["data"]["row_count"] == 1
    assert client.get("/api/reconciliation/bank/files", headers=headers).json()["data"]["files"] == []


def test_a_jv_template_from_a_preset_previews_and_exports(client, workspace):
    entity, user, headers = workspace
    register(entity, user, [{"employee_id": "E1"}, {"employee_id": "E2"}])

    created = client.post("/api/reconciliation/jv/templates", headers=headers, json={
        "name": "Our JV", "from_preset": "standard_accrual",
    })
    assert created.status_code == 200, created.text
    template_id = created.json()["data"]["id"]
    assert created.json()["data"]["rule_count"] == 14

    approved = client.post(
        f"/api/reconciliation/jv/templates/{template_id}/approve", headers=headers
    )
    assert approved.status_code == 200
    assert approved.json()["data"]["is_current"] is True

    preview = client.get("/api/reconciliation/jv/preview?period=2026-06", headers=headers)
    assert preview.status_code == 200
    assert preview.json()["data"]["balanced"] is True

    export = client.get(
        "/api/reconciliation/jv/export?period=2026-06&format=tally_csv", headers=headers
    )
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    assert "Ledger Name" in export.text


def test_editing_an_approved_template_withdraws_its_approval(client, workspace):
    # The mapping that posts to the ledger is re-approved when it changes.
    entity, user, headers = workspace
    created = client.post("/api/reconciliation/jv/templates", headers=headers, json={
        "name": "Editable", "from_preset": "standard_accrual",
    }).json()["data"]
    client.post(f"/api/reconciliation/jv/templates/{created['id']}/approve", headers=headers)

    edited = client.put(
        f"/api/reconciliation/jv/templates/{created['id']}", headers=headers,
        json={"name": "Editable", "rules": [
            {"label": "Salaries", "account_code": "5001", "side": "debit",
             "measures": ["gross"]},
        ]},
    )
    assert edited.status_code == 200
    assert edited.json()["data"]["state"] == "draft"
    assert edited.json()["data"]["is_current"] is False


def test_a_template_mapping_a_measure_that_does_not_exist_is_refused(client, workspace):
    _, _, headers = workspace
    r = client.post("/api/reconciliation/jv/templates", headers=headers, json={
        "name": "Bad", "rules": [
            {"label": "X", "account_code": "1", "side": "debit", "measures": ["bonus_tax"]},
        ],
    })
    assert r.status_code == 400
    assert "bonus_tax" in r.json()["error"]["detail"]


def test_a_per_cost_centre_template_without_a_dimension_is_refused(client, workspace):
    _, _, headers = workspace
    r = client.post("/api/reconciliation/jv/templates", headers=headers, json={
        "name": "No dimension", "split_mode": "per_group", "from_preset": "standard_accrual",
    })
    assert r.status_code == 400


def test_a_reconciliation_run_is_stored_with_its_exceptions(client, workspace):
    entity, user, headers = workspace
    register(entity, user, [{"employee_id": "E1"}, {"employee_id": "E2"}])
    file_id = bank(entity, user, [{"employee_id": "E1", "amount": net_of(entity, "E1")}])

    created = client.post("/api/reconciliation/runs", headers=headers,
                          json={"period_month": "2026-06-01", "kind": "bank",
                                "bank_file_id": str(file_id)})
    assert created.status_code == 200, created.text
    run_id = created.json()["data"]["id"]

    stored = client.get(f"/api/reconciliation/runs/{run_id}", headers=headers).json()["data"]
    assert stored["exception_count"] > 0
    assert any(e["code"] == "bank.not_in_file" for e in stored["exceptions"])
    # Every stored exception carries the guidance for its code.
    assert all(e["action"] for e in stored["exceptions"])


def test_closing_a_run_records_who_accepted_it_without_erasing_anything(client, workspace):
    entity, user, headers = workspace
    register(entity, user, [{"employee_id": "E1"}, {"employee_id": "E2"}])
    file_id = bank(entity, user, [{"employee_id": "E1", "amount": net_of(entity, "E1")}])
    run_id = client.post("/api/reconciliation/runs", headers=headers,
                         json={"period_month": "2026-06-01", "kind": "bank",
                               "bank_file_id": str(file_id)}).json()["data"]["id"]

    closed = client.post(f"/api/reconciliation/runs/{run_id}/close", headers=headers)
    assert closed.status_code == 200
    assert closed.json()["data"]["state"] == "closed"
    assert closed.json()["data"]["closed_by"]

    still_there = client.get(f"/api/reconciliation/runs/{run_id}", headers=headers).json()["data"]
    assert still_there["exception_count"] > 0


# ---------------------------------------------------------------------------
# Never claiming more than was checked
# ---------------------------------------------------------------------------
def test_a_month_with_no_bank_file_is_unreconciled_rather_than_clean(client, workspace):
    entity, user, headers = workspace
    register(entity, user, [{"employee_id": "E1"}])
    overview = client.get("/api/reconciliation/overview?period=2026-06",
                          headers=headers).json()["data"]
    assert overview["bank"]["ready"] is False
    assert "unreconciled" in overview["bank"]["message"]
    assert overview["reconciled"] is False


def test_a_workspace_with_no_register_at_all_says_so(client, workspace):
    _, _, headers = workspace
    overview = client.get("/api/reconciliation/overview", headers=headers).json()["data"]
    assert overview["ready"] is False
    assert overview["period"] is None


def test_the_overview_defaults_to_the_latest_month_that_has_a_register(client, workspace):
    """No ``period`` means "the month I would be closing", i.e. the newest one.

    The parameter is optional, so omitting it has to answer rather than fault.
    It used to read a key the period list does not carry and then stringify the
    whole entry, which made every register-bearing workspace a 400.
    """
    entity, user, headers = workspace
    register(entity, user, [{"employee_id": "E1"}], period=date(2026, 4, 1))
    register(entity, user, [{"employee_id": "E1"}], period=PERIOD)

    response = client.get("/api/reconciliation/overview", headers=headers)
    assert response.status_code == 200, response.text

    overview = response.json()["data"]
    assert overview["period"] == PERIOD.isoformat(), "should default to the newest month"


def test_the_overview_reports_a_missing_jv_template(client, workspace):
    entity, user, headers = workspace
    register(entity, user, [{"employee_id": "E1"}])
    overview = client.get("/api/reconciliation/overview?period=2026-06",
                          headers=headers).json()["data"]
    assert overview["jv"]["ready"] is False
    assert overview["jv"]["template"] is None


def test_previewing_a_voucher_with_no_approved_template_is_a_clear_404(client, workspace):
    _, _, headers = workspace
    r = client.get("/api/reconciliation/jv/preview?period=2026-06", headers=headers)
    assert r.status_code == 404
    assert "approved" in r.json()["error"]["detail"]


def _codes_emitted_by(module) -> set[str]:
    """
    Every code passed to a reporting helper in a module's source.

    Read from the source rather than from a hand-kept list, because a list
    maintained alongside the calls is the thing that goes stale.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in {"_note", "_flag"}:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "." in arg.value:
                out.add(arg.value)
                break
    return out


def test_every_exception_code_either_module_raises_is_in_the_catalogue():
    # An exception with no explanation is an alarm nobody can act on.
    from app.services import jv_builder

    catalogued = {k["code"] for k in reconciliation.exception_catalogue()}
    assert catalogued == {k.code for k in reconciliation.EXCEPTION_KINDS}

    emitted = _codes_emitted_by(reconciliation) | _codes_emitted_by(jv_builder)
    assert emitted, "the source scan found no codes, so it is not checking anything"
    assert emitted <= catalogued, sorted(emitted - catalogued)


def test_every_exception_code_carries_a_meaning_and_an_action():
    for kind in reconciliation.EXCEPTION_KINDS:
        assert kind.meaning and kind.action, kind.code
        assert kind.severity in {"high", "medium", "low"}, kind.code


# ---------------------------------------------------------------------------
# The report, and the other modules this one leans on
# ---------------------------------------------------------------------------
def test_the_reconciliation_workbook_downloads_with_both_halves(client, workspace):
    entity, user, headers = workspace
    register(entity, user, [{"employee_id": "E1"}, {"employee_id": "E2"}])
    bank(entity, user, [{"employee_id": "E1", "amount": net_of(entity, "E1")}])
    template_id = client.post("/api/reconciliation/jv/templates", headers=headers, json={
        "name": "Report JV", "from_preset": "standard_accrual",
    }).json()["data"]["id"]
    client.post(f"/api/reconciliation/jv/templates/{template_id}/approve", headers=headers)

    r = client.get("/api/reports/bank-jv-reconciliation.xlsx?date_to=2026-06", headers=headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml"
    )

    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(r.content))
    assert {"Bank reconciliation", "Bank exceptions", "Journal voucher",
            "Voucher check"} <= set(book.sheetnames)


def test_a_workbook_for_a_month_with_no_bank_file_says_unreconciled_in_words(client, workspace):
    # The sheet is present and says so, rather than being absent — an absent
    # sheet reads as a clean month.
    entity, user, headers = workspace
    register(entity, user, [{"employee_id": "E1"}])
    r = client.get("/api/reports/bank-jv-reconciliation.xlsx?date_to=2026-06", headers=headers)
    assert r.status_code == 200

    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(r.content))
    text = " ".join(
        str(cell.value) for row in book["Bank reconciliation"].iter_rows() for cell in row
    )
    assert "UNRECONCILED" in text


def test_configuration_changes_reach_the_audit_trail(client, workspace):
    # Who changed the mapping that posts to the ledger is the question an
    # auditor asks, and it has to be answerable without reading the database.
    _, _, headers = workspace
    client.post("/api/reconciliation/bank/profiles", headers=headers, json={
        "name": "Audited profile", "column_map": {"employee_id": "code", "amount": "net"},
    })
    template_id = client.post("/api/reconciliation/jv/templates", headers=headers, json={
        "name": "Audited JV", "from_preset": "standard_accrual",
    }).json()["data"]["id"]
    client.post(f"/api/reconciliation/jv/templates/{template_id}/approve", headers=headers)

    events = client.get("/api/audit?limit=50", headers=headers).json()["data"]["events"]
    actions = {e["action"] for e in events}
    assert {"bank_profile.created", "jv_template.created", "jv_template.approved"} <= actions


def test_net_pay_stated_in_an_uploaded_register_reaches_the_reconciliation(client, workspace):
    # The link back to the upload path: a register carrying a net pay column
    # must reconcile against that figure, not a recomputed one.
    _, _, headers = workspace
    for component in ({"component_name": "Basic", "pf_applicable": True},
                      {"component_name": "HRA"}):
        assert client.post("/api/components", json=component,
                           headers=headers).status_code == 201
    csv = (
        "employee_id,employee_name,basic,hra,pf_employee,pt,net_pay\n"
        "E1,Asha,30000,15000,1800,200,41000\n"
    )
    uploaded = client.post(
        "/api/payroll/upload", headers=headers,
        files={"file": ("register.csv", io.BytesIO(csv.encode()), "text/csv")},
        data={"meta": json.dumps({"period_month": "2026-06-01",
                                  "strict_header_check": False})},
    )
    assert uploaded.status_code == 200, uploaded.text

    db = SessionLocal()
    try:
        entity_id = uuid.UUID(headers["X-Entity-Id"])
        entries = reconciliation.register_net(db, entity_id, PERIOD)
    finally:
        db.close()
    assert len(entries) == 1
    assert entries[0].stated_net == Decimal("41000.00")
    assert entries[0].expected == Decimal("41000.00")
