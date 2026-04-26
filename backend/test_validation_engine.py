"""
End-to-end smoke test for the Payroll Validation Rule Engine v2.
Run from the backend directory:
    python test_validation_engine.py

Tests every rule group (P1–P7) against hand-crafted employee rows.
"""
import sys
import json
import requests
import time

BASE = "http://127.0.0.1:8000"

# ─── helpers ───────────────────────────────────────────────────────────────

def register(email, password, company="TestCo"):
    r = requests.post(f"{BASE}/api/auth/signup",
                      json={"email": email, "password": password,
                            "company_name": company})
    return r

def login(email, password):
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]

def headers(token):
    return {"Authorization": f"Bearer {token}"}

def setup_components(token, components):
    """Create or overwrite components one by one via POST /api/components."""
    for comp in components:
        r = requests.post(f"{BASE}/api/components",
                          json=comp, headers=headers(token))
        r.raise_for_status()
    return True

def validate(token, employees, run_type="regular",
             period_month=None, from_=None, to_=None):
    payload = {
        "employees": employees,
        "run_type": run_type,
        "period_month": period_month,
        "effective_month_from": from_,
        "effective_month_to": to_,
    }
    r = requests.post(f"{BASE}/api/payroll/validate",
                      json=payload, headers=headers(token))
    r.raise_for_status()
    return r.json()

def assert_finding(findings, rule_id, status="FAIL", msg=""):
    matches = [f for f in findings if f["rule_id"] == rule_id and f["status"] == status]
    assert matches, f"Expected finding {rule_id}={status} but got none. {msg}\nAll findings: {json.dumps([f['rule_id'] for f in findings], indent=2)}"
    return matches

def no_finding(findings, rule_id, status="FAIL"):
    matches = [f for f in findings if f["rule_id"] == rule_id and f["status"] == status]
    assert not matches, f"Unexpected finding {rule_id}={status} present!"

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

# ─── test setup ────────────────────────────────────────────────────────────

section("Setup: register and login")
email = f"testuser_{int(time.time())}@example.com"
password = "SecurePass99"
r = register(email, password)
if r.status_code not in (200, 201):
    # user may already exist from a previous run
    print(f"  Register returned {r.status_code}: {r.text[:80]}")
token = login(email, password)
print(f"  Logged in ✓  (token prefix: {token[:20]}…)")

# ─── configure salary components ───────────────────────────────────────────
section("Setup: configure components")
comps = [
    {"component_name": "basic",      "pf_applicable": True,  "esic_applicable": True,
     "pt_applicable": True, "lwf_applicable": True,
     "included_in_wages": True, "taxable": True},
    {"component_name": "hra",        "pf_applicable": False, "esic_applicable": True,
     "pt_applicable": True, "included_in_wages": True, "taxable": False},
    {"component_name": "special_allowance", "pf_applicable": False, "esic_applicable": True,
     "pt_applicable": True, "included_in_wages": True, "taxable": True},
    {"component_name": "bonus",      "pf_applicable": False, "esic_applicable": False,
     "pt_applicable": False, "included_in_wages": True, "taxable": True},
]
setup_components(token, comps)
print(f"  {len(comps)} components configured ✓")

# ─── test cases ────────────────────────────────────────────────────────────

all_passed = True

def run_case(name, employees, expected_rules=None, unexpected_rules=None,
             run_type="regular", period_month="2025-04-01"):
    global all_passed
    print(f"\n[TEST] {name}")
    data = validate(token, employees, run_type=run_type, period_month=period_month)
    findings = data.get("findings", [])
    summary  = data.get("findings_summary", {})

    print(f"  Total findings: {summary.get('total_findings', len(findings))}")
    print(f"  Critical={summary.get('critical',0)}  Warning={summary.get('warning',0)}  "
          f"Info={summary.get('info',0)}  Pass={summary.get('pass',0)}")

    ok = True
    for rule in (expected_rules or []):
        try:
            matches = assert_finding(findings, rule)
            print(f"  ✓  {rule} FAIL present  ('{matches[0]['reason'][:70]}…')")
        except AssertionError as e:
            print(f"  ✗  {e}")
            ok = False

    for rule in (unexpected_rules or []):
        try:
            no_finding(findings, rule)
            print(f"  ✓  {rule} correctly absent")
        except AssertionError as e:
            print(f"  ✗  {e}")
            ok = False

    if not ok:
        all_passed = False
    return findings, data

# ─────────────────────────────────────────────────────────────────
#  P1: DATA-001 — missing employee ID
# ─────────────────────────────────────────────────────────────────
run_case(
    "P1 · DATA-001 — missing employee ID",
    employees=[{"basic": 12000, "hra": 5000, "special_allowance": 3000}],
    expected_rules=["DATA-001"],
)

# ─────────────────────────────────────────────────────────────────
#  P2: DATA-002 — duplicate employee IDs  (batch-level)
# ─────────────────────────────────────────────────────────────────
run_case(
    "P1/P2 · DATA-002 — duplicate employee IDs",
    employees=[
        {"employee_id": "EMP001", "basic": 15000, "hra": 6000},
        {"employee_id": "EMP001", "basic": 15000, "hra": 6000},
    ],
    expected_rules=["DATA-002"],
)

# ─────────────────────────────────────────────────────────────────
#  P2: COMP-001 — unknown column in register
# ─────────────────────────────────────────────────────────────────
run_case(
    "P2 · COMP-001 — unknown column in register",
    employees=[{
        "employee_id": "EMP002",
        "basic": 20000, "hra": 8000,
        "mystery_pay": 5000,      # ← not in component config
    }],
    expected_rules=["COMP-001"],
)

# ─────────────────────────────────────────────────────────────────
#  P3: AGG-001 — gross pay mismatch
# ─────────────────────────────────────────────────────────────────
run_case(
    "P3 · AGG-001 — gross pay mismatch",
    employees=[{
        "employee_id": "EMP003",
        "basic": 20000, "hra": 8000, "special_allowance": 5000,
        "gross": 99999,           # wrong gross
    }],
    expected_rules=["AGG-001"],
)

# ─────────────────────────────────────────────────────────────────
#  P3: AGG-001 — gross pay CORRECT (should be absent)
# ─────────────────────────────────────────────────────────────────
run_case(
    "P3 · AGG-001 — gross pay CORRECT (no finding expected)",
    employees=[{
        "employee_id": "EMP004",
        "basic": 20000, "hra": 8000, "special_allowance": 5000,
        "gross": 33000,           # correct (20000+8000+5000)
    }],
    unexpected_rules=["AGG-001"],
)

# ─────────────────────────────────────────────────────────────────
#  P4: STAT-001 — PF employee mismatch
#  PF wage = basic (20000) → capped at 15000 → PF = 1800
#  Register shows 2000 → mismatch
# ─────────────────────────────────────────────────────────────────
run_case(
    "P4 · STAT-001 — PF employee mismatch",
    employees=[{
        "employee_id": "EMP005",
        "basic": 20000, "hra": 8000,
        "pf_employee": 2000,      # should be 1800 (15000×12%)
    }],
    expected_rules=["STAT-001"],
)

# ─────────────────────────────────────────────────────────────────
#  P4: STAT-001 — PF correct (ceiling applied)
# ─────────────────────────────────────────────────────────────────
run_case(
    "P4 · STAT-001 — PF employee CORRECT (ceiling 15000)",
    employees=[{
        "employee_id": "EMP006",
        "basic": 20000, "hra": 8000,
        "pf_employee": 1800,      # 15000 × 12% = 1800
    }],
    unexpected_rules=["STAT-001"],
)

# ─────────────────────────────────────────────────────────────────
#  P4: STAT-006 — ESIC employee mismatch
#  ESIC eligible: gross ≤ 21000  |  basic 8000+hra 5000+special 3000=16000
#  Employee ESIC = 16000 × 0.75% = 120  → register has 200
# ─────────────────────────────────────────────────────────────────
run_case(
    "P4 · STAT-006 — ESIC employee mismatch",
    employees=[{
        "employee_id": "EMP007",
        "basic": 8000, "hra": 5000, "special_allowance": 3000,
        "esic_employee": 200,     # wrong (should be 120)
    }],
    expected_rules=["STAT-006"],
)

# ─────────────────────────────────────────────────────────────────
#  P5: LOP-001 — paid + lop ≠ days in month
# ─────────────────────────────────────────────────────────────────
run_case(
    "P5 · LOP-001 — paid_days + lop_days ≠ total days",
    employees=[{
        "employee_id": "EMP008",
        "basic": 30000, "hra": 10000,
        "paid_days": 20, "lop_days": 5,  # 25 ≠ 30 (April has 30 days)
    }],
    expected_rules=["LOP-001"],
)

# ─────────────────────────────────────────────────────────────────
#  P4: STAT-001 — PF mismatch because wage above 15000 (ceiling
#  is applied by default → expected is 1800, register has 6000)
# ─────────────────────────────────────────────────────────────────
run_case(
    "P4 · STAT-001 — PF mismatch (high basic, ceiling applied)",
    employees=[{
        "employee_id": "EMP009",
        "basic": 50000, "hra": 20000,
        "pf_employee": 6000,      # register says 6000 but engine expects 1800 (15000×12%)
    }],
    expected_rules=["STAT-001"],
)

# ─────────────────────────────────────────────────────────────────
#  P4: STAT-005 — ESIC ineligible (gross > 21000)
# ─────────────────────────────────────────────────────────────────
run_case(
    "P4 · STAT-005 — ESIC ineligible (high salary)",
    employees=[{
        "employee_id": "EMP010",
        "basic": 30000, "hra": 10000, "special_allowance": 5000,
        "esic_employee": 0,
    }],
    expected_rules=["STAT-005"],
)

# ─────────────────────────────────────────────────────────────────
#  P7: ADV-001 — zero salary for all components
# ─────────────────────────────────────────────────────────────────
run_case(
    "P7 · DATA-004 — all components are zero",
    employees=[{
        "employee_id": "EMP011",
        "basic": 0, "hra": 0, "special_allowance": 0,
    }],
    expected_rules=["DATA-004"],
)

# ─────────────────────────────────────────────────────────────────
#  SUMMARY
# ─────────────────────────────────────────────────────────────────
section("Final result")
if all_passed:
    print("  ALL TESTS PASSED ✅")
    sys.exit(0)
else:
    print("  SOME TESTS FAILED ❌  — see output above")
    sys.exit(1)
