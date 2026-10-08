#!/usr/bin/env python3
"""PeopleOps Studio client-side import example. Python 3.10+, standard library only.

Run on your own controlled machine. This file never runs on PeopleOpsLab servers.
Keep POL_API_KEY in a secret store, never in this file. Edit transform() for your
source's column names or set POL_MAPPING_KEY to a published Studio mapping.
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

KINDS = ("employee_master", "ctc", "attendance", "salary_register")


def transform(row):
    """Map one client record to the approved import fields.

    For example: out["employee_id"] = row["Employee Code"].
    Preserve employee IDs as strings. Never log unmasked payroll rows.
    """
    if not isinstance(row, dict):
        raise ValueError("Every input record must be a JSON object")
    return dict(row)


def request(url, key, company, payload, idempotency=None):
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": "Bearer " + key,
        "X-Company-Id": company,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if idempotency:
        headers["Idempotency-Key"] = idempotency
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        # API error bodies do not contain the supplied key or full records.
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError("API returned HTTP %s: %s" % (exc.code, detail)) from None
    return result.get("data", result)


def main():
    parser = argparse.ArgumentParser(description="Check and optionally submit a Studio import")
    parser.add_argument("--send", action="store_true", help="Submit only after a successful check")
    args = parser.parse_args()
    key = os.environ.get("POL_API_KEY")
    company = os.environ.get("POL_COMPANY_ID")
    kind = os.environ.get("POL_OBJECT_TYPE", "employee_master")
    source = os.environ.get("POL_INPUT_JSON")
    period = os.environ.get("POL_PERIOD")
    base = os.environ.get("POL_API_BASE", "https://www.peopleopslab.in/api/proxy/api/integration/v1").rstrip("/")
    if not key or not company or not source:
        parser.error("POL_API_KEY, POL_COMPANY_ID and POL_INPUT_JSON are required")
    if kind not in KINDS:
        parser.error("POL_OBJECT_TYPE must be one of: " + ", ".join(KINDS))
    if not base.startswith("https://") and not base.startswith("http://localhost:"):
        parser.error("POL_API_BASE must use HTTPS")
    if not period:
        parser.error("POL_PERIOD is required (YYYY-MM-DD); use the first day of the payroll month")
    rows = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        parser.error("Input must be a non-empty JSON array")
    records = [transform(row) for row in rows]
    payload = {
        "records": records,
        "source_system": os.environ.get("POL_SOURCE_SYSTEM", "client_python"),
        "source_object": Path(source).name,
        "batch_id": os.environ.get("POL_BATCH_ID") or Path(source).stem + "-" + period,
    }
    payload[{"employee_master": "effective_from", "ctc": "default_effective_from",
             "attendance": "period_month", "salary_register": "period_month"}[kind]] = period
    if os.environ.get("POL_MAPPING_KEY"):
        payload["mapping_key"] = os.environ["POL_MAPPING_KEY"]
    path = base + "/imports/" + kind
    check = request(path + "/check", key, company, payload)
    counts = check.get("counts", {})
    rejections = check.get("rejections", [])
    print(json.dumps({"check_counts": counts, "rejections": rejections}, indent=2))
    if check.get("error") or rejections or counts.get("rejected", 0):
        print("Check found errors or rejections; nothing was submitted.", file=sys.stderr)
        return 1
    if not args.send:
        print("Check passed. Review the totals, then rerun with --send to submit.")
        return 0
    # Same company, endpoint, and payload yields the same key on a safe retry.
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256((company + "|" + kind + "|" + canonical).encode("utf-8")).hexdigest()
    result = request(path, key, company, payload, idempotency="studio-python-" + digest)
    print(json.dumps({"run_id": result.get("id"), "status": result.get("status"),
                      "message": "Track this run in Studio Run history; acceptance is asynchronous."}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print("Import failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
