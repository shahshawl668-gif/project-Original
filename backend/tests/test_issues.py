"""
Findings as work: owners, due dates, comments, evidence, grouped decisions,
waivers that end, and rule packs.

The fixture register (tests/test_coverage.BASE_ROWS) has known defects, so
every finding worked here is one whose cause is known independently: E002's PF
is ₹100 short (STAT-001), and the shared PAN and UAN raise DATA-006/DATA-007
for all three employees.
"""
from __future__ import annotations

import io
import uuid
from datetime import date, timedelta

import pytest

from app.database import SessionLocal
from app.models import AuditEvent, FindingState, FindingStateEvent
from tests.test_coverage import BASE_ROWS, _register, _run
from tests.test_run_history import PERIOD, PASSWORD, _company, _data, _empty_queue  # noqa: F401


def _member(client, owner_headers, role: str, tag: str) -> dict:
    email = f"{role}-{tag}-{uuid.uuid4().hex[:6]}@issues-example.com"
    inv = _data(client.post("/api/org/invitations", headers=owner_headers, json={"email": email, "role": role}))
    joined = client.post("/api/org/invitations/register", json={"token": inv["token"], "password": PASSWORD})
    assert joined.status_code == 200, joined.text
    return {"Authorization": f"Bearer {joined.json()['data']['access_token']}",
            "X-Entity-Id": owner_headers["X-Entity-Id"], "_email": email}


def _h(headers: dict) -> dict:
    return {k: v for k, v in headers.items() if not k.startswith("_")}


@pytest.fixture()
def company(client):
    headers = _company(client, "iss")
    _run(client, headers, _register(BASE_ROWS))
    return headers


def _issue(client, headers, rule_id, employee_id="E002"):
    page = _data(client.get(f"/api/findings/worklist?rule_id={rule_id}&state=", headers=headers))
    return next(i for i in page["items"] if i["employee_id"] == employee_id)


# ---------------------------------------------------------------------------
# The worklist
# ---------------------------------------------------------------------------
def test_worklist_is_paged_counted_and_filterable(client, company):
    page = _data(client.get("/api/findings/worklist?page_size=2", headers=company))
    assert page["page_size"] == 2 and len(page["items"]) == 2
    assert page["total"] == page["counts"]["open"] > 2
    assert page["unassigned"] == page["total"]
    # Worst first: a critical before any warning.
    assert page["items"][0]["severity"] == "CRITICAL"
    by_rule = _data(client.get("/api/findings/worklist?rule_id=STAT-001", headers=company))
    assert [i["employee_id"] for i in by_rule["items"]] == ["E002"]
    assert by_rule["items"][0]["impact_calculated"] is True
    search = _data(client.get("/api/findings/worklist?q=E003", headers=company))
    assert search["total"] > 0 and all(i["employee_id"] == "E003" for i in search["items"])
    # A data finding has no priced impact, and says so rather than ₹0.
    dup = _issue(client, company, "DATA-006", "E001")
    assert dup["impact_calculated"] is False


def test_another_company_cannot_see_or_touch_an_issue(client, company):
    stranger = _company(client, "iss-x")
    fp = _issue(client, company, "STAT-001")["fingerprint"]
    assert client.get(f"/api/findings/{fp}", headers=stranger).status_code == 404
    assert client.post(f"/api/findings/{fp}/comments", headers=stranger, json={"body": "hi"}).status_code == 404
    out = _data(client.post("/api/findings/bulk", headers=stranger,
                            json={"fingerprints": [fp], "action": "decision", "state": "acknowledged"}))
    assert out["updated"] == 0 and out["skipped"][0]["reason"] == "Not found in this company"


# ---------------------------------------------------------------------------
# Ownership and due dates
# ---------------------------------------------------------------------------
def test_assign_an_owner_and_a_due_date(client, company):
    analyst = _member(client, company, "analyst", "a")
    people = {a["email"]: a for a in _data(client.get("/api/findings/assignees", headers=company))}
    assert analyst["_email"] in people
    fp = _issue(client, company, "STAT-001")["fingerprint"]
    due = (date.today() - timedelta(days=1)).isoformat()
    out = _data(client.patch(f"/api/findings/{fp}/assignment", headers=company,
                             json={"owner_user_id": people[analyst["_email"]]["user_id"], "due_date": due}))
    assert out["owner_email"] == analyst["_email"] and out["due_date"] == due
    assert out["overdue"] is True
    mine = _data(client.get("/api/findings/worklist?owner=me", headers=_h(analyst)))
    assert [i["fingerprint"] for i in mine["items"]] == [fp]
    assert _data(client.get("/api/findings/worklist?overdue=true", headers=company))["total"] == 1
    history = _data(client.get(f"/api/findings/{fp}", headers=company))["history"]
    assert any("Assigned to " + analyst["_email"] in (h["reason"] or "") for h in history)


def test_only_people_who_can_work_the_company_can_own_its_issues(client, company):
    viewer = _member(client, company, "viewer", "v")
    outsider_org = _company(client, "iss-o")
    fp = _issue(client, company, "STAT-001")["fingerprint"]
    emails = {a["email"] for a in _data(client.get("/api/findings/assignees", headers=company))}
    assert viewer["_email"] not in emails
    # A person from another organisation: refused, without saying whether they exist.
    db = SessionLocal()
    try:
        from app.models import OrgMembership
        from app.models import Entity as E
        other_org = db.get(E, uuid.UUID(outsider_org["X-Entity-Id"])).org_id
        outsider = db.query(OrgMembership).filter(OrgMembership.org_id == other_org).first().user_id
    finally:
        db.close()
    r = client.patch(f"/api/findings/{fp}/assignment", headers=company,
                     json={"owner_user_id": str(outsider), "due_date": None})
    assert r.status_code == 400
    # A viewer reads the worklist but cannot change it.
    assert client.get("/api/findings/worklist", headers=_h(viewer)).status_code == 200
    assert client.patch(f"/api/findings/{fp}/assignment", headers=_h(viewer),
                        json={"owner_user_id": None, "due_date": None}).status_code == 403
    assert client.post(f"/api/findings/{fp}/comments", headers=_h(viewer), json={"body": "x"}).status_code == 403


# ---------------------------------------------------------------------------
# Comments and evidence
# ---------------------------------------------------------------------------
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def test_comments_and_attachments_are_kept_with_the_issue(client, company):
    fp = _issue(client, company, "STAT-001")["fingerprint"]
    _data(client.post(f"/api/findings/{fp}/comments", headers=company,
                      json={"body": "Payroll vendor confirmed the PF wage was keyed wrong."}))
    up = _data(client.post(f"/api/findings/{fp}/attachments", headers=company,
                           files={"file": ("vendor-letter.pdf", io.BytesIO(PDF), "application/pdf")}))
    assert up["size"] == len(PDF) and len(up["sha256"]) == 64
    detail = _data(client.get(f"/api/findings/{fp}", headers=company))
    assert detail["comments"][0]["body"].startswith("Payroll vendor")
    assert detail["attachments"][0]["filename"] == "vendor-letter.pdf"
    listed = _issue(client, company, "STAT-001")
    assert listed["comment_count"] == 1 and listed["attachment_count"] == 1
    got = client.get(f"/api/findings/{fp}/attachments/{up['id']}", headers=company)
    assert got.status_code == 200 and got.content == PDF
    assert got.headers["content-type"].startswith("application/pdf")
    stranger = _company(client, "iss-y")
    assert client.get(f"/api/findings/{fp}/attachments/{up['id']}", headers=stranger).status_code == 404


@pytest.mark.parametrize("name,content,why", [
    ("letter.pdf", b"this is not a pdf", "not a valid .pdf"),
    ("script.exe", b"MZ\x90\x00", "Attach a PDF"),
    ("big.txt", b"a" * (5 * 1024 * 1024 + 1), "5 MB"),
    ("empty.csv", b"", "empty"),
])
def test_evidence_is_checked_before_it_is_kept(client, company, name, content, why):
    fp = _issue(client, company, "STAT-001")["fingerprint"]
    r = client.post(f"/api/findings/{fp}/attachments", headers=company,
                    files={"file": (name, io.BytesIO(content), "application/octet-stream")})
    assert r.status_code == 400 and why in r.text


# ---------------------------------------------------------------------------
# Decisions and waivers
# ---------------------------------------------------------------------------
def test_a_waiver_always_ends(client, company):
    fp = _issue(client, company, "STAT-001")["fingerprint"]
    out = _data(client.post(f"/api/findings/{fp}/decision", headers=company,
                            json={"state": "waived", "reason": "Vendor correcting next cycle"}))
    assert out["waived_until"] == (date.today() + timedelta(days=90)).isoformat()
    too_long = (date.today() + timedelta(days=400)).isoformat()
    r = client.post(f"/api/findings/{fp}/decision", headers=company,
                    json={"state": "waived", "reason": "x" * 10, "waived_until": too_long})
    assert r.status_code == 400 and "366" in r.text
    past = (date.today() - timedelta(days=1)).isoformat()
    r = client.post(f"/api/findings/{fp}/decision", headers=company,
                    json={"state": "waived", "reason": "x" * 10, "waived_until": past})
    assert r.status_code == 400


def test_a_lapsed_waiver_reopens_with_a_record_and_is_not_accepted_at_sign_off(client, company):
    fp = _issue(client, company, "STAT-001")["fingerprint"]
    _data(client.post(f"/api/findings/{fp}/decision", headers=company,
                      json={"state": "waived", "reason": "Vendor correcting next cycle"}))
    db = SessionLocal()
    try:  # time passes
        state = db.query(FindingState).filter(FindingState.fingerprint == fp).one()
        state.waived_until = date.today() - timedelta(days=1)
        db.commit()
    finally:
        db.close()
    item = _issue(client, company, "STAT-001")
    assert item["state"] == "open" and item["waived_until"] is None
    history = _data(client.get(f"/api/findings/{fp}", headers=company))["history"]
    # SQLite timestamps resolve to the second, so find the event rather than rely on order.
    lapse = next(h for h in history if "Waiver expired" in (h["reason"] or ""))
    assert lapse["from_state"] == "waived" and lapse["to_state"] == "open"
    assert lapse["actor_email"] is None
    preview = _data(client.get(f"/api/signoff/{PERIOD}/preview", headers=company))
    assert fp in {f["fingerprint"] for f in preview["outstanding_findings"]}
    assert fp not in {f["fingerprint"] for f in preview["accepted_findings"]}


def test_resolving_needs_a_reason(client, company):
    fp = _issue(client, company, "STAT-001")["fingerprint"]
    r = client.post(f"/api/findings/{fp}/decision", headers=company, json={"state": "resolved"})
    assert r.status_code == 400
    ok = client.post(f"/api/findings/{fp}/decision", headers=company,
                     json={"state": "resolved", "reason": "Corrected in the supplementary run"})
    assert ok.status_code == 200 and ok.json()["data"]["state"] == "resolved"


def test_a_grouped_decision_is_one_event_per_finding(client, company):
    page = _data(client.get("/api/findings/worklist?rule_id=DATA-006", headers=company))
    fps = [i["fingerprint"] for i in page["items"]]
    assert len(fps) == 3
    r = client.post("/api/findings/bulk", headers=company, json={
        "fingerprints": fps, "action": "decision", "state": "waived"})
    assert r.status_code == 400  # a waiver states its grounds, even in bulk
    out = _data(client.post("/api/findings/bulk", headers=company, json={
        "fingerprints": [*fps, "no-such-fingerprint"], "action": "decision", "state": "waived",
        "reason": "Shared PAN belongs to a family trust; confirmed with tax team"}))
    assert out["updated"] == 3 and len(out["skipped"]) == 1
    db = SessionLocal()
    try:
        ids = [s.id for s in db.query(FindingState).filter(FindingState.fingerprint.in_(fps))]
        events = db.query(FindingStateEvent).filter(
            FindingStateEvent.state_id.in_(ids), FindingStateEvent.to_state == "waived").all()
        assert len(events) == 3
        assert {e.reason for e in events} == {"Shared PAN belongs to a family trust; confirmed with tax team"}
        assert db.query(AuditEvent).filter(AuditEvent.action == "findings.bulk_decision").count() >= 1
    finally:
        db.close()
    # Running the same decision again changes nothing and says why.
    again = _data(client.post("/api/findings/bulk", headers=company, json={
        "fingerprints": fps, "action": "decision", "state": "waived", "reason": "again, same"}))
    assert again["updated"] == 0 and again["skipped"][0]["reason"] == "Already waived"


def test_bulk_assignment(client, company):
    analyst = _member(client, company, "analyst", "b")
    uid = next(a["user_id"] for a in _data(client.get("/api/findings/assignees", headers=company))
               if a["email"] == analyst["_email"])
    fps = [i["fingerprint"] for i in _data(client.get("/api/findings/worklist?rule_id=DATA-007",
                                                      headers=company))["items"]]
    due = (date.today() + timedelta(days=7)).isoformat()
    out = _data(client.post("/api/findings/bulk", headers=company, json={
        "fingerprints": fps, "action": "assign", "owner_user_id": uid, "due_date": due}))
    assert out["updated"] == len(fps) == 3
    mine = _data(client.get("/api/findings/worklist?owner=me&sort=due_date", headers=_h(analyst)))
    assert {i["fingerprint"] for i in mine["items"]} == set(fps)
    assert all(i["due_date"] == due and not i["overdue"] for i in mine["items"])


# ---------------------------------------------------------------------------
# Rule packs
# ---------------------------------------------------------------------------
def test_rule_packs_explain_what_they_need_and_how_the_last_run_went(client, company):
    packs = {p["key"]: p for p in _data(client.get("/api/validation-matrix/packs", headers=company))}
    pf = packs["pf"]
    assert pf["state"] == "on" and "STAT-001" in {c["rule_id"] for c in pf["checks"]}
    assert any(r["input"] == "PF employee column" for r in pf["required_inputs"])
    assert pf["last_run"]["totals"]["failed"] >= 1
    assert packs["reconciliation"]["checks"] == [] and packs["reconciliation"]["elsewhere"]
    assert packs["minimum_wage"]["last_run"]["totals"]["cannot_validate"] > 0


def test_a_pack_switched_off_reports_disabled_and_is_audited(client, company):
    r = client.put("/api/validation-matrix/packs/pf", headers=company, json={"enabled": False, "reason": "short"})
    assert r.status_code == 422  # a reason worth reading
    out = _data(client.put("/api/validation-matrix/packs/pf", headers=company,
                           json={"enabled": False, "reason": "PF handled by the group's PF trust"}))
    assert out["changed"] == 7
    run_id = _run(client, company, _register(BASE_ROWS))
    detail = _data(client.get(f"/api/validation/runs/{run_id}/employees/E002", headers=company))
    assert detail["result"]["coverage"]["STAT-001"]["outcome"] == "disabled"
    packs = {p["key"]: p for p in _data(client.get("/api/validation-matrix/packs", headers=company))}
    assert packs["pf"]["state"] == "off"
    assert client.put("/api/validation-matrix/packs/reconciliation", headers=company,
                      json={"enabled": False, "reason": "not a validation pack"}).status_code == 404
    analyst = _member(client, company, "analyst", "c")
    assert client.put("/api/validation-matrix/packs/pf", headers=_h(analyst),
                      json={"enabled": True, "reason": "turning it back on"}).status_code == 403
    db = SessionLocal()
    try:
        assert db.query(AuditEvent).filter(AuditEvent.action == "rule_pack.disabled").count() >= 1
    finally:
        db.close()


def test_a_waiver_given_before_waivers_had_to_end_is_flagged_not_rewritten(client, company):
    fp = _issue(client, company, "STAT-001")["fingerprint"]
    _data(client.post(f"/api/findings/{fp}/decision", headers=company,
                      json={"state": "waived", "reason": "Accepted under the old rules"}))
    db = SessionLocal()
    try:  # as a pre-upgrade waiver would read
        state = db.query(FindingState).filter(FindingState.fingerprint == fp).one()
        state.waived_until = None
        db.commit()
    finally:
        db.close()
    item = _issue(client, company, "STAT-001")
    assert item["state"] == "waived" and item["waived_until"] is None
    assert item["waiver_open_ended"] is True
