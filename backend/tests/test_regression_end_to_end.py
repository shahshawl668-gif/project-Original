"""
One company, three months, the whole product.

The unit suites prove each module is right on its own. This one exists to
answer a different question: do the three modules agree with each other when
they are looking at the same month?

    validation  — is the register correct?
    cost / BI   — what did it cost, and by what?
    reconciliation — did that reach the bank, and the ledger?

The assertions that matter here are the cross-module ones. Any module can be
internally consistent and still disagree with its neighbour, and a client who
is shown ₹9.1 crore on a dashboard and ₹8.7 crore on a voucher will not care
which of the two is right.

The scenario plants real defects rather than clean data, because a product
that returns 200 on a perfect file has proved almost nothing:

* E004 has PF wages but no PF deducted            → validation must find it
* E003 is paid into an account that is not the master's → the fraud check
* E007 is on the register and missing from the bank file → an unpaid employee
* E999 is paid and is on no register               → a payee nobody authorised
* E010 joins in May and E002 leaves in June        → headcount movement
* two states, three departments, two cost centres  → dimensional splits
"""
from __future__ import annotations

import io
import json
from datetime import date

import pytest

PASSWORD = "Passw0rd!x"
PERIODS = [date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1)]

COMPONENTS = [
    {"component_name": "Basic", "pf_applicable": True, "esic_applicable": True,
     "pt_applicable": True, "lwf_applicable": True, "included_in_wages": True, "taxable": True},
    {"component_name": "HRA", "esic_applicable": True, "pt_applicable": True, "taxable": True},
    {"component_name": "Special Allowance", "pf_applicable": True, "esic_applicable": True,
     "pt_applicable": True, "taxable": True},
    {"component_name": "Conveyance", "esic_applicable": True, "pt_applicable": True,
     "taxable": True},
]

# employee_id, name, gender, state, department, cost centre, basic, joined, exited
STAFF = [
    ("E001", "Asha Menon",      "F", "Karnataka",   "Engineering", "CC-ENG", 62000, "2019-06-03", None),
    ("E002", "Rahul Verma",     "M", "Karnataka",   "Engineering", "CC-ENG", 48000, "2021-01-11", "2026-06-24"),
    ("E003", "Priya Nair",      "F", "Karnataka",   "Engineering", "CC-ENG", 35000, "2022-08-01", None),
    ("E004", "Imran Shaikh",    "M", "Karnataka",   "Engineering", "CC-ENG", 28000, "2023-03-15", None),
    ("E005", "Devika Rao",      "F", "Karnataka",   "Sales",       "CC-SAL", 41000, "2020-11-02", None),
    ("E006", "Sanjay Kulkarni", "M", "Maharashtra", "Sales",       "CC-SAL", 33000, "2021-07-19", None),
    ("E007", "Meera Iyer",      "F", "Maharashtra", "Sales",       "CC-SAL", 26000, "2024-02-05", None),
    ("E008", "Vikram Desai",    "M", "Karnataka",   "Operations",  "CC-OPS", 14500, "2023-09-11", None),
    ("E009", "Fatima Khan",     "F", "Karnataka",   "Operations",  "CC-OPS", 12800, "2024-06-17", None),
    ("E010", "Arjun Pillai",    "M", "Karnataka",   "Operations",  "CC-OPS", 15200, "2026-05-04", None),
]

# Who is on which month's register: E010 joins in May, E002 leaves after June.
def on_register(employee_id: str, period: date) -> bool:
    if employee_id == "E010":
        return period >= date(2026, 5, 1)
    return True


def pay(basic: int) -> dict[str, int]:
    """A pay structure built the way Indian structures usually are."""
    return {
        "Basic": basic,
        "HRA": round(basic * 0.4),
        "Special Allowance": round(basic * 0.25),
        "Conveyance": 1600,
    }


def gross(basic: int) -> int:
    return sum(pay(basic).values())


def pf_employee(employee_id: str, basic: int) -> int:
    """
    12% of PF wages, capped at the ₹15,000 ceiling.

    PF wages are every component marked pf_applicable — here Basic plus Special
    Allowance — not Basic alone. Getting this right in the fixture matters: if
    the scenario deducted the wrong PF, every employee would be flagged and the
    one planted defect would be lost in the noise.
    """
    if employee_id == "E004":
        # Planted: PF wages present, nothing deducted. Validation must catch it.
        return 0
    pf_wage = min(basic + pay(basic)["Special Allowance"], 15000)
    return round(pf_wage * 0.12)


def register_csv(period: date) -> str:
    header = (
        "employee_id,employee_name,state,paid_days,lop_days,"
        "basic,hra,special allowance,conveyance,"
        "pf_employee,pf_employer,esic_employee,esic_employer,pt,tds,net_pay\n"
    )
    lines = []
    for employee_id, name, _gender, state, _dept, _cc, basic, _doj, _dol in STAFF:
        if not on_register(employee_id, period):
            continue
        parts = pay(basic)
        total = sum(parts.values())
        ee_pf = pf_employee(employee_id, basic)
        er_pf = ee_pf
        esi_ee = esi_er = 0
        if total <= 21000:
            esi_ee = round(total * 0.0075)
            esi_er = round(total * 0.0325)
        pt = 200 if state == "Karnataka" and total > 25000 else (200 if state == "Maharashtra" else 0)
        tds = round(max(total - 30000, 0) * 0.05)
        net = total - ee_pf - esi_ee - pt - tds
        lines.append(
            f"{employee_id},{name},{state},30,0,"
            f"{parts['Basic']},{parts['HRA']},{parts['Special Allowance']},{parts['Conveyance']},"
            f"{ee_pf},{er_pf},{esi_ee},{esi_er},{pt},{tds},{net}"
        )
    return header + "\n".join(lines) + "\n"


def attendance_csv(period: date) -> str:
    """
    A full month for everyone, with two planted problems in June.

    E005 loses three days that the register never deducts, and E006 works
    overtime that nobody pays. Both are invisible to every register-level
    check: the register is perfectly consistent with itself, it is consistent
    with the wrong number of days.
    """
    days = 30 if period.month in (4, 6, 9, 11) else 31
    header = ("employee_id,employee_name,calendar_days,present_days,paid_leave_days,"
              "weekly_off_days,holiday_days,lop_days,paid_days,overtime_hours\n")
    lines = []
    for employee_id, name, *_ in STAFF:
        if not on_register(employee_id, period):
            continue
        lop = 3 if (employee_id == "E005" and period == date(2026, 6, 1)) else 0
        overtime = 8 if (employee_id == "E006" and period == date(2026, 6, 1)) else 0
        weekly_off, holiday, paid_leave = 4, 1, 0
        present = days - weekly_off - holiday - paid_leave - lop
        lines.append(
            f"{employee_id},{name},{days},{present},{paid_leave},{weekly_off},"
            f"{holiday},{lop},{days - lop},{overtime}"
        )
    return header + "\n".join(lines) + "\n"


def master_csv() -> str:
    header = (
        "employee_id,employee_name,gender,date_of_joining,date_of_exit,work_state,"
        "department,cost_center,designation,employment_type,bank_account,ifsc\n"
    )
    lines = []
    for employee_id, name, gender, state, dept, cc, _basic, doj, dol in STAFF:
        account = f"5001{employee_id[1:]}0099"
        lines.append(
            f"{employee_id},{name},{gender},{doj},{dol or ''},{state},"
            f"{dept},{cc},Consultant,Permanent,{account},HDFC0001234"
        )
    return header + "\n".join(lines) + "\n"


def bank_csv(period: date) -> str:
    """
    The payment file, with three deliberate problems.

    Built from the register's own net so the clean rows reconcile exactly; the
    planted rows are the only differences, which is what lets the test assert
    the totals rather than merely the exception count.
    """
    rows = []
    for line in register_csv(period).splitlines()[1:]:
        cells = line.split(",")
        employee_id, name, net = cells[0], cells[1], cells[-1]
        if employee_id == "E007" and period == date(2026, 6, 1):
            continue  # planted: due but never paid
        account = f"5001{employee_id[1:]}0099"
        if employee_id == "E003" and period == date(2026, 6, 1):
            account = "9999888877776666"  # planted: not the account on the master
        rows.append(f"{employee_id},{name},{account},HDFC0001234,{net}")
    if period == date(2026, 6, 1):
        rows.append("E999,Unknown Payee,7777666655554444,HDFC0001234,84000")  # planted: ghost
    body = "\n".join(rows)
    return "code,name,account,ifsc,amount\n" + body + "\n"


# ---------------------------------------------------------------------------
# The company, set up once for the whole scenario
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def company(client):
    email = "close@regression-example.com"
    r = client.post("/api/auth/signup", json={
        "email": email, "password": PASSWORD, "company_name": "Regression Services Pvt Ltd",
    })
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}

    entity_id = client.post(
        "/api/org/entities",
        json={"name": "Regression Services", "primary_state": "Karnataka"},
        headers=headers,
    ).json()["data"]["id"]
    headers["X-Entity-Id"] = entity_id

    for component in COMPONENTS:
        assert client.post("/api/components", json=component, headers=headers).status_code == 201

    for rule_type in ("PT", "LWF"):
        client.post(
            f"/api/rule-engine/slabs/import-defaults/all?rule_type={rule_type}&overwrite=true",
            headers=headers,
        )

    commit = client.post(
        "/api/workforce/master/commit", headers=headers,
        files={"file": ("master.csv", io.BytesIO(master_csv().encode()), "text/csv")},
        data={"meta": json.dumps({"effective_from": "2026-04-01"})},
    )
    assert commit.status_code == 200, commit.text

    for period in PERIODS:
        checked = client.post(
            "/api/workforce/attendance/validate", headers=headers,
            files={"file": (f"att-{period:%Y-%m}.csv",
                            io.BytesIO(attendance_csv(period).encode()), "text/csv")},
            data={"meta": json.dumps({"period_month": period.isoformat()})},
        )
        assert checked.status_code == 200, checked.text
        assert checked.json()["data"]["clean"] is True, checked.json()["data"]["findings"]
        committed = client.post(
            "/api/workforce/attendance/commit", headers=headers,
            files={"file": (f"att-{period:%Y-%m}.csv",
                            io.BytesIO(attendance_csv(period).encode()), "text/csv")},
            data={"meta": json.dumps({"period_month": period.isoformat()})},
        )
        assert committed.status_code == 200, committed.text

        upload = client.post(
            "/api/payroll/upload", headers=headers,
            files={
                "file": (
                    f"register-{period:%Y-%m}.csv",
                    io.BytesIO(register_csv(period).encode()),
                    "text/csv",
                )
            },
            data={"meta": json.dumps({
                "period_month": period.isoformat(), "strict_header_check": False,
            })},
        )
        assert upload.status_code == 200, upload.text

    return headers


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


# ---------------------------------------------------------------------------
# Stage 1 — the data landed
# ---------------------------------------------------------------------------
def test_the_master_and_three_registers_are_stored(client, company):
    master = data(client.get("/api/workforce/master", headers=company))
    assert len({r["employee_id"] for r in master}) == len(STAFF)

    registers = data(client.get("/api/payroll/registers", headers=company))
    assert [r["period_month"] for r in registers[:3]] == sorted(
        (p.isoformat() for p in PERIODS), reverse=True
    )
    counts = {r["period_month"]: r["employee_count"] for r in registers}
    assert counts["2026-04-01"] == 9   # E010 has not joined
    assert counts["2026-06-01"] == 10


def test_the_reporting_attributes_came_off_the_master(client, company):
    # Dimensions are snapshotted onto the register at upload. If this breaks,
    # every breakdown in the product silently collapses into "Unassigned".
    analysis = data(client.get(
        "/api/bi/cost-analysis?group_by=department&date_from=2026-04-01&date_to=2026-06-01",
        headers=company,
    ))
    assert set(analysis["groups"]) == {"Engineering", "Sales", "Operations"}


# ---------------------------------------------------------------------------
# Stage 2 — Module A: validation finds the planted defect
# ---------------------------------------------------------------------------
def test_validation_finds_the_employee_whose_pf_was_not_deducted(client, company):
    parsed = data(client.post(
        "/api/payroll/upload", headers=company,
        files={"file": ("june.csv", io.BytesIO(register_csv(PERIODS[2]).encode()), "text/csv")},
        data={"meta": json.dumps({
            "period_month": "2026-06-01", "strict_header_check": False,
        })},
    ))
    result = data(client.post("/api/payroll/validate", headers=company, json={
        "employees": parsed["employees"], "period_month": "2026-06-01",
    }))

    critical_pf = {
        row["employee_id"]
        for row in result["results"]
        for finding in row.get("findings", [])
        if finding.get("rule_id") == "STAT-001" and finding.get("severity") == "CRITICAL"
    }
    assert critical_pf == {"E004"}, (
        "the planted PF under-deduction was not reported at CRITICAL — a register "
        "stating a PF of zero is claiming nothing was deducted, not omitting a column"
    )


def test_the_finding_survives_into_the_findings_register(client, company):
    summary = data(client.get("/api/findings/summary", headers=company))
    assert summary["open_count"] > 0
    findings = data(client.get("/api/findings", headers=company))
    assert any(f["employee_id"] == "E004" for f in findings)


def test_attendance_the_register_ignored_is_reported(client, company):
    """
    The gap no register-level rule can see.

    E005 lost three days and was paid for thirty. Gross matches its own
    components, PF matches the PF wage, every internal check passes — and the
    employee has been overpaid three days' wages.
    """
    parsed = data(client.post(
        "/api/payroll/upload", headers=company,
        files={"file": ("june.csv", io.BytesIO(register_csv(PERIODS[2]).encode()), "text/csv")},
        data={"meta": json.dumps({
            "period_month": "2026-06-01", "strict_header_check": False,
        })},
    ))
    result = data(client.post("/api/payroll/validate", headers=company, json={
        "employees": parsed["employees"], "period_month": "2026-06-01",
    }))
    by_employee = {
        row["employee_id"]: {f["rule_id"]: f for f in row["findings"]}
        for row in result["results"]
    }

    # The days themselves disagree …
    assert "ATT-002" in by_employee["E005"]
    # … and so does the money, valued against May, which carried no loss of pay.
    overpaid = by_employee["E005"]["ATT-020"]
    assert overpaid["severity"] == "CRITICAL"
    assert overpaid["financial_impact"] > 0

    # Overtime worked and never paid.
    assert "ATT-022" in by_employee["E006"]

    # And nobody else is dragged in by the change.
    for employee_id, findings in by_employee.items():
        if employee_id not in ("E005", "E006"):
            assert "ATT-020" not in findings and "ATT-022" not in findings, employee_id


def test_an_attendance_file_that_does_not_add_up_is_refused_before_it_is_stored(client, company):
    broken = (
        "employee_id,calendar_days,present_days,paid_leave_days,weekly_off_days,"
        "holiday_days,lop_days,paid_days\n"
        "E001,31,22,1,4,1,2,30\n"      # 31 days claimed in a 30-day June
        "E002,30,22,1,4,1,4,30\n"      # 30 paid with 4 lost — contradicts itself
    )
    checked = data(client.post(
        "/api/workforce/attendance/validate", headers=company,
        files={"file": ("broken.csv", io.BytesIO(broken.encode()), "text/csv")},
        data={"meta": json.dumps({"period_month": "2026-06-01"})},
    ))
    assert checked["clean"] is False
    assert {f["rule_id"] for f in checked["findings"]} >= {"ATT-011", "ATT-012"}

    # And nothing was stored: the good June file is still the one on record.
    registers = data(client.get("/api/workforce/attendance", headers=company))
    june = next(r for r in registers if r["period_month"] == "2026-06-01")
    assert june["employee_count"] == 10


# ---------------------------------------------------------------------------
# Stage 3 — Module B: cost and BI
# ---------------------------------------------------------------------------
def test_the_cost_taxonomy_adds_up_to_its_own_definition(client, company):
    analysis = data(client.get(
        "/api/bi/cost-analysis?date_from=2026-06-01&date_to=2026-06-01", headers=company
    ))
    totals = analysis["totals"]
    earnings = sum(totals[k] for k in
                   ("basic_da", "hra", "allowances", "variable_pay", "arrears"))
    employer = sum(totals[k] for k in
                   ("er_pf", "er_pf_admin", "er_esi", "gratuity", "er_lwf"))
    assert round(totals["gross"], 2) == round(earnings, 2)
    assert round(totals["employer_cost"], 2) == round(employer, 2)
    # The identity the whole product rests on. Deductions are inside gross and
    # are deliberately not added on top.
    assert round(totals["ctc"], 2) == round(earnings + employer, 2)
    assert round(totals["net"], 2) == round(totals["gross"] - totals["deductions"], 2)


def test_the_register_s_own_statutory_figures_are_used_not_recomputed(client, company):
    analysis = data(client.get(
        "/api/bi/cost-analysis?date_from=2026-06-01&date_to=2026-06-01", headers=company
    ))
    # The register states PF, ESI, PT and TDS. The dashboard reports those
    # rather than its own arithmetic, and says how much it read.
    assert analysis["sources"]["reported"] > 0
    assert analysis["totals"]["tds"] > 0


def test_headcount_movement_sees_the_joiner_and_the_leaver(client, company):
    movement = data(client.get(
        "/api/bi/headcount-movement?date_from=2026-04-01&date_to=2026-06-01", headers=company
    ))
    by_period = {p["period"]: p for p in movement["periods"]}
    assert by_period["2026-05-01"]["joiners"] >= 1
    assert by_period["2026-06-01"]["closing"] == 10


def test_month_on_month_comparison_answers(client, company):
    compare = data(client.get(
        "/api/bi/cost-compare?period_a=2026-04-01&period_b=2026-06-01", headers=company
    ))
    assert compare["a"]["measures"]["ctc"] > 0
    assert compare["b"]["measures"]["ctc"] > 0
    # E010 joined in May, so June carries one more person and more cost.
    assert compare["headcount"]["delta"] == 1
    assert compare["b"]["measures"]["ctc"] > compare["a"]["measures"]["ctc"]


def test_a_budget_can_be_uploaded_approved_and_compared(client, company):
    rows = "period,scope,amount,headcount\n"
    for period in PERIODS:
        rows += f"{period:%Y-%m},entity,5200000,10\n"
    created = data(client.post(
        "/api/budget/versions", headers=company,
        files={"file": ("budget.csv", io.BytesIO(rows.encode()), "text/csv")},
        data={"name": "FY27 plan", "scope_key": "entity", "measure": "ctc"},
    ))
    assert data(client.post(
        f"/api/budget/versions/{created['id']}/approve", headers=company
    ))["state"] == "approved"

    variance = data(client.get(
        "/api/budget/variance?date_from=2026-04-01&date_to=2026-06-01", headers=company
    ))
    assert variance["totals"]["budget"] > 0
    assert variance["totals"]["actual"] > 0


def test_a_forecast_never_comes_back_looking_like_an_actual(client, company):
    forecast = data(client.get("/api/budget/forecast?months=3&increment_pct=8", headers=company))
    assert "forecast" in forecast
    assert forecast.get("disclaimer")


# ---------------------------------------------------------------------------
# Stage 4 — Module C: reconciliation
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def bank_files(client, company):
    profile = data(client.post("/api/reconciliation/bank/profiles", headers=company, json={
        "name": "Regression bank", "bank_label": "HDFC Bank",
        "column_map": {
            "employee_id": "code", "employee_name": "name",
            "account_number": "account", "ifsc": "ifsc", "amount": "amount",
        },
        "is_default": True,
    }))
    uploaded = {}
    for period in PERIODS:
        result = data(client.post(
            "/api/reconciliation/bank/files", headers=company,
            files={"file": (
                f"bank-{period:%Y-%m}.csv",
                io.BytesIO(bank_csv(period).encode()), "text/csv",
            )},
            data={"period": f"{period:%Y-%m}", "profile_id": profile["id"]},
        ))
        uploaded[period] = result["id"]
    return uploaded


def test_a_clean_month_reconciles_to_the_rupee(client, company, bank_files):
    result = data(client.get(
        f"/api/reconciliation/bank/reconcile?file_id={bank_files[PERIODS[0]]}", headers=company
    ))
    assert result["summary"]["difference"] == 0
    assert result["summary"]["matched"] == 9
    codes = {e["code"] for e in result["exceptions"]}
    assert "bank.amount_mismatch" not in codes
    assert "bank.not_in_file" not in codes


def test_the_three_planted_payment_problems_are_all_found(client, company, bank_files):
    result = data(client.get(
        f"/api/reconciliation/bank/reconcile?file_id={bank_files[PERIODS[2]]}", headers=company
    ))
    by_code = {}
    for item in result["exceptions"]:
        by_code.setdefault(item["code"], []).append(item)

    unpaid = by_code["bank.not_in_file"]
    assert [e["employee_id"] for e in unpaid] == ["E007"]

    swapped = by_code["bank.account_differs_from_master"]
    assert [e["employee_id"] for e in swapped] == ["E003"]
    assert swapped[0]["context"]["paid_to"] == "9999888877776666"

    ghost = by_code["bank.not_in_register"]
    assert [e["employee_id"] for e in ghost] == ["E999"]
    assert ghost[0]["actual"] == 84000.0

    assert result["summary"]["reconciled"] is False


def test_the_headline_difference_is_exactly_the_planted_lines(client, company, bank_files):
    # A total nobody can trace to named employees is not actionable. The
    # difference must be the ghost payment less the employee who went unpaid.
    result = data(client.get(
        f"/api/reconciliation/bank/reconcile?file_id={bank_files[PERIODS[2]]}", headers=company
    ))
    unpaid = next(
        e for e in result["exceptions"] if e["code"] == "bank.not_in_file"
    )["expected"]
    assert round(result["summary"]["difference"], 2) == round(84000.0 - unpaid, 2)


@pytest.fixture(scope="module")
def jv_template(client, company):
    template = data(client.post("/api/reconciliation/jv/templates", headers=company, json={
        "name": "Regression JV", "from_preset": "standard_accrual",
    }))
    data(client.post(
        f"/api/reconciliation/jv/templates/{template['id']}/approve", headers=company
    ))
    return template["id"]


def test_the_voucher_balances_for_every_month(client, company, jv_template):
    for period in PERIODS:
        result = data(client.get(
            f"/api/reconciliation/jv/reconcile?period={period:%Y-%m}", headers=company
        ))
        assert result["balanced"] is True, f"{period:%b %Y} does not balance"
        assert result["summary"]["reconciled"] is True


def test_the_voucher_exports_in_every_layout(client, company, jv_template):
    for fmt in ("generic_csv", "tally_csv", "sap_csv", "zoho_csv"):
        response = client.get(
            f"/api/reconciliation/jv/export?period=2026-06&format={fmt}", headers=company
        )
        assert response.status_code == 200, fmt
        lines = [line for line in response.text.splitlines() if line.strip()]
        assert len(lines) > 5, fmt


def test_a_cost_centre_split_produces_a_balancing_voucher_per_centre(client, company):
    template = data(client.post("/api/reconciliation/jv/templates", headers=company, json={
        "name": "Regression JV by cost centre", "from_preset": "standard_accrual",
        "split_mode": "per_group", "group_by": "cost_center",
    }))
    result = data(client.get(
        f"/api/reconciliation/jv/preview?period=2026-06&template_id={template['id']}",
        headers=company,
    ))
    assert {v["scope"] for v in result["vouchers"]} == {"CC-ENG", "CC-SAL", "CC-OPS"}
    assert all(v["balanced"] for v in result["vouchers"])


# ---------------------------------------------------------------------------
# Stage 5 — the cross-module assertions this file exists for
# ---------------------------------------------------------------------------
def test_the_ledger_posts_exactly_what_the_cost_dashboard_reports(client, company, jv_template):
    # If these two ever part company, a client is shown one payroll cost on a
    # dashboard and a different one in their books.
    analysis = data(client.get(
        "/api/bi/cost-analysis?date_from=2026-06-01&date_to=2026-06-01", headers=company
    ))
    voucher = data(client.get(
        "/api/reconciliation/jv/reconcile?period=2026-06", headers=company
    ))
    assert round(voucher["summary"]["total_debit"], 2) == round(analysis["totals"]["ctc"], 2)
    assert round(voucher["summary"]["payroll_cost"], 2) == round(analysis["totals"]["ctc"], 2)


def test_the_voucher_credits_the_same_net_the_dashboard_computes(
    client, company, jv_template
):
    analysis = data(client.get(
        "/api/bi/cost-analysis?date_from=2026-04-01&date_to=2026-04-01", headers=company
    ))
    voucher = data(client.get(
        "/api/reconciliation/jv/preview?period=2026-04", headers=company
    ))
    salary_payable = sum(
        line["credit"] for v in voucher["vouchers"] for line in v["lines"]
        if line["account_code"] == "2001"
    )
    assert round(salary_payable, 2) == round(analysis["totals"]["net"], 2)


def test_the_bank_is_reconciled_against_the_net_the_register_itself_stated(
    client, company, bank_files
):
    """
    Stated net and computed net differ here, and that is correct.

    This register states PF, ESI, PT and TDS but no LWF, so the engine fills
    the LWF in and computed net comes out lower than the net the register
    declared. The bank file was instructed with the *stated* figure, so that is
    what it is reconciled against — and the gap between the two is reported as
    an exception rather than quietly resolved in either direction.
    """
    analysis = data(client.get(
        "/api/bi/cost-analysis?date_from=2026-04-01&date_to=2026-04-01", headers=company
    ))
    recon = data(client.get(
        f"/api/reconciliation/bank/reconcile?file_id={bank_files[PERIODS[0]]}", headers=company
    ))

    # A clean month: the file pays exactly what the register said it would.
    assert round(recon["summary"]["paid_total"], 2) == round(recon["summary"]["due_total"], 2)

    # And the gap against the taxonomy is exactly the deduction the register
    # never itemised — not a rounding drift, and not unexplained.
    gap = recon["summary"]["due_total"] - analysis["totals"]["net"]
    assert round(gap, 2) == round(analysis["totals"]["ee_lwf"], 2)
    assert any(e["code"] == "net.stated_vs_computed" for e in recon["exceptions"])


def test_headcount_is_one_number_across_the_register_the_dashboard_and_the_voucher(
    client, company, jv_template
):
    registers = data(client.get("/api/payroll/registers", headers=company))
    stored = next(r for r in registers if r["period_month"] == "2026-06-01")["employee_count"]
    analysis = data(client.get(
        "/api/bi/cost-analysis?date_from=2026-06-01&date_to=2026-06-01", headers=company
    ))
    voucher = data(client.get(
        "/api/reconciliation/jv/reconcile?period=2026-06", headers=company
    ))
    assert stored == analysis["totals"]["headcount"] == voucher["employee_count"] == 10


def test_a_dimensional_split_sums_back_to_the_whole(client, company):
    # Every breakdown in the product has to total to the same figure, or a
    # reader who slices by department gets a different company.
    whole = data(client.get(
        "/api/bi/cost-analysis?date_from=2026-06-01&date_to=2026-06-01", headers=company
    ))["totals"]["ctc"]
    for dimension in ("department", "cost_center", "work_state", "employment_type"):
        split = data(client.get(
            f"/api/bi/cost-analysis?group_by={dimension}&date_from=2026-06-01&date_to=2026-06-01",
            headers=company,
        ))
        assert round(sum(g["total"] for g in split["matrix"]), 2) == round(whole, 2), dimension


def test_the_two_states_are_kept_apart_where_the_law_differs(client, company):
    split = data(client.get(
        "/api/bi/cost-analysis?group_by=work_state&date_from=2026-06-01&date_to=2026-06-01",
        headers=company,
    ))
    assert set(split["groups"]) == {"Karnataka", "Maharashtra"}


# ---------------------------------------------------------------------------
# Stage 6 — the outputs a client actually receives
# ---------------------------------------------------------------------------
def test_every_report_in_the_catalogue_downloads(client, company, bank_files, jv_template):
    catalogue = data(client.get("/api/reports", headers=company))["reports"]
    assert len(catalogue) >= 10
    for report in catalogue:
        if report["key"] == "pay-equity":
            continue  # authorisation-gated; covered by its own suite
        response = client.get(
            f"/api/reports/{report['key']}.xlsx?date_from=2026-04-01&date_to=2026-06-01",
            headers=company,
        )
        assert response.status_code == 200, report["key"]
        assert response.content[:2] == b"PK", report["key"]


def test_the_reconciliation_pack_carries_the_planted_exceptions(client, company, bank_files):
    import openpyxl

    response = client.get(
        "/api/reports/bank-jv-reconciliation.xlsx?date_to=2026-06-01", headers=company
    )
    assert response.status_code == 200
    book = openpyxl.load_workbook(io.BytesIO(response.content))
    text = " ".join(
        str(cell.value)
        for sheet in ("Bank exceptions", "Voucher check")
        for row in book[sheet].iter_rows()
        for cell in row
    )
    assert "E003" in text and "E007" in text and "E999" in text


def test_the_month_can_be_signed_off_with_an_evidence_pack(client, company):
    submitted = client.post("/api/signoff/submit", headers=company,
                            json={"period_month": "2026-04-01", "notes": "Regression run"})
    assert submitted.status_code == 200, submitted.text
    signed = client.post("/api/signoff/sign", headers=company,
                         json={"period_month": "2026-04-01", "notes": "Checked"})
    assert signed.status_code == 200, signed.text
    pack = client.get("/api/signoff/2026-04-01/evidence-pack", headers=company)
    assert pack.status_code == 200, pack.text
    assert pack.content[:2] == b"PK"


def test_signing_a_period_that_was_never_validated_says_nothing_was_checked(client, company):
    """
    The snapshot counts what a validation run checked, not what is on file.

    April was uploaded but never put through validation, so the signed record
    says zero employees were checked. That is honest — but it means a period
    can carry a signature while the snapshot behind it is empty, which is worth
    a caller's attention.
    """
    state = data(client.get("/api/signoff/2026-04-01", headers=company))["signoff"]
    assert state["state"] == "signed"
    assert state["employee_count"] == 0


def test_the_audit_trail_carries_the_whole_chain(client, company, bank_files, jv_template):
    events = data(client.get("/api/audit?limit=200", headers=company))["events"]
    actions = {e["action"] for e in events}
    for expected in (
        "register.uploaded", "budget.uploaded", "budget.approved",
        "bank_profile.created", "bank_file.uploaded",
        "jv_template.created", "jv_template.approved",
    ):
        assert expected in actions, f"{expected} left no audit trail"


# ---------------------------------------------------------------------------
# Stage 7 — the month as the product summarises it
# ---------------------------------------------------------------------------
def test_the_close_overview_reports_the_month_as_it_actually_is(
    client, company, bank_files, jv_template
):
    overview = data(client.get("/api/reconciliation/overview?period=2026-06", headers=company))
    assert overview["register"]["employees"] == 10
    assert overview["bank"]["ready"] is True
    assert overview["jv"]["ready"] is True
    # Nothing has been kept and closed for June, so the month is not reconciled
    # however green the individual panels look.
    assert overview["reconciled"] is False


def test_closing_the_month_puts_the_exceptions_on_the_record(
    client, company, bank_files, jv_template
):
    run = data(client.post("/api/reconciliation/runs", headers=company, json={
        "period_month": "2026-06-01", "kind": "bank",
        "bank_file_id": bank_files[PERIODS[2]],
    }))
    assert run["exception_count"] >= 3

    closed = data(client.post(f"/api/reconciliation/runs/{run['id']}/close", headers=company))
    assert closed["state"] == "closed"
    assert closed["closed_by"]

    stored = data(client.get(f"/api/reconciliation/runs/{run['id']}", headers=company))
    codes = {e["code"] for e in stored["exceptions"]}
    assert {"bank.not_in_file", "bank.not_in_register",
            "bank.account_differs_from_master"} <= codes
    # Closing records that someone accepted the position; it never erases it.
    assert stored["exception_count"] == run["exception_count"]
