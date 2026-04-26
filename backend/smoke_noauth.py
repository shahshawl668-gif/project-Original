"""Verify all main endpoints work with NO Authorization header."""
import requests, sys

BASE = "http://127.0.0.1:8000"
OK = True

def check(label, r):
    global OK
    status = "OK" if r.status_code < 400 else "FAIL"
    if status == "FAIL":
        OK = False
    print(f"  [{status}] {r.status_code}  {label}")
    if status == "FAIL":
        print(f"         {r.text[:120]}")

print("\n=== No-auth smoke test ===\n")

check("GET /api/health",                   requests.get(f"{BASE}/api/health"))
check("GET /api/components",               requests.get(f"{BASE}/api/components"))
check("GET /api/settings/statutory",       requests.get(f"{BASE}/api/settings/statutory"))
check("GET /api/rule-engine/slabs",        requests.get(f"{BASE}/api/rule-engine/slabs?rule_type=PT&state=Maharashtra"))
check("GET /api/payroll/registers",        requests.get(f"{BASE}/api/payroll/registers"))
check("GET /api/ctc/uploads",              requests.get(f"{BASE}/api/ctc/uploads"))

# First add a component so validate has something to work with
requests.post(f"{BASE}/api/components",
    json={"component_name":"basic","pf_applicable":True,"esic_applicable":True,"included_in_wages":True,"taxable":True})

payload = {
    "employees": [{"employee_id": "EMP001", "employee_name": "Test User",
                   "basic": 20000, "hra": 8000, "pf_employee": 1800}],
    "run_type": "regular", "period_month": "2025-04-01",
}
r = requests.post(f"{BASE}/api/payroll/validate", json=payload)
check("POST /api/payroll/validate", r)
if r.ok:
    d = r.json()
    print(f"         findings_summary={d.get('findings_summary',{})}")

print()
if OK:
    print("All checks passed — no login required!")
    sys.exit(0)
else:
    print("Some checks FAILED!")
    sys.exit(1)
