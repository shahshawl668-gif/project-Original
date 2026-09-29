"""
Measure the integration API at payroll scale.

    DATABASE_URL=postgresql://... python tools/benchmark_studio.py --sizes 8000

For each size: create a company and a service account through the product,
then send every input a month needs through ``/api/integration/v1`` as JSON —
employee master, attendance, CTC history (two effective dates per person), the
prior month's register and the month's register with ``validate: true`` — and
run the Studio worker and the validation worker. Each step is timed; resident
memory is sampled; every run's reconciliation identities are checked; and the
validation is checked against the planted defects in ``synthetic_payroll.py``,
whose expected findings are computed independently of the engine. A dry run
and an all-unchanged resend of the master are measured too.

Use a throwaway database. Runs the API in-process, so it measures the
application and the database, not the network or the hosting tier.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import platform
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

os.environ.setdefault("ENV", "dev")
os.environ["VALIDATION_WORKER_ENABLED"] = "false"
os.environ.setdefault("JWT_SECRET", "benchmark-only-secret")
os.environ.setdefault("INTEGRATION_RATE_LIMIT_PER_MINUTE", "100000")

import synthetic_payroll  # noqa: E402
from benchmark_validation import PeakSampler, _data, timed  # noqa: E402

API = "/api/integration/v1"


def _records(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def run_size(client, n: int) -> dict:
    from app.database import SessionLocal
    from app.services import validation_worker as vworker
    from app.services.studio import worker as sworker

    data = synthetic_payroll.generate(n)
    period = data["period_month"]
    steps: dict = {}
    email = f"studio-bench-{n}-{uuid.uuid4().hex[:6]}@benchmark-example.com"
    token = _data(client.post("/api/auth/signup", json={
        "email": email, "password": "Bench-mark-1!", "company_name": f"Studio benchmark {n}"}))["access_token"]
    human = {"Authorization": f"Bearer {token}"}
    entity = _data(client.post("/api/org/entities", headers=human,
                               json={"name": f"Studio benchmark {n}", "primary_state": "Karnataka"}))["id"]
    human["X-Entity-Id"] = entity
    for component in data["components"]:
        assert client.post("/api/components", json=component, headers=human).status_code == 201
    for rule_type in ("PT", "LWF"):
        client.post(f"/api/rule-engine/slabs/import-defaults/all?rule_type={rule_type}&overwrite=true", headers=human)
    account = _data(client.post("/api/studio/service-accounts", headers=human, json={
        "name": "Benchmark feed", "entity_ids": [entity],
        "scopes": ["imports:write", "imports:read", "validation:run", "validation:read"]}))
    key = _data(client.post(f"/api/studio/service-accounts/{account['id']}/keys", headers=human,
                            json={"label": "bench", "expires_in_days": 1}))["key"]
    h = {"Authorization": f"Bearer {key}", "X-Company-Id": entity}

    def submit(kind: str, body: dict) -> str:
        r = client.post(f"{API}/imports/{kind}", headers={**h, "Idempotency-Key": uuid.uuid4().hex}, json=body)
        assert r.status_code == 202, r.text
        return r.json()["data"]["id"]

    def drain_studio():
        db = SessionLocal()
        try:
            return sworker.drain(db)
        finally:
            db.close()

    def drain_validation():
        db = SessionLocal()
        try:
            return vworker.drain(db, "bench-worker")
        finally:
            db.close()

    def finished(run_id: str) -> dict:
        run = client.get(f"{API}/imports/{run_id}", headers=h).json()["data"]
        c = run["counts"]
        assert c["received"] == c["accepted"] + c["rejected"] + c["skipped"], c
        assert c["accepted"] in (0, c["created"] + c["updated"] + c["unchanged"]), c
        return run

    master = _records(data["master_csv"])
    attendance = _records(data["attendance_csv"])
    register = _records(data["register_csv"])
    prior = _records(data["prior_register_csv"])
    ctc = []
    for row in register:
        basic = float(row["basic"])
        for eff, factor in (("2025-04-01", 0.92), ("2026-04-01", 1.0)):
            ctc.append({"employee_id": row["employee_id"], "effective_from": eff,
                        "basic": round(basic * 12 * factor), "hra": round(float(row["hra"]) * 12 * factor)})
    sizes = {
        "master_json_mb": round(len(json.dumps(master)) / 1e6, 2),
        "register_json_mb": round(len(json.dumps(register)) / 1e6, 2),
        "ctc_records": len(ctc),
    }

    body = {"effective_from": "2026-04-01", "records": master, "batch_id": "BENCH-MASTER"}
    timed("master_check_dry_run", steps, lambda: _data(client.post(f"{API}/imports/employee_master/check", headers=h, json=body)))
    rid = timed("master_submit", steps, lambda: submit("employee_master", body))
    timed("master_process", steps, drain_studio)
    m = finished(rid)
    rid = timed("master_resend_submit", steps, lambda: submit("employee_master", body))
    timed("master_resend_process", steps, drain_studio)
    again = finished(rid)
    rid = submit("attendance", {"period_month": period, "records": attendance})
    timed("attendance_process", steps, drain_studio)
    a = finished(rid)
    rid = submit("ctc", {"records": ctc})
    timed("ctc_process", steps, drain_studio)
    c = finished(rid)
    rid = submit("salary_register", {"period_month": data["prior_period_month"], "records": prior})
    timed("prior_register_process", steps, drain_studio)
    p = finished(rid)
    rid = timed("register_submit", steps, lambda: submit("salary_register", {"period_month": period, "records": register, "validate": True}))
    timed("register_process", steps, drain_studio)
    r = finished(rid)
    timed("validation", steps, drain_validation)
    job = client.get(f"{API}/validation-jobs/{r['links']['validation_job_id']}", headers=h).json()["data"]
    assert job["state"] == "succeeded", job
    found: dict[str, set[str]] = {k: set() for k in data["expected"]}

    def read_findings():
        page = 1
        while True:
            out = client.get(f"{API}/validation-runs/{job['run_id']}/findings?page={page}&page_size=500", headers=h).json()["data"]
            for f in out["items"]:
                if f["rule_id"] in found:
                    found[f["rule_id"]].add(f["employee_id"])
            if not out["has_more"]:
                return out["total"]
            page += 1

    total = timed("read_all_findings_paged", steps, read_findings)
    exact = {rule: sorted(found[rule]) == ids for rule, ids in data["expected"].items()}
    return {
        "employees": n,
        "sizes": sizes,
        "steps": steps,
        "counts": {"master": m["counts"], "master_resend": again["counts"], "attendance": a["counts"],
                   "ctc": c["counts"], "prior_register": p["counts"], "register": r["counts"]},
        "findings_total": total,
        "planted_found_exactly": exact,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[8000])
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    from fastapi.testclient import TestClient

    from app.database import engine
    from app.main import app

    report = {"python": platform.python_version(), "machine": platform.machine(), "cpus": os.cpu_count(),
              "database": engine.url.get_backend_name(), "results": []}
    with TestClient(app) as client:
        for n in args.sizes:
            with PeakSampler() as mem:
                result = run_size(client, n)
            result["process_rss_start_mb"] = round(mem.start, 1)
            result["process_rss_peak_mb"] = round(mem.peak, 1)
            report["results"].append(result)
            print(json.dumps(result, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
    ok = all(all(r["planted_found_exactly"].values()) for r in report["results"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
