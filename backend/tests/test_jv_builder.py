"""
Building a journal voucher from a month of payroll cost.

The property under test is the one that makes this module worth having: a
voucher built from the cost taxonomy balances *by arithmetic*, not by luck.

    debits  = gross + employer contributions
    credits = employer contributions + deductions + net
            = employer + deductions + (gross - deductions)

so the balance check is a real test of the company's own mapping. Every test
here that asserts a balance is asserting that identity; every test that asserts
an imbalance is checking the product reports a mapping error rather than
papering over it.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import Entity, SalaryRegister, SalaryRegisterRow, User
from app.services import jv_builder
from app.services.dimensions import UNASSIGNED

PASSWORD = "Passw0rd!x"
PERIOD = date(2026, 6, 1)


@pytest.fixture()
def workspace(client, request):
    email = f"{request.node.name[:40]}@jv-example.com".replace("_", "-")
    r = client.post("/api/auth/signup",
                    json={"email": email, "password": PASSWORD, "company_name": "JV Tests"})
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


def _dims(**kw) -> dict:
    base = dict.fromkeys(
        ("business_unit", "department", "cost_center", "work_location", "work_state",
         "grade", "designation", "employment_type", "skill_category"), UNASSIGNED
    )
    base.update(kw)
    return base


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
                arrears=row.get("arrears", {}),
                deductions=row.get("deductions", {}),
                dimensions=row.get("dimensions") or _dims(),
                net_pay=row.get("net_pay"),
                increment_arrear_total=Decimal("0"),
            ))
        db.commit()
    finally:
        db.close()


def build(entity, template_overrides: dict | None = None, rules=None, period: date = PERIOD):
    template = {
        "name": "Test template", "posting_basis": "accrual", "split_mode": "consolidated",
        "detail_level": "summary", "group_by": None, "sign_convention": "two_column",
        "net_pay_source": "computed", "voucher_date_rule": "month_end",
        "voucher_type": "Journal",
        "narration_template": "Payroll for {period_label}{scope_suffix}",
        "balance_tolerance": "1.00", "rounding_mode": "none", "rounding_account": None,
    }
    template.update(template_overrides or {})
    if rules is None:
        rules = jv_builder.preset_rules("standard_accrual")
    db = SessionLocal()
    try:
        return jv_builder.build_jv(db, entity.id, period, template, rules=rules)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The identity
# ---------------------------------------------------------------------------
def test_the_supplied_template_balances_to_the_paisa(workspace):
    entity, user, _ = workspace
    register(entity, user, [
        {"employee_id": "E1", "components": {"basic": 40000.0, "hra": 20000.0}},
        {"employee_id": "E2", "components": {"basic": 25000.0, "hra": 12500.0,
                                             "special_allowance": 5000.0}},
        {"employee_id": "E3", "components": {"basic": 15000.0, "hra": 7000.0},
         "deductions": {"pt": 200.0, "tds": 1500.0}},
    ])
    document = build(entity)
    assert document.warnings == [], document.warnings
    assert document.total_debit == document.total_credit
    assert document.difference == Decimal("0")


def test_debits_equal_the_payroll_cost_the_dashboard_reports(workspace):
    # The whole reason a rule names measures rather than columns: one costing
    # pass feeds both, so the ledger and the dashboard cannot disagree.
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}, {"employee_id": "E2"}])
    document = build(entity)
    assert document.total_debit == document.cost_totals["ctc"]


def test_credits_are_the_liabilities_plus_net_pay(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1", "deductions": {"tds": 2000.0, "pt": 200.0}}])
    document = build(entity)
    totals = document.cost_totals
    expected = totals["employer_cost"] + totals["deductions"] + totals["net"]
    assert document.total_credit == expected


def test_a_register_with_arrears_still_balances(workspace):
    entity, user, _ = workspace
    register(entity, user, [
        {"employee_id": "E1", "arrears": {"basic": 12000.0, "hra": 6000.0}},
    ])
    document = build(entity)
    assert document.difference == Decimal("0")
    assert document.cost_totals["arrears"] > 0


# ---------------------------------------------------------------------------
# The options
# ---------------------------------------------------------------------------
def test_the_cash_basis_leaves_gratuity_out_and_still_balances(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    accrual = build(entity)
    cash = build(entity, {"posting_basis": "cash"})
    assert accrual.cost_totals["gratuity"] > 0
    assert cash.cost_totals["gratuity"] == Decimal("0")
    assert cash.total_debit < accrual.total_debit
    assert cash.difference == Decimal("0")


def test_one_voucher_per_cost_centre_and_each_one_balances(workspace):
    entity, user, _ = workspace
    register(entity, user, [
        {"employee_id": "E1", "dimensions": _dims(department="Engineering")},
        {"employee_id": "E2", "dimensions": _dims(department="Engineering")},
        {"employee_id": "E3", "dimensions": _dims(department="Sales")},
    ])
    document = build(entity, {"split_mode": "per_group", "group_by": "department"})
    assert {v.scope for v in document.vouchers} == {"Engineering", "Sales"}
    for voucher in document.vouchers:
        assert voucher.difference == Decimal("0"), voucher.scope
    assert document.difference == Decimal("0")


def test_a_consolidated_voucher_tags_each_line_with_its_cost_centre(workspace):
    entity, user, _ = workspace
    register(entity, user, [
        {"employee_id": "E1", "dimensions": _dims(cost_center="CC10")},
        {"employee_id": "E2", "dimensions": _dims(cost_center="CC20")},
    ])
    document = build(entity, {"group_by": "cost_center"})
    assert len(document.vouchers) == 1
    assert {line.cost_center for line in document.vouchers[0].lines} == {"CC10", "CC20"}
    assert document.difference == Decimal("0")


def test_component_level_detail_splits_lines_without_changing_the_totals(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    summary = build(entity)
    detailed = build(entity, {"detail_level": "by_component"})
    assert len(detailed.vouchers[0].lines) > len(summary.vouchers[0].lines)
    assert detailed.total_debit == summary.total_debit
    assert detailed.difference == Decimal("0")


def test_employee_level_detail_posts_a_line_each_and_still_balances(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}, {"employee_id": "E2"}, {"employee_id": "E3"}])
    document = build(entity, {"detail_level": "by_employee"})
    employees = {line.employee_id for line in document.vouchers[0].lines if line.employee_id}
    assert employees == {"E1", "E2", "E3"}
    assert document.difference == Decimal("0")


def test_the_voucher_date_follows_the_rule_the_company_chose(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    assert build(entity).vouchers[0].voucher_date == date(2026, 6, 30)
    assert build(entity, {"voucher_date_rule": "month_start"}).vouchers[0].voucher_date == date(2026, 6, 1)
    assert build(entity, {"voucher_date_rule": "next_month_start"}).vouchers[0].voucher_date == date(2026, 7, 1)


def test_december_rolls_into_the_next_year(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}], period=date(2026, 12, 1))
    document = build(entity, {"voucher_date_rule": "next_month_start"}, period=date(2026, 12, 1))
    assert document.vouchers[0].voucher_date == date(2027, 1, 1)


def test_february_in_a_leap_year_ends_on_the_twenty_ninth(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}], period=date(2028, 2, 1))
    document = build(entity, period=date(2028, 2, 1))
    assert document.vouchers[0].voucher_date == date(2028, 2, 29)


def test_a_rule_filter_restricts_a_line_to_part_of_the_workforce(workspace):
    entity, user, _ = workspace
    register(entity, user, [
        {"employee_id": "E1", "dimensions": _dims(department="Field")},
        {"employee_id": "E2", "dimensions": _dims(department="Head office")},
    ])
    rules = [
        {"label": "Field salaries", "account_code": "5001", "side": "debit",
         "measures": ["gross"], "filters": {"department": ["Field"]}},
        {"label": "Office salaries", "account_code": "5002", "side": "debit",
         "measures": ["gross"], "filters": {"department": ["Head office"]}},
    ]
    document = build(entity, rules=rules)
    by_account = {line.account_code: line.amount for line in document.vouchers[0].lines}
    assert by_account["5001"] > 0 and by_account["5002"] > 0
    assert by_account["5001"] + by_account["5002"] == document.cost_totals["gross"]


# ---------------------------------------------------------------------------
# What it refuses to hide
# ---------------------------------------------------------------------------
def test_a_measure_with_no_account_is_named_and_the_voucher_reports_the_gap(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1", "deductions": {"tds": 5000.0}}])
    rules = [r for r in jv_builder.preset_rules("standard_accrual")
             if "tds" not in r["measures"]]
    document = build(entity, rules=rules)
    assert any("TDS" in w for w in document.warnings)
    assert any(i["code"] == "jv.measure_unmapped" for i in document.issues)
    # And the imbalance is exactly the TDS that has nowhere to go.
    assert document.difference == document.cost_totals["tds"]


def test_an_unbalanced_template_is_reported_in_rupees(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    rules = [{"label": "Salaries", "account_code": "5001", "side": "debit",
              "measures": ["gross"]}]
    document = build(entity, rules=rules)
    codes = {i["code"] for i in document.issues}
    assert "jv.unbalanced" in codes
    unbalanced = next(i for i in document.issues if i["code"] == "jv.unbalanced")
    assert unbalanced["difference"] == float(document.cost_totals["gross"])


def test_a_difference_beyond_tolerance_is_never_rounded_away(workspace):
    # Rounding exists for paise. Forcing a balance on a real mapping error
    # would bury the one thing this check is for.
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    rules = [{"label": "Salaries", "account_code": "5001", "side": "debit",
              "measures": ["gross"]}]
    document = build(entity, {"rounding_mode": "account", "rounding_account": "9999"},
                     rules=rules)
    assert document.difference != Decimal("0")
    assert any(i["code"] == "jv.beyond_tolerance" for i in document.issues)
    assert all(line.account_code != "9999" for v in document.vouchers for line in v.lines)


def _one_voucher(debit: str, credit: str) -> jv_builder.Voucher:
    """A hand-built voucher, so a rounding difference can be an exact amount."""
    return jv_builder.Voucher(
        number="PAY-TEST", voucher_date=PERIOD, voucher_type="Journal",
        scope=None, narration="Test",
        lines=[
            jv_builder.JvLine("5001", "Salaries", "Salaries", "debit", Decimal(debit)),
            jv_builder.JvLine("2001", "Salary payable", "Salary payable", "credit",
                              Decimal(credit)),
        ],
    )


def test_rounding_within_tolerance_posts_to_the_named_account():
    voucher = _one_voucher("1000.50", "1000.00")
    document = jv_builder.JvDocument(period_month=PERIOD, template_name="t")
    jv_builder._apply_rounding(voucher, "account", "9999", Decimal("1.00"), document)
    rounding = [line for line in voucher.lines if line.account_code == "9999"]
    assert len(rounding) == 1
    assert rounding[0].side == "credit" and rounding[0].amount == Decimal("0.50")
    assert voucher.difference == Decimal("0")


def test_rounding_into_the_largest_line_says_which_line_it_touched():
    voucher = _one_voucher("1000.50", "1000.00")
    document = jv_builder.JvDocument(period_month=PERIOD, template_name="t")
    jv_builder._apply_rounding(voucher, "largest_line", None, Decimal("1.00"), document)
    assert voucher.difference == Decimal("0")
    # Absorbing a difference hides it unless the voucher says so out loud.
    assert any(i["code"] == "jv.rounding_absorbed" for i in document.issues)


def test_the_default_rounding_mode_reports_the_difference_and_changes_nothing():
    voucher = _one_voucher("1000.50", "1000.00")
    document = jv_builder.JvDocument(period_month=PERIOD, template_name="t")
    jv_builder._apply_rounding(voucher, "none", "9999", Decimal("1.00"), document)
    assert voucher.difference == Decimal("0.50")
    assert len(voucher.lines) == 2


def test_a_month_with_no_register_says_so_rather_than_posting_nothing_quietly(workspace):
    entity, _, _ = workspace
    document = build(entity, period=date(2020, 1, 1))
    assert any(i["code"] == "jv.no_register" for i in document.issues)
    assert document.vouchers == []


def test_cost_landing_in_unassigned_is_reported(workspace):
    entity, user, _ = workspace
    register(entity, user, [
        {"employee_id": "E1", "dimensions": _dims(department="Engineering")},
        {"employee_id": "E2", "dimensions": _dims()},
    ])
    document = build(entity, {"group_by": "department"})
    assert any(i["code"] == "jv.unassigned_cost_centre" for i in document.issues)


def test_a_rule_with_no_account_code_is_flagged_but_the_totals_still_hold(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    rules = jv_builder.preset_rules("standard_accrual")
    rules[0] = {**rules[0], "account_code": ""}
    document = build(entity, rules=rules)
    assert any(i["code"] == "jv.missing_account_code" for i in document.issues)
    assert document.difference == Decimal("0")


# ---------------------------------------------------------------------------
# Net pay source
# ---------------------------------------------------------------------------
def test_the_stated_net_is_used_when_the_template_asks_for_it(workspace):
    entity, user, _ = workspace
    register(entity, user, [
        {"employee_id": "E1", "components": {"basic": 30000.0, "hra": 15000.0},
         "deductions": {"ee_pf": 1800.0, "pt": 200.0}, "net_pay": Decimal("40000.00")},
    ])
    computed = build(entity)
    stated = build(entity, {"net_pay_source": "stated"})
    salary_payable = next(
        line for line in stated.vouchers[0].lines if line.account_code == "2001"
    )
    assert salary_payable.amount == Decimal("40000.00")
    assert computed.cost_totals["net"] != Decimal("40000.00")


def test_a_stated_net_that_does_not_balance_is_reported_not_forced(workspace):
    # A register deducting a loan instalment it does not itemise will not
    # balance on stated net. That is a real thing to tell the client, and
    # quietly switching back to computed net would hide it.
    entity, user, _ = workspace
    register(entity, user, [
        {"employee_id": "E1", "components": {"basic": 30000.0, "hra": 15000.0},
         "deductions": {"ee_pf": 1800.0}, "net_pay": Decimal("30000.00")},
    ])
    document = build(entity, {"net_pay_source": "stated"})
    assert document.difference != Decimal("0")
    assert any(i["code"] == "jv.unbalanced" for i in document.issues)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fmt", ["generic_csv", "tally_csv", "sap_csv", "zoho_csv"])
def test_every_export_layout_writes_one_row_per_posting_line(workspace, fmt):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    document = build(entity)
    header, rows = jv_builder.export_rows(document, fmt)
    assert len(rows) == sum(len(v.lines) for v in document.vouchers)
    assert all(len(row) == len(header) for row in rows)


def test_the_signed_layout_writes_credits_as_negative(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    document = build(entity)
    _, rows = jv_builder.export_rows(document, "generic_csv", "signed")
    amounts = [row[6] for row in rows]
    assert any(a < 0 for a in amounts) and any(a > 0 for a in amounts)
    # A signed column that sums to zero is the same balance, said differently.
    assert round(sum(amounts), 2) == 0


def test_the_sap_layout_uses_s_and_h_for_debit_and_credit(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    _, rows = jv_builder.export_rows(build(entity), "sap_csv")
    assert {row[4] for row in rows} == {"S", "H"}


def test_the_csv_export_carries_a_header_and_every_line(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    document = build(entity)
    text = jv_builder.export_csv(document, "generic_csv")
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines[0].startswith("Voucher No")
    assert len(lines) == 1 + sum(len(v.lines) for v in document.vouchers)


# ---------------------------------------------------------------------------
# The catalogues the UI reads
# ---------------------------------------------------------------------------
def test_every_supplied_template_produces_a_balancing_voucher(workspace):
    entity, user, _ = workspace
    register(entity, user, [
        {"employee_id": "E1", "deductions": {"tds": 3000.0, "pt": 200.0}},
        {"employee_id": "E2", "dimensions": _dims(cost_center="CC1")},
    ])
    for preset in jv_builder.preset_catalogue():
        overrides = {k: preset[k] for k in
                     ("posting_basis", "split_mode", "detail_level", "group_by",
                      "net_pay_source") if k in preset}
        document = build(entity, overrides, rules=preset["rules"])
        assert document.difference == Decimal("0"), preset["key"]


def test_a_derived_measure_expands_to_the_base_measures_it_stands_for():
    from app.services.cost_model import DEDUCTION_KEYS, EARNING_KEYS, EMPLOYER_KEYS

    assert jv_builder.expand_measures(["gross"]) == set(EARNING_KEYS)
    assert jv_builder.expand_measures(["employer_cost"]) == set(EMPLOYER_KEYS)
    assert jv_builder.expand_measures(["ctc"]) == set(EARNING_KEYS) | set(EMPLOYER_KEYS)
    assert jv_builder.expand_measures(["deductions"]) == set(DEDUCTION_KEYS)
    # Net covers nothing: it is the residual that balances the voucher. Letting
    # it stand in for the deductions netted out of it would hide a template
    # that never credits TDS payable — the error the check is for.
    assert jv_builder.expand_measures(["net"]) == set()


def test_the_option_catalogue_offers_every_measure_a_rule_can_map():
    from app.services.cost_model import MEASURE_KEYS

    keys = {m["key"] for m in jv_builder.option_catalogue()["measures"]}
    assert set(MEASURE_KEYS) <= keys
    assert {"gross", "employer_cost", "ctc", "deductions", "net"} <= keys


def test_a_narration_with_an_unknown_placeholder_still_produces_a_voucher(workspace):
    entity, user, _ = workspace
    register(entity, user, [{"employee_id": "E1"}])
    document = build(entity, {"narration_template": "Payroll {nonsense} {period_label}"})
    assert document.vouchers[0].narration
    assert document.difference == Decimal("0")


def test_the_catalogue_sends_what_each_derived_measure_expands_to(workspace):
    # The editor shows which parts of cost are mapped. It reads this expansion
    # rather than keeping its own copy, which would drift from the check.
    catalogue = {m["key"]: m for m in jv_builder.option_catalogue()["measures"]}
    for key, meta in catalogue.items():
        assert set(meta["parts"]) == jv_builder.expand_measures([key]), key
    assert catalogue["net"]["parts"] == []
    assert catalogue["basic_da"]["parts"] == ["basic_da"]
