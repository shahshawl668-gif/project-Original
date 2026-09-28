"""
Company rules, version two: nested logic, arithmetic, lookups, applicability,
missing data, the life of a version, conflicts, import and copying.

The unit tests evaluate rules against hand-built rows whose answers are worked
out here, in the comments, not by the engine. The API tests use the coverage
fixture register (every employee paid 30 days of June, gross 31,000 / 16,500
/ 12,400 — see tests/test_coverage._row).
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from app.database import SessionLocal
from app.models import AuditEvent, ValidationRuleVersion
from app.services import validation_matrix as vm
from tests.test_coverage import BASE_ROWS, _register, _run
from tests.test_run_history import PERIOD, _company, _data


@pytest.fixture(autouse=True)
def _empty_queue(request):
    """As in the history tests, but only once the app (and its tables) exist."""
    request.getfixturevalue("client")
    from app.models import ValidationJob

    db = SessionLocal()
    try:
        db.query(ValidationJob).filter(ValidationJob.state.in_(("queued", "running"))).update(
            {"state": "cancelled"}, synchronize_session=False)
        db.commit()
    finally:
        db.close()


def F(key):
    return {"source": "field", "key": key}


def C(key):
    return {"source": "component", "key": key}


def L(value):
    return {"source": "literal", "value": str(value)}


def X(expression):
    return {"source": "expr", "value": expression}


def cmp(left, op, right, tol="0"):
    return {"left": left, "operator": op, "right": right, "tolerance": tol}


def rule(assertion, condition=None, **kw):
    base = {
        "id": uuid.uuid4(), "rule_key": "CUST-T", "version": 1, "name": "t", "state": None,
        "condition": condition, "assertion": assertion, "applies_to": None, "on_missing": "cannot_validate",
        "severity": "WARNING", "blocks_signoff": False, "source_reference": None, "suggested_fix": None,
        "responsible_team": None, "effective_from": date(2026, 1, 1), "effective_to": None, "status": "published",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def row(**kw):
    base = {"employee_id": "E1", "employee_name": "One", "components": {}, "deductions": {}}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Three-valued logic and nesting
# ---------------------------------------------------------------------------
def test_missing_input_is_unknown_not_false():
    any_group = {"mode": "any", "items": [cmp(F("tds"), "gt", L(0)), cmp(F("pan"), "present", L(1))]}
    # tds 0 (false) and pan missing (unknown): "any" cannot be decided.
    assert vm.condition_result(any_group, row(tds=0)) is None
    # pan present: true regardless of the other part.
    assert vm.condition_result(any_group, row(pan="ABCPE1234F")) is True
    all_group = {"mode": "all", "items": [cmp(F("tds"), "gt", L(0)), cmp(F("pan"), "present", L(1))]}
    # One part false decides "all" even though the other is unknown.
    assert vm.condition_result(all_group, row(tds=0)) is False


def test_nested_groups_and_negation():
    # (lop_days > 2 AND NOT (employment_type in Contract|Trainee)) OR paid_days < 10
    node = {"mode": "any", "items": [
        {"mode": "all", "items": [
            cmp(F("lop_days"), "gt", L(2)),
            {"mode": "all", "negate": True, "items": [cmp(F("employment_type"), "in", L("Contract|Trainee"))]},
        ]},
        cmp(F("paid_days"), "lt", L(10)),
    ]}
    assert vm.condition_result(node, row(lop_days=3, employment_type="Permanent", paid_days=27)) is True
    assert vm.condition_result(node, row(lop_days=3, employment_type="Contract", paid_days=27)) is False
    assert vm.condition_result(node, row(lop_days=0, employment_type="Contract", paid_days=5)) is True


def test_a_condition_that_does_not_hold_means_the_rule_does_not_apply():
    r = rule(cmp(F("pan"), "present", L(1)), condition=cmp(F("tds"), "gt", L(0)))
    assert vm.evaluate(r, row(tds=0)) is None            # no TDS: rule out of scope
    # TDS but no PAN: flagged. A missing required value is reported as an input
    # that could not be checked (the engine's long-standing reading of "present").
    finding = vm.evaluate(r, row(tds=500))
    assert finding and finding["evidence"]["unverifiable"] is True
    assert vm.evaluate(r, row(tds=500, pan="ABCPE1234F")) is None


# ---------------------------------------------------------------------------
# Arithmetic and lookups
# ---------------------------------------------------------------------------
def test_expression_operand():
    r = rule(cmp(X("basic / gross * 100"), "gte", L(40)))
    # 20,000 / 50,000 = 40% → passes; 15,000 / 50,000 = 30% → fails at 30.00.
    assert vm.evaluate(r, row(components={"basic": 20000, "hra": 30000}, gross=50000)) is None
    f = vm.evaluate(r, row(components={"basic": 15000, "hra": 35000}, gross=50000))
    assert f["actual_value"] == "30.00" and f["expected_value"] == "40"


def test_division_by_zero_is_unknown_not_a_pass():
    r = rule(cmp(X("basic / gross * 100"), "gte", L(40)))
    f = vm.evaluate(r, row(components={"basic": 0}, gross=0))
    assert f["reason"].startswith("Cannot validate") and f["evidence"]["unverifiable"] is True


def test_previous_period_lookup_and_missing_data_behaviour():
    swing = cmp(X("abs(gross - prev_gross) / prev_gross * 100"), "lte", L(20))
    last = {"components": {}, "deductions": {}, "gross": 50000}
    # 60,000 against 50,000 is 20% → passes; 61,000 is 22% → fails.
    assert vm.evaluate(rule(swing), row(gross=60000, _previous=last)) is None
    assert vm.evaluate(rule(swing), row(gross=61000, _previous=last))["actual_value"] == "22.00"
    # A joiner has no previous month: skip, cannot-validate or fail, as the rule says.
    joiner = row(gross=61000, _previous=None)
    assert vm.evaluate(rule(swing, on_missing="skip"), joiner) is None
    assert vm.evaluate(rule(swing), joiner)["evidence"]["unverifiable"] is True
    failed = vm.evaluate(rule(swing, on_missing="fail"), joiner)
    assert failed["reason"].startswith("Treated as a failure") and failed["evidence"]["unverifiable"] is False
    # A previous-month operand reads the same kind of input as this month.
    prev_basic = cmp(C("basic"), "gte", {"source": "previous", "of": "component", "key": "basic"})
    assert vm.evaluate(rule(prev_basic), row(components={"basic": 900}, _previous={"components": {"basic": 1000}}))


def test_master_lookup():
    r = rule(cmp(F("department"), "eq", {"source": "master", "key": "department"}))
    assert vm.evaluate(r, row(department="Sales", _master={"department": "sales"})) is None
    assert vm.evaluate(r, row(department="Sales", _master={"department": "Ops"}))
    assert vm.evaluate(r, row(department="Sales", _master=None))["evidence"]["unverifiable"]


def test_applicability_by_dimension():
    r = rule(cmp(F("lop_days"), "lte", L(2)), applies_to={"department": ["Sales"]})
    assert vm.evaluate(r, row(department="Ops", lop_days=5)) is None                  # out of scope
    assert vm.evaluate(r, row(department="Sales", lop_days=5))                        # in scope, fails
    assert vm.evaluate(r, row(lop_days=5, _master={"department": "Sales"}))           # read from master
    unknown = vm.evaluate(r, row(lop_days=5))
    assert "department is not recorded" in unknown["reason"]


def test_retired_version_governs_only_its_months():
    v1 = rule(cmp(F("lop_days"), "lte", L(2)), status="retired", effective_to=date(2026, 3, 31))

    class Q:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *a):
            return self

        def all(self):
            return self.rows

    db = SimpleNamespace(query=lambda _m: Q([v1]))
    assert vm.published_for(db, None, date(2026, 2, 1)) == [v1]
    assert vm.published_for(db, None, date(2026, 4, 1)) == []


# ---------------------------------------------------------------------------
# Safety: never unrestricted code
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("expression", [
    "__import__('os').system('id')",
    "gross.__class__",
    "open('/etc/passwd')",
    "[x for x in range(10)]",
    "lambda: 1",
    "undefined_name * 2",
])
def test_expressions_cannot_escape(expression):
    with pytest.raises(ValueError):
        vm.validate_comparison(cmp(X(expression), "gt", L(0)), {"basic"})


def test_depth_and_size_are_bounded():
    leaf = cmp(F("lop_days"), "lte", L(2))
    deep = {"mode": "all", "items": [{"mode": "all", "items": [{"mode": "all", "items": [{"mode": "all", "items": [leaf]}]}]}]}
    with pytest.raises(ValueError, match="nest"):
        vm.validate_condition(deep, set())
    wide = {"mode": "all", "items": [leaf] * 21}
    with pytest.raises(ValueError, match="at most"):
        vm.validate_condition(wide, set())


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------
def test_conflicts_are_detected_within_scope():
    a = rule(cmp(F("net_pay"), "gte", L(100)), rule_key="CUST-A")
    b = rule(cmp(F("net_pay"), "lte", L(50)), rule_key="CUST-B")
    kinds = {c["kind"] for c in vm.conflicts([a, b], set())}
    assert kinds == {"contradiction"}
    # Different departments: never in force for the same employee.
    a2 = rule(cmp(F("net_pay"), "gte", L(100)), rule_key="CUST-A", applies_to={"department": ["Sales"]})
    b2 = rule(cmp(F("net_pay"), "lte", L(50)), rule_key="CUST-B", applies_to={"department": ["Ops"]})
    assert vm.conflicts([a2, b2], set()) == []
    # Not overlapping in time.
    b3 = rule(cmp(F("net_pay"), "lte", L(50)), rule_key="CUST-B",
              effective_from=date(2025, 1, 1), effective_to=date(2025, 12, 31))
    assert vm.conflicts([a, b3], set()) == []
    dup = rule(cmp(F("net_pay"), "gte", L(100)), rule_key="CUST-C")
    assert {c["kind"] for c in vm.conflicts([a, dup], set())} == {"duplicate"}
    broken = rule(cmp(C("special_allowance"), "gte", L(0)), rule_key="CUST-D")
    assert {c["kind"] for c in vm.conflicts([broken], {"basic"})} == {"broken_reference"}


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------
@pytest.fixture()
def company(client):
    headers = _company(client, "rv2")
    _run(client, headers, _register(BASE_ROWS))
    return headers


def body(key="CUST-PAID", assertion=None, **kw):
    out = {
        "rule_key": key, "name": "Paid days policy", "effective_from": "2026-01-01",
        "change_reason": "Company policy agreed at the payroll review",
        "assertion": assertion or cmp(F("paid_days"), "lte", L(29)), "severity": "WARNING",
    }
    out.update(kw)
    return out


def _publish(client, headers, rule_id):
    _data(client.post(f"/api/validation-matrix/{rule_id}/submit", headers=headers))
    return client.post(f"/api/validation-matrix/{rule_id}/publish", headers=headers)


def test_advanced_rule_is_stored_and_listed(client, company):
    group = {"mode": "any", "negate": False, "items": [
        cmp(F("lop_days"), "gt", L(2)),
        {"mode": "all", "negate": True, "items": [cmp(F("pan"), "present", L(1))]},
    ]}
    created = _data(client.post("/api/validation-matrix", headers=company, json=body(
        condition_group=group, applies_to={"department": ["Sales", " "]}, on_missing="skip",
        editor_mode="advanced")))
    assert created["condition"]["mode"] == "any" and created["condition"]["items"][1]["negate"] is True
    assert created["applies_to"] == {"department": ["Sales"]}
    assert created["on_missing"] == "skip" and created["editor_mode"] == "advanced"
    bad = client.post("/api/validation-matrix", headers=company, json=body(
        key="CUST-BAD", assertion=cmp(X("__import__('os')"), "gt", L(0))))
    assert bad.status_code in (400, 422)
    unknown = client.post("/api/validation-matrix", headers=company, json=body(
        key="CUST-BAD2", assertion=cmp(X("bonus_pool / 2"), "gt", L(0))))
    assert unknown.status_code == 400 and "unknown names" in unknown.text


def test_impact_preview_on_a_whole_month(client, company):
    v1 = _data(client.post("/api/validation-matrix", headers=company, json=body()))
    # Everyone was paid 30 days; "at most 29" flags all three.
    impact = _data(client.post(f"/api/validation-matrix/{v1['id']}/impact", headers=company,
                               json={"period_month": PERIOD}))
    assert impact["employees_evaluated"] == 3
    assert impact["would_flag"] == 3 and impact["compared_with"] is None
    assert _publish(client, company, v1["id"]).status_code == 200
    v2 = _data(client.post(f"/api/validation-matrix/{v1['id']}/clone", headers=company,
                           json={"change_reason": "Allow a full month of paid days"}))
    assert v2["version"] == 2 and v2["cloned_from_id"] == v1["id"] and v2["status"] == "draft"
    # Relax v2 by rolling a copy with a new assertion through create (a new version of the same key).
    v3 = _data(client.post("/api/validation-matrix", headers=company, json=body(
        assertion=cmp(F("paid_days"), "lte", L(31)), change_reason="Allow a full month of paid days")))
    impact = _data(client.post(f"/api/validation-matrix/{v3['id']}/impact", headers=company,
                               json={"period_month": PERIOD}))
    assert impact["compared_with"]["version"] == 1
    assert impact["currently_flagged"] == 3 and impact["no_longer_flagged"] == 3 and impact["would_flag"] == 0


def test_the_life_of_a_version(client, company):
    v1 = _data(client.post("/api/validation-matrix", headers=company, json=body()))
    _data(client.post(f"/api/validation-matrix/{v1['id']}/submit", headers=company))
    returned = _data(client.post(f"/api/validation-matrix/{v1['id']}/return", headers=company,
                                 json={"reason": "Needs a policy reference first"}))
    assert returned["status"] == "draft"
    assert _publish(client, company, v1["id"]).status_code == 200
    v2 = _data(client.post("/api/validation-matrix", headers=company, json=body(
        assertion=cmp(F("paid_days"), "lte", L(31)), effective_from="2026-07-01")))
    diff = _data(client.get(f"/api/validation-matrix/compare?a={v1['id']}&b={v2['id']}", headers=company))
    assert {c["field"] for c in diff["changes"]} == {"assertion", "effective_from"}
    back = _data(client.post(f"/api/validation-matrix/{v1['id']}/rollback", headers=company,
                             json={"reason": "The relaxed limit was agreed in error"}))
    assert back["version"] == 3 and back["assertion"] == v1["assertion"] and back["status"] == "draft"
    assert "Rollback to v1" in back["change_reason"]
    assert client.post(f"/api/validation-matrix/{back['id']}/rollback", headers=company,
                       json={"reason": "already the latest one"}).status_code == 409
    retired = _data(client.post(f"/api/validation-matrix/{v1['id']}/retire", headers=company,
                                json={"effective_to": "2026-05-31", "reason": "Replaced by the July policy"}))
    assert retired["status"] == "retired" and retired["effective_to"] == "2026-05-31"
    # Retired: still in force for May, not for June.
    db = SessionLocal()
    try:
        entity_id = uuid.UUID(company["X-Entity-Id"])
        assert [r.version for r in vm.published_for(db, entity_id, date(2026, 5, 1))] == [1]
        assert vm.published_for(db, entity_id, date(2026, 6, 1)) == []
        actions = {a for (a,) in db.query(AuditEvent.action).filter(AuditEvent.entity_id == entity_id)}
        assert {"validation_rule.returned", "validation_rule.rollback_drafted", "validation_rule.retired"} <= actions
    finally:
        db.close()


def test_a_contradicting_rule_cannot_be_published(client, company):
    a = _data(client.post("/api/validation-matrix", headers=company, json=body(
        key="CUST-MIN", assertion=cmp(F("paid_days"), "gte", L(20)))))
    assert _publish(client, company, a["id"]).status_code == 200
    b = _data(client.post("/api/validation-matrix", headers=company, json=body(
        key="CUST-MAX", assertion=cmp(F("paid_days"), "lte", L(10)))))
    listed = _data(client.get("/api/validation-matrix/conflicts", headers=company))
    assert listed == []  # b is a draft; drafts do not conflict until submitted
    refused = _publish(client, company, b["id"])
    assert refused.status_code == 409 and "cannot both be satisfied" in refused.text
    assert {c["kind"] for c in _data(client.get("/api/validation-matrix/conflicts", headers=company))} == {"contradiction"}


def _csv(rows: list[dict]) -> bytes:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return out.getvalue().encode()


def test_import_previews_then_creates_drafts_only(client, company):
    import json as _json

    _data(client.post("/api/validation-matrix", headers=company, json=body()))
    exported = client.get("/api/validation-matrix/export.csv", headers=company)
    assert exported.status_code == 200
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert rows[0]["rule_key"] == "CUST-PAID"
    unchanged = dict(rows[0])
    changed = dict(rows[0], rule_key="CUST-PAID", name="Paid days policy (revised)")
    new = dict(rows[0], rule_key="CUST-NEW", assertion=_json.dumps(cmp(F("lop_days"), "lte", L(3))))
    broken = dict(rows[0], rule_key="CUST-BROKEN", assertion=_json.dumps(cmp(C("no_such_component"), "gt", L(0))))

    def send(content, dry_run=True, name="rules.csv"):
        return client.post(f"/api/validation-matrix/import?dry_run={str(dry_run).lower()}", headers=company,
                           files={"file": (name, io.BytesIO(content), "text/csv")})

    preview = _data(send(_csv([unchanged, new, broken])))
    assert preview["summary"] == {"new": 1, "new_version": 0, "unchanged": 1, "error": 1}
    assert "not configured" in next(r for r in preview["rows"] if r["rule_key"] == "CUST-BROKEN")["errors"][0]
    assert send(_csv([unchanged, new, broken]), dry_run=False).status_code == 422
    preview = _data(send(_csv([changed, new])))
    assert preview["summary"]["new_version"] == 1 and preview["rows"][0]["changes"] == ["name"]
    done = _data(send(_csv([changed, new]), dry_run=False))
    assert sorted(done["created"]) == ["CUST-NEW v1", "CUST-PAID v2"]
    listed = _data(client.get("/api/validation-matrix", headers=company))
    assert all(r["status"] == "draft" for r in listed)

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(list(new))
    ws.append(list(dict(new, rule_key="CUST-XL").values()))
    buf = io.BytesIO()
    wb.save(buf)
    xl = _data(send(buf.getvalue(), name="rules.xlsx"))
    assert xl["summary"]["new"] == 1


def test_copy_to_another_company_is_controlled(client, company):
    rule_v = _data(client.post("/api/validation-matrix", headers=company, json=body()))
    component_rule = _data(client.post("/api/validation-matrix", headers=company, json=body(
        key="CUST-BASIC", assertion=cmp(C("basic"), "gt", L(0)))))
    sibling = _data(client.post("/api/org/entities", headers=company, json={"name": "Sibling Co", "primary_state": "Kerala"}))
    stranger = _company(client, "rv2-x")
    request = {"rule_ids": [rule_v["id"], component_rule["id"]],
               "target_entity_ids": [sibling["id"], stranger["X-Entity-Id"], str(uuid.uuid4())],
               "change_reason": "Group-wide paid days policy"}
    plan = _data(client.post("/api/validation-matrix/copy", headers=company, json=request))
    by_target = {t["entity_id"]: t for t in plan["targets"]}
    assert by_target[stranger["X-Entity-Id"]]["status"] == "not_available"
    sib = by_target[sibling["id"]]
    assert sib["status"] == "ok"
    assert {r["rule_key"]: r["status"] for r in sib["rules"]} == {"CUST-PAID": "will_copy", "CUST-BASIC": "skipped"}
    done = _data(client.post("/api/validation-matrix/copy", headers=company, json={**request, "dry_run": False}))
    assert {r["rule_key"]: r["status"] for r in {t["entity_id"]: t for t in done["targets"]}[sibling["id"]]["rules"]} == {
        "CUST-PAID": "copied", "CUST-BASIC": "skipped"}
    sib_headers = {**company, "X-Entity-Id": sibling["id"]}
    copied = _data(client.get("/api/validation-matrix", headers=sib_headers))
    assert [(r["rule_key"], r["status"]) for r in copied] == [("CUST-PAID", "draft")]
    assert "Copied from" in copied[0]["change_reason"]
    assert _data(client.get("/api/validation-matrix", headers=stranger)) == []
    db = SessionLocal()
    try:
        assert db.query(AuditEvent).filter(AuditEvent.action == "validation_rule.copied_in",
                                           AuditEvent.entity_id == uuid.UUID(sibling["id"])).count() == 1
        assert db.query(ValidationRuleVersion).filter(
            ValidationRuleVersion.entity_id == uuid.UUID(stranger["X-Entity-Id"])).count() == 0
    finally:
        db.close()


def test_rule_templates_say_what_they_need(client, company):
    templates = {t["key"]: t for t in _data(client.get("/api/validation-matrix/templates", headers=company))}
    assert templates["basic_share"]["available"] is True  # the fixture configures Basic
    for t in templates.values():
        payload = body(key="CUST-" + t["key"].upper().replace("_", "")[:20], **t["rule"])
        r = client.post("/api/validation-matrix", headers=company, json=payload)
        assert r.status_code == 200, (t["key"], r.text)


def test_configuration_copies_between_companies_with_a_preview(client, company):
    here = _data(client.get("/api/components", headers=company))
    assert len(here) >= 3
    sibling = _data(client.post("/api/org/entities", headers=company, json={"name": "Sibling Two", "primary_state": "Goa"}))
    sib = {**company, "X-Entity-Id": sibling["id"]}
    request = {"source_entity_id": company["X-Entity-Id"], "sections": ["components"],
               "reason": "Same salary structure across the group"}
    plan = _data(client.post("/api/config/bundle/copy", headers=sib, json=request))
    assert plan["preview"] is True
    assert plan["sections"]["components"] == {"from_source": len(here), "replacing_here": 0}
    assert _data(client.get("/api/components", headers=sib)) == []  # a preview changes nothing
    done = _data(client.post("/api/config/bundle/copy", headers=sib, json={**request, "dry_run": False}))
    assert done["preview"] is False
    copied = _data(client.get("/api/components", headers=sib))
    assert sorted(c["component_name"] for c in copied) == sorted(c["component_name"] for c in here)
    stranger = _company(client, "rv2-cfg")
    assert client.post("/api/config/bundle/copy", headers=stranger,
                       json={**request, "dry_run": True}).status_code == 404
    assert client.post("/api/config/bundle/copy", headers=sib,
                       json={**request, "sections": ["no_such_section"]}).status_code == 400
    db = SessionLocal()
    try:
        actions = {(a, str(e)) for a, e in db.query(AuditEvent.action, AuditEvent.entity_id)
                   .filter(AuditEvent.action.in_(("config.copied_in", "config.copied_out")))}
        assert ("config.copied_in", sibling["id"].replace("-", "")) in {(a, e.replace("-", "")) for a, e in actions}
        assert ("config.copied_out", company["X-Entity-Id"].replace("-", "")) in {(a, e.replace("-", "")) for a, e in actions}
    finally:
        db.close()


def test_impact_says_who_was_skipped_rather_than_reporting_a_pass(client, company):
    # Narrowed to a department nobody has on record, skipping missing inputs:
    # nobody fails, and the preview must say that all three were skipped.
    v = _data(client.post("/api/validation-matrix", headers=company, json=body(
        key="CUST-SKIP", applies_to={"department": ["Finance"]}, on_missing="skip", editor_mode="advanced")))
    out = _data(client.post(f"/api/validation-matrix/{v['id']}/impact", headers=company, json={"period_month": PERIOD}))
    assert out["would_flag"] == 0
    assert out["outcomes"] == {"passed": 0, "failed": 0, "cannot_validate": 0, "skipped": 3, "out_of_scope": 0}
