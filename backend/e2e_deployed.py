"""
End-to-end check against a running deployment.

``pytest tests`` proves the code is right. This proves a *deployment* is right:
the same three-module scenario, driven over real HTTP against whatever host you
point it at, through the same onboard → configure → upload → validate →
reconcile path a first client takes on day one.

    python e2e_deployed.py                                   # a local server
    PEOPLEOPSLAB_BASE_URL=https://api.example.com \
    PEOPLEOPSLAB_PLATFORM_EMAIL=you@example.com \
    PEOPLEOPSLAB_PLATFORM_PASSWORD=... python e2e_deployed.py

Production has no public signup, so there it onboards the way a client really
arrives — platform staff provision a workspace, the owner accepts the
invitation — which is what the two platform variables are for. Where signup is
open it simply signs up. ``PEOPLEOPSLAB_E2E_PASSWORD`` optionally fixes the
throwaway owner's password so you can sign in and look; otherwise it is random.

It creates a throwaway organization each run, so it is safe against a live
deployment: entity scoping keeps everything it creates inside that
organization, and it touches no existing client's data. It writes, so do not
point it at a production tenant you care about the audit trail of.

Exits non-zero if anything fails, which makes it usable as a release gate.

The scenario itself — the staff, the planted defects, the bank file — is
imported from the regression suite rather than copied, so the two cannot drift
apart.
"""
from __future__ import annotations

import io
import json
import os
import secrets
import sys
import time
import uuid

import requests

from tests.test_regression_end_to_end import (
    COMPONENTS,
    PERIODS,
    STAFF,
    attendance_csv,
    bank_csv,
    master_csv,
    register_csv,
)

BASE = os.environ.get("PEOPLEOPSLAB_BASE_URL", "http://localhost:8000").rstrip("/")
# The runner leaves a real workspace behind on the deployment it checks, so its
# owner never gets a password that is written down anywhere — least of all in a
# repository. A fresh one per run unless you set it to sign in and look around.
PASSWORD = os.environ.get("PEOPLEOPSLAB_E2E_PASSWORD") or f"{secrets.token_urlsafe(18)}Aa1!"
JUNE = PERIODS[2]

# A cold free-tier instance can take the better part of a minute to wake.
TIMEOUT = int(os.environ.get("PEOPLEOPSLAB_TIMEOUT", "120"))


class Run:
    """Counts what happened, so the exit code means something."""

    def __init__(self) -> None:
        self.passed = 0
        self.failures: list[str] = []

    def check(self, label: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.passed += 1
            print(f"  [PASS] {label}")
        else:
            self.failures.append(f"{label}{f' — {detail}' if detail else ''}")
            print(f"  [FAIL] {label}")
            if detail:
                print(f"         {detail[:300]}")
        return bool(condition)

    def section(self, title: str) -> None:
        print(f"\n--- {title} ---")


run = Run()
session = requests.Session()
headers: dict[str, str] = {}


def call(method: str, path: str, **kw) -> requests.Response:
    return session.request(method, f"{BASE}{path}", headers=headers, timeout=TIMEOUT, **kw)


def body(response: requests.Response) -> dict | list | None:
    """The payload inside the envelope, or None if this was not a success."""
    try:
        return response.json().get("data")
    except Exception:
        return None


def upload(path: str, filename: str, content: str, meta: dict) -> requests.Response:
    return call(
        "POST", path,
        files={"file": (filename, io.BytesIO(content.encode()), "text/csv")},
        data={"meta": json.dumps(meta)},
    )


PLATFORM_EMAIL = os.environ.get("PEOPLEOPSLAB_PLATFORM_EMAIL", "").strip()
PLATFORM_PASSWORD = os.environ.get("PEOPLEOPSLAB_PLATFORM_PASSWORD", "")


def onboard(email: str) -> str | None:
    """Get a client session for a throwaway organisation, the way a real one arrives.

    Where public signup is open (development), that is one call. In production
    it is closed — onboarding is by invitation — so this does what the
    platform console does: platform staff provision a workspace, the owner
    accepts the invitation by setting a password, and signs in at their
    workspace's own address.

    That path needs platform credentials, read from
    PEOPLEOPSLAB_PLATFORM_EMAIL and PEOPLEOPSLAB_PLATFORM_PASSWORD. They are
    never defaulted and never written anywhere: a release gate that ships with
    an admin password is a release gate that leaks one.
    """
    signed = call("POST", "/api/auth/signup",
                  json={"email": email, "password": PASSWORD, "company_name": "E2E Check Pvt Ltd"})
    if signed.status_code == 200:
        run.check("self-registration succeeds (public signup is open)", True)
        return body(signed)["access_token"]
    if signed.status_code != 404:
        run.check("signup answers", False, f"HTTP {signed.status_code}: {signed.text[:200]}")
        return None

    print("         public signup is closed — onboarding by invitation, as production does")
    if not (PLATFORM_EMAIL and PLATFORM_PASSWORD):
        run.check("platform credentials supplied", False,
                  "this deployment is invitation-only; set PEOPLEOPSLAB_PLATFORM_EMAIL and "
                  "PEOPLEOPSLAB_PLATFORM_PASSWORD to a platform owner or admin account")
        return None

    # Platform calls carry their own header; the shared one is for the client.
    staff = session.post(f"{BASE}/api/auth/platform-login", timeout=TIMEOUT,
                         json={"email": PLATFORM_EMAIL, "password": PLATFORM_PASSWORD})
    if not run.check("platform staff can sign in", staff.status_code == 200, staff.text[:200]):
        return None
    staff_header = {"Authorization": f"Bearer {body(staff)['access_token']}"}

    provisioned = session.post(f"{BASE}/api/admin/organizations", headers=staff_header,
                               timeout=TIMEOUT,
                               json={"name": "E2E Check Pvt Ltd", "owner_email": email})
    if not run.check("workspace provisioned", provisioned.status_code == 201,
                     provisioned.text[:300]):
        return None
    workspace = body(provisioned)
    invite_token = workspace["invitation_path"].split("token=", 1)[-1]

    registered = session.post(f"{BASE}/api/org/invitations/register", timeout=TIMEOUT,
                              json={"token": invite_token, "password": PASSWORD})
    if not run.check("owner accepts the invitation", registered.status_code == 200,
                     registered.text[:300]):
        return None

    # The address a client is actually given, rather than the token the
    # invitation happened to return.
    signed_in = session.post(f"{BASE}/api/auth/login", timeout=TIMEOUT,
                             json={"email": email, "password": PASSWORD,
                                   "workspace_slug": workspace["slug"]})
    if not run.check(f"owner signs in at {workspace['login_path']}",
                     signed_in.status_code == 200, signed_in.text[:200]):
        return None

    # A workspace sign-in must be bound to that workspace, not merely succeed.
    wrong = session.post(f"{BASE}/api/auth/login", timeout=TIMEOUT,
                         json={"email": email, "password": PASSWORD,
                               "workspace_slug": workspace["slug"] + "-not-it"})
    run.check("the same credentials are refused at another workspace",
              wrong.status_code in (400, 401, 404), f"HTTP {wrong.status_code}")
    return body(signed_in)["access_token"]


# ---------------------------------------------------------------------------
def main() -> int:
    print(f"\n=== Peopleopslab end-to-end against {BASE} ===")

    run.section("Reachability")
    try:
        health = call("GET", "/api/health")
    except requests.RequestException as exc:
        run.check("API reachable", False, str(exc))
        return report()
    payload = body(health) or {}
    run.check("GET /api/health is 200", health.status_code == 200, health.text[:200])
    run.check("health reports ok", payload.get("status") == "ok", json.dumps(payload))
    env = payload.get("env")
    print(f"         env={env} version={payload.get('version')}")

    run.section("Anonymous access is refused")
    # The single most important production setting. A deployment that answers
    # this without a token is serving every client's payroll to the internet.
    anon = requests.get(f"{BASE}/api/org/entities", timeout=TIMEOUT)
    if env == "production":
        run.check("unauthenticated request is rejected", anon.status_code in (401, 403),
                  f"HTTP {anon.status_code} — ALLOW_ANONYMOUS_API must be false in production")
    else:
        print(f"  [SKIP] env={env}, not asserting auth enforcement (HTTP {anon.status_code})")

    run.section("Onboarding")
    email = f"e2e-{uuid.uuid4().hex[:12]}@e2e-check.com"
    token = onboard(email)
    if token is None:
        return report()
    headers["Authorization"] = f"Bearer {token}"

    run.section("Entity")

    entity = call("POST", "/api/org/entities",
                  json={"name": "E2E Check", "primary_state": "Karnataka"})
    if not run.check("entity created", entity.status_code == 200, entity.text[:300]):
        return report()
    headers["X-Entity-Id"] = body(entity)["id"]

    run.section("Configuration")
    created = [call("POST", "/api/components", json=c).status_code for c in COMPONENTS]
    run.check(f"{len(COMPONENTS)} salary components created",
              all(s == 201 for s in created), str(created))
    for rule_type in ("PT", "LWF"):
        r = call("POST", f"/api/rule-engine/slabs/import-defaults/all"
                         f"?rule_type={rule_type}&overwrite=true")
        run.check(f"{rule_type} slabs seeded", r.status_code == 200, r.text[:200])

    run.section("Employee master and three months of data")
    master = upload("/api/workforce/master/commit", "master.csv", master_csv(),
                    {"effective_from": "2026-04-01"})
    run.check("employee master committed", master.status_code == 200, master.text[:300])

    for period in PERIODS:
        tag = f"{period:%Y-%m}"
        checked = upload("/api/workforce/attendance/validate", f"att-{tag}.csv",
                         attendance_csv(period), {"period_month": period.isoformat()})
        ok = checked.status_code == 200 and (body(checked) or {}).get("clean") is True
        run.check(f"attendance {tag} is self-consistent", ok, checked.text[:300])
        committed = upload("/api/workforce/attendance/commit", f"att-{tag}.csv",
                           attendance_csv(period), {"period_month": period.isoformat()})
        run.check(f"attendance {tag} committed", committed.status_code == 200,
                  committed.text[:300])
        registered = upload("/api/payroll/upload", f"register-{tag}.csv", register_csv(period),
                            {"period_month": period.isoformat(), "strict_header_check": False})
        run.check(f"register {tag} uploaded", registered.status_code == 200,
                  registered.text[:300])

    run.section("Module A — validation finds the planted defects")
    parsed = upload("/api/payroll/upload", "june.csv", register_csv(JUNE),
                    {"period_month": JUNE.isoformat(), "strict_header_check": False})
    validated = call("POST", "/api/payroll/validate",
                     json={"employees": (body(parsed) or {}).get("employees", []),
                           "period_month": JUNE.isoformat()})
    if run.check("validation ran", validated.status_code == 200, validated.text[:300]):
        rows = (body(validated) or {}).get("results", [])
        found = {
            row["employee_id"]: {f["rule_id"]: f for f in row.get("findings", [])}
            for row in rows
        }
        run.check("every employee on the register was assessed",
                  len(found) == len(STAFF), f"{len(found)} rows")
        pf = found.get("E004", {}).get("STAT-001", {})
        run.check("E004's undeducted PF is CRITICAL (STAT-001)",
                  pf.get("severity") == "CRITICAL", json.dumps(pf)[:200])
        run.check("E005's unpaid attendance loss is reported (ATT-002)",
                  "ATT-002" in found.get("E005", {}))
        overpaid = found.get("E005", {}).get("ATT-020", {})
        run.check("E005's overpayment is CRITICAL and valued (ATT-020)",
                  overpaid.get("severity") == "CRITICAL"
                  and (overpaid.get("financial_impact") or 0) > 0,
                  json.dumps(overpaid)[:200])
        run.check("E006's unpaid overtime is reported (ATT-022)",
                  "ATT-022" in found.get("E006", {}))
        clean = [e for e in found if e not in ("E004", "E005", "E006")
                 and ({"ATT-020", "ATT-022"} & set(found[e]))]
        run.check("no one else is dragged in", not clean, str(clean))

    summary = call("GET", "/api/findings/summary")
    run.check("findings reach the register",
              summary.status_code == 200 and (body(summary) or {}).get("open_count", 0) > 0,
              summary.text[:200])

    run.section("Module B — cost and BI")
    analysis = call("GET", "/api/bi/cost-analysis"
                           "?group_by=department&date_from=2026-04-01&date_to=2026-06-01")
    groups = set((body(analysis) or {}).get("groups", {}) or {})
    run.check("dimensions came off the master",
              groups == {"Engineering", "Sales", "Operations"}, str(groups))

    run.section("Module C — bank file and journal voucher")
    profile = call("POST", "/api/reconciliation/bank/profiles", json={
        "name": "E2E bank layout",
        "column_map": {"employee_id": "code", "employee_name": "name",
                       "account_number": "account", "ifsc": "ifsc", "amount": "amount"},
    })
    if run.check("bank file profile created", profile.status_code == 200, profile.text[:300]):
        sent = call("POST", "/api/reconciliation/bank/files",
                    files={"file": ("bank.csv", io.BytesIO(bank_csv(JUNE).encode()), "text/csv")},
                    data={"period": "2026-06", "profile_id": body(profile)["id"]})
        if run.check("bank file parsed and stored", sent.status_code == 200, sent.text[:300]):
            recon = call("GET", f"/api/reconciliation/bank/reconcile?file_id={body(sent)['id']}")
            if run.check("bank reconciliation ran", recon.status_code == 200, recon.text[:300]):
                kinds = {e["code"] for e in (body(recon) or {}).get("exceptions", [])}
                run.check("the unpaid employee is found (bank.not_in_file)",
                          "bank.not_in_file" in kinds, str(sorted(kinds)))
                run.check("the ghost payee is found (bank.not_in_register)",
                          "bank.not_in_register" in kinds, str(sorted(kinds)))
                run.check("the changed account is found (bank.account_differs_from_master)",
                          "bank.account_differs_from_master" in kinds, str(sorted(kinds)))

    template = call("POST", "/api/reconciliation/jv/templates",
                    json={"name": "E2E JV", "from_preset": "standard_accrual"})
    if run.check("JV template created from a preset", template.status_code == 200,
                 template.text[:300]):
        template_id = body(template)["id"]
        approved = call("POST", f"/api/reconciliation/jv/templates/{template_id}/approve")
        run.check("JV template approved", approved.status_code == 200, approved.text[:200])
        preview = call("GET", "/api/reconciliation/jv/preview?period=2026-06")
        run.check("the voucher balances",
                  preview.status_code == 200 and (body(preview) or {}).get("balanced") is True,
                  preview.text[:300])
        export = call("GET", "/api/reconciliation/jv/export?period=2026-06&format=tally_csv")
        run.check("the voucher exports to Tally CSV",
                  export.status_code == 200 and "Ledger Name" in export.text,
                  export.text[:200])

    overview = call("GET", "/api/reconciliation/overview?period=2026-06")
    run.check("reconciliation overview answers", overview.status_code == 200,
              overview.text[:200])

    run.section("Reports")
    report_xlsx = call("GET", "/api/reports/bank-jv-reconciliation.xlsx?date_to=2026-06")
    run.check("the reconciliation workbook downloads",
              report_xlsx.status_code == 200 and len(report_xlsx.content) > 0,
              f"HTTP {report_xlsx.status_code}")

    run.section("Team management")
    invited = call("POST", "/api/org/invitations",
                   json={"email": f"colleague-{uuid.uuid4().hex[:8]}@e2e-check.com",
                         "role": "analyst"})
    run.check("an invitation can be issued", invited.status_code in (200, 201),
              invited.text[:300])
    members = call("GET", "/api/org/members")
    run.check("the member list answers", members.status_code == 200, members.text[:200])

    return report()


def report() -> int:
    failed = len(run.failures)
    total = run.passed + failed
    print(f"\n=== {run.passed}/{total} checks passed ===")
    if failed:
        print("\nFailures:")
        for line in run.failures:
            print(f"  • {line}")
        return 1
    print("The deployment is answering correctly end to end.")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = main()
    print(f"({time.time() - started:.1f}s)")
    sys.exit(code)
