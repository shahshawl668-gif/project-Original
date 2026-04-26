"""Quick demo: one employee with intentional errors, show all findings."""
import requests, json

BASE = "http://127.0.0.1:8000"

# get token
r = requests.post(f"{BASE}/api/auth/login", json={"email":"demo@example.com","password":"demopass1"})
if r.status_code != 200:
    requests.post(f"{BASE}/api/auth/signup", json={"email":"demo@example.com","password":"demopass1","company_name":"Demo"})
    r = requests.post(f"{BASE}/api/auth/login", json={"email":"demo@example.com","password":"demopass1"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# configure components
for comp in [
    {"component_name":"basic","pf_applicable":True,"esic_applicable":True,"pt_applicable":True,"included_in_wages":True,"taxable":True},
    {"component_name":"hra","esic_applicable":True,"pt_applicable":True,"included_in_wages":True},
    {"component_name":"special_allowance","esic_applicable":True,"included_in_wages":True,"taxable":True},
]:
    requests.post(f"{BASE}/api/components", json=comp, headers=h)

# submit payroll with deliberate errors
payload = {
    "employees": [
        {
            "employee_id": "EMP001", "employee_name": "Ravi Kumar",
            "basic": 20000, "hra": 8000, "special_allowance": 5000,
            "gross": 40000,          # wrong (should be 33000)
            "pf_employee": 2500,     # wrong (should be 1800)
            "esic_employee": 250,    # wrong (should be 120 for 16000 wage)
            "paid_days": 22, "lop_days": 5,   # 22+5=27 != 30
        },
        {
            "employee_id": "EMP002", "employee_name": "Priya Sharma",
            "basic": 8000, "hra": 3000, "special_allowance": 2000,
            "gross": 13000,          # correct
            "pf_employee": 960,      # correct (8000*12%)
            "esic_employee": 98,     # correct (13000*0.75%=97.5)
            "paid_days": 30, "lop_days": 0,
            "mystery_column": 5000,  # unknown column
        },
    ],
    "run_type": "regular", "period_month": "2025-04-01"
}

resp = requests.post(f"{BASE}/api/payroll/validate", json=payload, headers=h).json()

print("\n" + "="*70)
print("  FINDINGS SUMMARY")
print("="*70)
s = resp["findings_summary"]
print(f"  Total  : {s['total_findings']}")
print(f"  Critical: {s['critical']}  Warning: {s['warning']}  Info: {s['info']}  Pass: {s['pass']}")

print("\n  Rules triggered:")
for r in s.get("rules_triggered", []):
    print(f"    {r['rule_id']:12}  {r['severity']:8}  x{r['fail_count']}  {r['rule_name']}")

print("\n" + "="*70)
print("  ALL FINDINGS (FAIL only)")
print("="*70)
print(f"  {'SEV':8} {'RULE':10} {'EMP':8} {'COMPONENT':25} {'EXPECTED':12} {'ACTUAL':12}  REASON")
print("  " + "-"*100)
for f in resp["findings"]:
    if f["status"] == "FAIL":
        sev = f["severity"]
        color = ""
        print(f"  {sev:8} {f['rule_id']:10} {f['employee_id']:8} {f['component']:25} "
              f"{f['expected_value']:12} {f['actual_value']:12}  {f['reason'][:60]}")
