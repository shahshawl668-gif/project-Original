"""Runs the whole pack through the product and saves the reports it produces.

    cd backend && PYTHONPATH=. python ../testdata/payroll-validation/generate_reports.py

Writes to ./sample-reports/ using a throw-away database, so it changes nothing real.
"""
from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "sample-reports"
os.environ.update(DATABASE_URL=f"sqlite:///{tempfile.mkdtemp()}/reports.db", JWT_SECRET="r" * 40, ENV="dev",
                  VALIDATION_WORKER_ENABLED="false", REPORT_WORKER_ENABLED="false")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def f(name):
    return {"file": (name, (HERE / name).read_bytes(), "text/csv")}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    with TestClient(app) as c:
        t = c.post("/api/auth/signup", json={"email": "reports@pack-example.com", "password": "Passw0rd!xyz",
                                             "company_name": "Acme Pack"}).json()["data"]["access_token"]
        h = {"Authorization": f"Bearer {t}"}
        h["X-Entity-Id"] = c.post("/api/org/entities", json={"name": "Acme Pack Pvt Ltd", "primary_state": "Karnataka"},
                                  headers=h).json()["data"]["id"]
        assert c.post("/api/config/bundle/import?dry_run=false", files=f("1_configuration.csv"), headers=h).status_code == 200
        c.post("/api/workforce/master/commit", files=f("2_employee_master.csv"),
               data={"meta": '{"effective_from":"2026-04-01"}'}, headers=h).raise_for_status()
        recs = c.post("/api/ctc/upload", files=f("3_ctc_report.csv"),
                      data={"meta": '{"default_effective_from":"2026-04-01"}'}, headers=h).json()["data"]["records"]
        c.post("/api/ctc/commit", json={"filename": "3_ctc_report.csv", "default_effective_from": "2026-04-01",
                                         "records": recs}, headers=h).raise_for_status()
        meta = '{"period_month":"2026-08-01"}'
        att = c.post("/api/workforce/attendance/validate", files=f("4_attendance_report.csv"), data={"meta": meta}, headers=h).json()["data"]
        c.post("/api/workforce/attendance/commit", files=f("4_attendance_report.csv"), data={"meta": meta}, headers=h).raise_for_status()
        runs = {}
        for name, period, last in (("6_previous_month_register_july.csv", "2026-07-01", "2026-07-31"),
                                   ("5_salary_register.csv", "2026-08-01", "2026-08-31")):
            up = c.post("/api/payroll/upload", files=f(name), headers=h, data={"meta": json.dumps({
                "run_type": "regular", "period_month": period, "strict_header_check": False})}).json()["data"]
            v = c.post("/api/payroll/validate", headers=h, json={"employees": up["employees"], "run_type": "regular",
                                                                 "period_month": period, "as_of_date": last})
            v.raise_for_status()
            runs[period] = v.json()["data"]
        august = runs["2026-08-01"]
        run_id = august["lifecycle"]["run_id"]

        def save(name, response):
            if response.status_code == 200:
                (OUT / name).write_bytes(response.content)
                print("saved", name)
            else:
                print("skipped", name, response.status_code)

        save("validation-results-aug-2026.xlsx", c.get(f"/api/validation/runs/{run_id}/export.xlsx", headers=h))
        save("parallel-run-pack-aug-2026.xlsx", c.get(f"/api/validation/runs/{run_id}/parallel-run.xlsx", headers=h))
        for kind in [r["key"] for r in c.get("/api/reports", headers=h).json()["data"]["reports"]]:
            save(f"report-centre-{kind}.xlsx", c.get(f"/api/reports/{kind}.xlsx", headers=h))

        cols = ["employee_id", "employee_name", "severity", "rule_id", "rule_name", "component",
                "expected_value", "actual_value", "difference", "financial_impact", "reason", "suggested_fix"]
        with open(OUT / "findings-aug-2026.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(x for x in sorted(august["findings"], key=lambda x: (x["employee_id"], x["rule_id"]))
                        if x["status"] == "FAIL")
        with open(OUT / "attendance-check-aug-2026.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(att["findings"])
        cov = august["findings_summary"]["coverage"]
        (OUT / "summary-aug-2026.md").write_text(
            "# August 2026 validation summary\n\n"
            f"* Employees: {len(august['results'])}\n"
            f"* Critical findings: {august['findings_summary']['critical']}, warnings: {august['findings_summary']['warning']}\n"
            f"* Coverage: {cov['coverage_pct']}% ({cov['totals']})\n"
            f"* Inputs still missing: {cov['missing_inputs']}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
