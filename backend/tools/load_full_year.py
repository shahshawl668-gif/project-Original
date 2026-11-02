"""Load the full-year test company into a running instance, month by month, over HTTP.

    python backend/tools/load_full_year.py                       # http://localhost:8000, all 12 months
    python backend/tools/load_full_year.py --through 2026-09     # April to September only
    python backend/tools/load_full_year.py --base http://localhost:8000 --email you@example.com
    python backend/tools/load_full_year.py --setup-only           # account, company and configuration only:
                                                                  # load the months yourself, in the screens

It does what a payroll team does each month, through the same endpoints the
screens use: upload the master and CTC when they change, the attendance, the
salary register, then queue the validation and wait for the background worker.
After each month it prints what was found against the pack's answer key, so the
year can be followed in the browser at the same time.

Use it against your own local instance only. It loads the year into the company
of the account it signs in to (a new account's own company, normally).
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from pathlib import Path

import requests

PACK = Path(__file__).resolve().parents[2] / "testdata" / "payroll-fy2026-27"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--email", default="fy-test@example.com")
    ap.add_argument("--password", default=None, help="defaults to a fresh random one, printed at the end")
    ap.add_argument("--through", default="2027-03", help="last month to load, YYYY-MM")
    ap.add_argument("--setup-only", action="store_true", help="create the account and company, load no months")
    ap.add_argument("--web", default="http://localhost:3000", help="the web app, for the sign-in link printed at the end")
    args = ap.parse_args()
    password = args.password or f"Fy-{secrets.token_urlsafe(9)}1a!"
    key = json.loads((PACK / "answer_key.json").read_text())
    s = requests.Session()

    def call(method, path, **kw):
        r = s.request(method, args.base + path, timeout=300, **kw)
        if r.status_code >= 400:
            raise SystemExit(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
        return r.json()["data"]

    def files(path: Path):
        return {"file": (path.name, path.read_bytes(), "text/csv")}

    r = s.post(args.base + "/api/auth/signup", json={"email": args.email, "password": password,
                                                    "company_name": "FY Retail (test)"}, timeout=60)
    if r.status_code != 200:
        if not args.password:
            raise SystemExit(f"{args.email} already exists: pass --password, or use another --email.")
        r = s.post(args.base + "/api/auth/login", json={"email": args.email, "password": password}, timeout=60)
    if r.status_code != 200:
        raise SystemExit(f"sign-in failed: {r.text[:300]}")
    s.headers["Authorization"] = f"Bearer {r.json()['data']['access_token']}"
    # The company the account was created with, so the year is what you see on signing in.
    entities = [e for e in call("GET", "/api/org/entities") if e.get("is_active", True)]
    entity = entities[0] if entities else call("POST", "/api/org/entities",
                                               json={"name": "FY Retail (test)", "primary_state": "Karnataka"})
    s.headers["X-Entity-Id"] = entity["id"]
    call("POST", "/api/config/bundle/import?dry_run=false", files=files(PACK / "1_configuration.csv"))
    slug = call("GET", "/api/org/context")["organization"]["slug"]
    sign_in = (f"Sign in at {args.web}/w/{slug}/login as {args.email}"
               + ("" if args.password else f" with password {password}") + ".")
    print(f"company {entity['name']} configured")
    if args.setup_only:
        print("Now load the months from testdata/payroll-fy2026-27/months/ in the screens, in order.")
        print(sign_in)
        return 0

    totals = {"caught": 0, "missed": 0, "extra": 0}
    for folder in sorted((PACK / "months").iterdir()):
        month = folder.name
        if month > args.through:
            break
        first = f"{month}-01"
        if (folder / "employee_master.csv").exists():
            call("POST", "/api/workforce/master/commit", files=files(folder / "employee_master.csv"),
                 data={"meta": json.dumps({"effective_from": first})})
        if (folder / "ctc.csv").exists():
            parsed = call("POST", "/api/ctc/upload", files=files(folder / "ctc.csv"),
                          data={"meta": json.dumps({"default_effective_from": first})})
            call("POST", "/api/ctc/commit", json={"filename": "ctc.csv", "default_effective_from": first,
                                                  "records": parsed["records"]})
        meta = {"meta": json.dumps({"period_month": first})}
        call("POST", "/api/workforce/attendance/commit", files=files(folder / "attendance.csv"), data=meta)
        up = call("POST", "/api/payroll/upload", files=files(folder / "salary_register.csv"),
                  data={"meta": json.dumps({"period_month": first, "strict_header_check": True,
                                            "return_employees": False})})
        upload = up.get("upload") or up
        job = call("POST", "/api/validation/jobs", json={"period_month": first, "upload_id": upload["id"]})["job"]
        for _ in range(600):
            job = call("GET", f"/api/validation/jobs/{job['id']}")
            if job["state"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(1)
        if job["state"] != "succeeded":
            raise SystemExit(f"{month}: validation {job['state']}: {job.get('error')}")
        found = []
        page = 1
        while True:
            data = call("GET", f"/api/validation/runs/{job['run_id']}/findings", params={"page": page, "page_size": 500})
            found += data["items"]
            if not data["items"] or len(found) >= data.get("total", 0):
                break
            page += 1
        fired: dict[str, set[str]] = {}
        for f in found:
            if f["status"] == "FAIL" and f["severity"] != "INFO":
                fired.setdefault(f["employee_id"], set()).add(f["rule_id"])
        planted = key.get(month, {})
        caught = [e for e, v in planted.items() if set(v["rules"]) <= fired.get(e, set())]
        missed = [e for e in planted if e not in caught]
        extra = {e: sorted(r - set(planted.get(e, {}).get("rules", []))) for e, r in fired.items()}
        extra = {e: r for e, r in extra.items() if r}
        totals["caught"] += len(caught)
        totals["missed"] += len(missed)
        totals["extra"] += len(extra)
        print(f"{month}: {len(found)} findings; planted {len(caught)}/{len(planted)} caught"
              + (f"; MISSED {missed}" if missed else "") + (f"; UNEXPECTED {extra}" if extra else ""))
    print(f"\nYear: {totals['caught']} planted mistakes caught, {totals['missed']} missed, "
          f"{totals['extra']} employees with unexpected findings.")
    print(sign_in)
    return 0 if not totals["missed"] and not totals["extra"] else 1


if __name__ == "__main__":
    sys.exit(main())
