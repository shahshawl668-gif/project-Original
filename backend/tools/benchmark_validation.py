"""
Measure validation at payroll scale.

    DATABASE_URL=postgresql://... python tools/benchmark_validation.py --sizes 8000 20000

For each size: set up a company through the API, commit a synthetic master and
attendance register, upload the salary register, queue its validation, run the
worker, then read the result back the way the product's pages do. Each step is
timed; the worker's CPU time and peak resident memory are measured; and the run
is checked against the planted defects in ``synthetic_payroll.py``, whose
expected findings are computed independently of the engine.

A second validation of the same month is then run, to measure the history path
(supersession) and the run comparison at the same scale.

Use a throwaway database. The benchmark creates companies and never deletes
them, and it runs the API in-process, so it measures the application and the
database — not network latency or the hosting tier, which it reports alongside.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import platform
import resource
import sys
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

os.environ.setdefault("ENV", "dev")
os.environ["VALIDATION_WORKER_ENABLED"] = "false"
os.environ.setdefault("JWT_SECRET", "benchmark-only-secret")

import synthetic_payroll  # noqa: E402


def _rss_mb() -> float:
    with open("/proc/self/status") as fh:
        for line in fh:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return 0.0


class PeakSampler:
    """Resident memory sampled every 20 ms while a step runs."""

    def __init__(self) -> None:
        self.peak = 0.0
        self.start = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, _rss_mb())
            time.sleep(0.02)

    def __enter__(self):
        self.start = _rss_mb()
        self.peak = self.start
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()


def _cpu() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


def _data(response):
    if response.status_code != 200:
        raise RuntimeError(f"{response.request.method} {response.request.url} → "
                           f"{response.status_code}: {response.text[:400]}")
    return response.json()["data"]


def timed(label: str, results: dict, fn):
    t0, c0 = time.perf_counter(), _cpu()
    with PeakSampler() as mem:
        out = fn()
    results[label] = {
        "seconds": round(time.perf_counter() - t0, 3),
        "cpu_seconds": round(_cpu() - c0, 3),
        "rss_start_mb": round(mem.start, 1),
        "rss_peak_mb": round(mem.peak, 1),
    }
    return out


def run_size(client, n: int) -> dict:
    from sqlalchemy import func

    from app.database import SessionLocal
    from app.models import FindingRecord, RegisterUpload, ValidationRunEmployee
    from app.services import validation_worker as worker

    data = synthetic_payroll.generate(n)
    period = data["period_month"]
    steps: dict = {}

    email = f"bench-{n}-{uuid.uuid4().hex[:6]}@benchmark-example.com"
    token = _data(client.post("/api/auth/signup", json={
        "email": email, "password": "Bench-mark-1!", "company_name": f"Benchmark {n}",
    }))["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    entity_id = _data(client.post("/api/org/entities", headers=headers,
                                  json={"name": f"Benchmark {n}", "primary_state": "Karnataka"}))["id"]
    headers["X-Entity-Id"] = entity_id
    for component in data["components"]:
        assert client.post("/api/components", json=component, headers=headers).status_code == 201
    for rule_type in ("PT", "LWF"):
        client.post(f"/api/rule-engine/slabs/import-defaults/all?rule_type={rule_type}&overwrite=true",
                    headers=headers)

    def files(name, text):
        return {"file": (name, io.BytesIO(text.encode()), "text/csv")}

    timed("master_commit", steps, lambda: _data(client.post(
        "/api/workforce/master/commit", headers=headers, files=files("master.csv", data["master_csv"]),
        data={"meta": json.dumps({"effective_from": "2026-04-01"})})))
    timed("attendance_commit", steps, lambda: _data(client.post(
        "/api/workforce/attendance/commit", headers=headers,
        files=files("attendance.csv", data["attendance_csv"]),
        data={"meta": json.dumps({"period_month": period})})))
    # May first, clean, so June is validated against a real prior month.
    timed("prior_register_upload", steps, lambda: _data(client.post(
        "/api/payroll/upload", headers=headers,
        files=files("register-may.csv", data["prior_register_csv"]),
        data={"meta": json.dumps({"period_month": data["prior_period_month"],
                                  "strict_header_check": False, "return_employees": False})})))
    upload = timed("register_upload", steps, lambda: _data(client.post(
        "/api/payroll/upload", headers=headers, files=files("register.csv", data["register_csv"]),
        data={"meta": json.dumps({"period_month": period, "strict_header_check": False,
                                  "return_employees": False})})))["upload"]
    job = timed("enqueue", steps, lambda: _data(client.post(
        "/api/validation/jobs", headers=headers, json={"period_month": period})))["job"]

    def work():
        db = SessionLocal()
        try:
            return worker.run_once(db, "benchmark")
        finally:
            db.close()

    assert timed("worker_validation", steps, work) is True
    job = _data(client.get(f"/api/validation/jobs/{job['id']}", headers=headers))
    if job["state"] != "succeeded":
        raise RuntimeError(f"job did not succeed: {job}")
    run_id = job["run_id"]

    run = timed("read_run_summary", steps, lambda: _data(client.get(
        f"/api/validation/runs/{run_id}", headers=headers)))
    timed("read_employees_page", steps, lambda: _data(client.get(
        f"/api/validation/runs/{run_id}/employees?page=1&page_size=50&sort=risk_score&order=desc",
        headers=headers)))
    timed("read_employees_page_computed", steps, lambda: _data(client.get(
        f"/api/validation/runs/{run_id}/employees?page=40&page_size=50&include_computed=true",
        headers=headers)))
    timed("search_employees", steps, lambda: _data(client.get(
        f"/api/validation/runs/{run_id}/employees?q=S0001&page_size=50", headers=headers)))
    timed("read_findings_page", steps, lambda: _data(client.get(
        f"/api/validation/runs/{run_id}/findings?page=1&page_size=50", headers=headers)))
    timed("read_employee_detail", steps, lambda: _data(client.get(
        f"/api/validation/runs/{run_id}/employees/S000006", headers=headers)))
    timed("export_xlsx", steps, lambda: client.get(
        f"/api/validation/runs/{run_id}/export.xlsx", headers=headers).content)

    # Second run of the same month: supersession and comparison at scale.
    job2 = _data(client.post("/api/validation/jobs", headers=headers, json={"period_month": period}))["job"]
    timed("worker_validation_rerun", steps, work)
    job2 = _data(client.get(f"/api/validation/jobs/{job2['id']}", headers=headers))
    compare = timed("compare_runs", steps, lambda: _data(client.get(
        f"/api/validation/runs/compare?base={run_id}&target={job2['run_id']}&limit=100", headers=headers)))

    # Independent check of the planted defects.
    db = SessionLocal()
    try:
        verification = {}
        for rule, expected in data["expected"].items():
            found = {
                eid for (eid,) in db.query(FindingRecord.employee_id)
                .filter(FindingRecord.run_id == uuid.UUID(run_id), FindingRecord.rule_id == rule)
                .all()
            }
            expected_set = set(expected)
            verification[rule] = {
                "planted": len(expected_set),
                "found": len(found),
                "missed": sorted(expected_set - found)[:10],
                "false_positives": sorted(found - expected_set)[:10],
                "exact": found == expected_set,
            }
        storage = {
            "upload_rows_gz_bytes": db.query(func.length(RegisterUpload.rows_gz))
            .filter(RegisterUpload.id == uuid.UUID(upload["id"])).scalar(),
            "employee_results_gz_bytes": db.query(func.sum(func.length(ValidationRunEmployee.detail_gz)))
            .filter(ValidationRunEmployee.run_id == uuid.UUID(run_id)).scalar(),
            "employee_result_rows": db.query(func.count(ValidationRunEmployee.id))
            .filter(ValidationRunEmployee.run_id == uuid.UUID(run_id)).scalar(),
            "finding_rows": db.query(func.count(FindingRecord.id))
            .filter(FindingRecord.run_id == uuid.UUID(run_id)).scalar(),
        }
    finally:
        db.close()

    return {
        "employees": n,
        "esic_eligible": data["esic_eligible"],
        "register_csv_bytes": len(data["register_csv"].encode()),
        "run": {
            "total_findings": run["total_findings"],
            "critical": run["critical_count"],
            "warnings": run["warning_count"],
            "duration_ms_recorded": run["duration_ms"],
        },
        "rerun_compare_counts": compare["counts"],
        "steps": steps,
        "verification": verification,
        "storage": storage,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark validation at payroll scale.")
    parser.add_argument("--sizes", type=int, nargs="+", default=[8000, 20000])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    from fastapi.testclient import TestClient

    from app.database import engine
    from app.main import app

    report = {
        "database": engine.url.get_backend_name(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "cpus": os.cpu_count(),
        "sizes": [],
    }
    with TestClient(app) as client:
        for n in args.sizes:
            print(f"--- {n} employees", flush=True)
            result = run_size(client, n)
            report["sizes"].append(result)
            print(json.dumps({k: result[k] for k in ("steps", "verification", "storage", "run")},
                             indent=1), flush=True)
    if args.out:
        args.out.write_text(json.dumps(report, indent=2))
    ok = all(v["exact"] for s in report["sizes"] for v in s["verification"].values())
    print("verification:", "all planted defects found exactly" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
