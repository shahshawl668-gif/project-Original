"""
Disbursement validation through the API: who may check a payment file, see
its findings, download the clean file and approve its release — and what an
approval refuses.

All data is synthetic (tools/disbursement_synth.py).
"""
from __future__ import annotations

import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta
from functools import cache

from app.database import SessionLocal
from app.models import AuditEvent, DisbursementRun
from tools.disbursement_synth import generate

PASSWORD = "Passw0rd!x"
SEED = 20260901


def _data(r):
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _company(client, tag: str) -> dict:
    email = f"dsb-{tag}-{uuid.uuid4().hex[:6]}@dsb-example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD,
                                              "company_name": f"Disbursement {tag} Pvt Ltd"})
    headers = {"Authorization": f"Bearer {_data(r)['access_token']}"}
    headers["X-Entity-Id"] = _data(client.post("/api/org/entities", headers=headers, json={
        "name": f"Disbursement {tag}", "primary_state": "Karnataka"}))["id"]
    return headers


def _member(client, owner: dict, role: str) -> dict:
    email = f"dsb-{role}-{uuid.uuid4().hex[:6]}@dsb-example.com"
    inv = _data(client.post("/api/org/invitations", headers=owner, json={"email": email, "role": role}))
    joined = client.post("/api/org/invitations/register", json={"token": inv["token"], "password": PASSWORD})
    assert joined.status_code == 200, joined.text
    return {"Authorization": f"Bearer {joined.json()['data']['access_token']}", "X-Entity-Id": owner["X-Entity-Id"]}


@cache
def _pack(scenario: str, layout: str = "generic"):
    return generate(120, SEED, scenario, layout)


def _check(client, headers, scenario="B", layout="generic", period="2026-09", skip=(), **form):
    pack = _pack(scenario, layout)
    files = {slot: (name, io.BytesIO(content)) for slot, (name, content) in pack.files.items() if slot not in skip}
    data = {"period": period, "profile_key": pack.profile, **form}
    if pack.value_date and "value_date" not in data:
        data["value_date"] = pack.value_date.isoformat()
    return client.post("/api/disbursement/runs", headers=headers, data=data, files=files)


def _settings(client, headers, **overrides):
    pack = _pack("B")
    return client.put("/api/disbursement/settings", headers=headers, json={
        "profile_key": pack.profile, "overrides": {**pack.settings, **overrides}})


def _approve(client, headers, run: dict, **over):
    body = {"approver_name": "Approver One", "fingerprint": run["clean_sha256"],
            "acknowledged": run["unchecked"], **over}
    return client.post(f"/api/disbursement/runs/{run['id']}/approve", headers=headers, json=body)


def test_the_catalogue_lists_every_check_and_layout(client):
    owner = _company(client, "cat")
    cat = _data(client.get("/api/disbursement/catalogue", headers=owner))
    assert [r["rule_id"] for r in cat["rules"]] == [f"DSB-{i:02d}" for i in range(1, 18)]
    assert {p["key"] for p in cat["profiles"]} == {"generic", "darwinbox_style"}
    assert {t["key"] for t in cat["templates"]} == {"generic_csv", "batch_pipe_hdt"}
    assert [i["slot"] for i in cat["inputs"] if i["required"]] == ["bank_file", "register"]


def test_a_check_is_stored_with_its_report_and_every_download_matches(client):
    owner = _company(client, "run")
    assert _settings(client, owner).status_code == 200
    run = _data(_check(client, owner))
    assert run["verdict"] == "RELEASE_WITH_HOLDS" and run["status"] == "checked"
    assert run["clean_available"] and len(run["clean_sha256"]) == 64

    detail = _data(client.get(f"/api/disbursement/runs/{run['id']}", headers=owner))
    assert detail["report"]["findings"] and detail["held"] and detail["can_approve"] is True
    assert detail["report"]["verdict"] == run["verdict"]

    clean = client.get(f"/api/disbursement/runs/{run['id']}/download/clean", headers=owner)
    assert clean.status_code == 200 and clean.headers["cache-control"] == "no-store"
    assert hashlib.sha256(clean.content).hexdigest() == run["clean_sha256"]
    for kind, magic in (("exceptions.csv", b"\xef\xbb\xbf"), ("exceptions.xlsx", b"PK"), ("summary.pdf", b"%PDF")):
        got = client.get(f"/api/disbursement/runs/{run['id']}/download/{kind}", headers=owner)
        assert got.status_code == 200 and got.content.startswith(magic), kind
    assert client.get(f"/api/disbursement/runs/{run['id']}/download/other", headers=owner).status_code == 404

    history = _data(client.get("/api/disbursement/runs", headers=owner))["runs"]
    assert [r["id"] for r in history] == [run["id"]] and "report" not in history[0]

    db = SessionLocal()
    try:
        actions = [a for (a,) in db.query(AuditEvent.action).filter(
            AuditEvent.object_id == run["id"]).all()]
    finally:
        db.close()
    assert actions.count("disbursement.checked") == 1 and actions.count("disbursement.downloaded") == 4


def test_a_stopped_file_has_no_clean_copy_and_cannot_be_approved(client):
    owner = _company(client, "stop")
    _settings(client, owner)
    run = _data(_check(client, owner, scenario="C"))
    assert run["verdict"] == "DO_NOT_RELEASE" and run["clean_sha256"] is None
    assert client.get(f"/api/disbursement/runs/{run['id']}/download/clean", headers=owner).status_code == 409
    refused = _approve(client, owner, run, fingerprint="0" * 64)
    assert refused.status_code == 409 and "must not be released" in refused.json()["error"]["detail"]
    # The exception report and summary still exist: they say why.
    assert client.get(f"/api/disbursement/runs/{run['id']}/download/summary.pdf", headers=owner).status_code == 200


def test_approval_needs_the_right_file_and_every_unchecked_check_acknowledged(client):
    owner = _company(client, "appr")
    _settings(client, owner)
    run = _data(_check(client, owner, scenario="D"))
    assert run["unchecked"], "scenario D leaves checks unrun"

    wrong = _approve(client, owner, run, fingerprint="f" * 64)
    assert wrong.status_code == 409 and "fingerprint" in wrong.json()["error"]["detail"]
    partial = _approve(client, owner, run, acknowledged=run["unchecked"][1:])
    assert partial.status_code == 400 and run["unchecked"][0] in partial.json()["error"]["detail"]

    analyst = _member(client, owner, "analyst")
    assert _approve(client, analyst, run).status_code == 403

    done = _data(_approve(client, owner, run, comment="Released after review"))
    assert done["status"] == "approved"
    assert done["approval"]["fingerprint"] == run["clean_sha256"]
    assert done["approval"]["acknowledged"] == run["unchecked"]
    assert done["approval"]["independent"] is False and done["approval"]["independence_required"] is False
    assert _approve(client, owner, run).status_code == 409             # once only

    pdf = client.get(f"/api/disbursement/runs/{run['id']}/download/summary.pdf", headers=owner)
    assert pdf.status_code == 200


def test_independence_when_the_organisation_requires_it(client):
    owner = _company(client, "ind")
    _settings(client, owner)
    policy = client.put("/api/org/approval-policy", headers=owner,
                        json={"disbursement_release_requires_independent_approver": True})
    assert policy.status_code == 200, policy.text
    run = _data(_check(client, owner))
    own = _approve(client, owner, run)
    assert own.status_code == 403 and "someone other than" in own.json()["error"]["detail"]
    manager = _member(client, owner, "manager")
    done = _data(_approve(client, manager, run))
    assert done["approval"]["independent"] is True and done["approval"]["independence_required"] is True


def test_a_newer_check_of_the_month_supersedes_the_older(client):
    owner = _company(client, "new")
    _settings(client, owner)
    first = _data(_check(client, owner))
    second = _data(_check(client, owner))
    stale = _approve(client, owner, first)
    assert stale.status_code == 409 and "newer check" in stale.json()["error"]["detail"]
    detail = _data(client.get(f"/api/disbursement/runs/{first['id']}", headers=owner))
    assert detail["superseded_by"] == second["id"]
    assert _approve(client, owner, second).status_code == 200


def test_roles_viewers_see_history_only_and_other_companies_see_nothing(client):
    owner = _company(client, "role")
    _settings(client, owner)
    run = _data(_check(client, owner))

    viewer = _member(client, owner, "viewer")
    assert _data(client.get("/api/disbursement/runs", headers=viewer))["runs"][0]["id"] == run["id"]
    assert client.get(f"/api/disbursement/runs/{run['id']}", headers=viewer).status_code == 403
    assert client.get(f"/api/disbursement/runs/{run['id']}/download/clean", headers=viewer).status_code == 403
    assert _check(client, viewer).status_code == 403

    analyst = _member(client, owner, "analyst")
    assert _check(client, analyst).status_code == 200
    assert _settings(client, analyst).status_code == 403           # settings decide who is held

    stranger = _company(client, "strange")
    for path in (f"/api/disbursement/runs/{run['id']}", f"/api/disbursement/runs/{run['id']}/download/clean"):
        assert client.get(path, headers=stranger).status_code == 404
    assert _approve(client, stranger, run).status_code == 404
    assert _data(client.get("/api/disbursement/runs", headers=stranger))["runs"] == []


def test_settings_are_validated_and_change_the_next_check(client):
    owner = _company(client, "set")
    bad = client.put("/api/disbursement/settings", headers=owner, json={"overrides": {"variance_pct": "-5"}})
    assert bad.status_code == 400
    unknown = client.put("/api/disbursement/settings", headers=owner, json={"overrides": {"made_up": 1}})
    assert unknown.status_code == 400
    clash = client.put("/api/disbursement/settings", headers=owner, json={
        "custom_templates": {"generic_csv": {"columns": [{"field": "employee_id"}, {"field": "amount"}]}}})
    assert clash.status_code == 400

    _settings(client, owner)
    before = _data(_check(client, owner))
    _settings(client, owner, enabled={"DSB-14": False})
    after = _data(_check(client, owner))
    assert after["rule_status"]["DSB-14"] == "DISABLED" and before["rule_status"]["DSB-14"] == "RAN"
    assert "DSB-14" in after["unchecked"]
    saved = _data(client.get("/api/disbursement/settings", headers=owner))
    assert saved["overrides"]["enabled"] == {"DSB-14": False}


def test_last_months_approved_check_is_this_months_previous_period(client):
    owner = _company(client, "prev")
    _settings(client, owner, max_hold_share_pct="0")
    august = _data(_check(client, owner, scenario="A", period="2026-08"))
    assert august["verdict"] != "DO_NOT_RELEASE"
    _data(_approve(client, owner, august))

    # Scenario D uploads no previous period: last month's approved payments stand in.
    september = _data(_check(client, owner, scenario="D"))
    assert september["previous_run_id"] == august["id"]
    assert september["rule_status"]["DSB-13"] == "RAN"
    detail = _data(client.get(f"/api/disbursement/runs/{september['id']}", headers=owner))
    source = [i for i in detail["report"]["inputs"] if i["slot"] == "previous"]
    assert source and source[0]["filename"] == "Approved check for Aug 2026"
    # Turned off, the check says so instead of reaching back silently.
    plain = _data(_check(client, owner, scenario="D", use_previous_approved="false"))
    assert plain["previous_run_id"] is None and plain["rule_status"]["DSB-13"] == "NOT_RUN"


def test_bank_details_are_cleared_after_retention_but_the_record_stays(client):
    owner = _company(client, "ret")
    _settings(client, owner)
    run = _data(_check(client, owner))
    db = SessionLocal()
    try:
        row = db.get(DisbursementRun, uuid.UUID(run["id"]))
        row.files_expire_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()
    finally:
        db.close()
    _data(_check(client, owner, period="2026-07"))                   # any later check sweeps
    gone = client.get(f"/api/disbursement/runs/{run['id']}/download/clean", headers=owner)
    assert gone.status_code == 410
    detail = _data(client.get(f"/api/disbursement/runs/{run['id']}", headers=owner))
    assert detail["files_cleared_at"] and detail["clean_sha256"] == run["clean_sha256"]
    assert client.get(f"/api/disbursement/runs/{run['id']}/download/exceptions.csv", headers=owner).status_code == 200
    assert _approve(client, owner, run).status_code in (409, 410)


def test_bad_uploads_are_refused_with_a_reason(client):
    owner = _company(client, "bad")
    assert _check(client, owner, period="Sept").status_code == 400
    no_register = _check(client, owner, skip=("register",))
    assert no_register.status_code == 422                          # required by the form
    wrong = client.post("/api/disbursement/runs", headers=owner, data={"period": "2026-09"}, files={
        "bank_file": ("bank.csv", io.BytesIO(b"nothing,like,a,bank,file\n1,2,3,4,5\n")),
        "register": ("register.csv", io.BytesIO(b"Employee ID,Net Pay\nE1,100\n"))})
    assert wrong.status_code == 400 and wrong.json()["error"]["detail"]
