"""Smoke test for the Config-Driven Statutory Engine endpoints."""
import urllib.request
import json

base = "http://localhost:8000"


def get(path):
    r = urllib.request.urlopen(f"{base}{path}")
    return json.loads(r.read())


def put(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base}{path}", data=data, method="PUT",
        headers={"Content-Type": "application/json"},
    )
    r = urllib.request.urlopen(req)
    return json.loads(r.read())


def post(path, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        f"{base}{path}", data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    r = urllib.request.urlopen(req)
    return json.loads(r.read())


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    return cond


all_passed = True

# 1. GET full config — defaults
cfg = get("/api/config/statutory")
all_passed &= check("GET /config/statutory — tenant_id present", "tenant_id" in cfg)
all_passed &= check("Default PF ceiling = 15000", cfg["pf"]["wage"]["wage_ceiling"] == "15000")
all_passed &= check("Default ESIC ceiling = 21000", cfg["esic"]["wage"]["wage_ceiling"] == "21000")

# 2. Config summary
summary = get("/api/config/statutory/summary")
all_passed &= check("Summary has pf + esic keys", "pf" in summary and "esic" in summary)
all_passed &= check("Summary PF emp rate = 12%", "12" in summary["pf"]["employee_rate"])

# 3. PUT — update PF ceiling
cfg["pf"]["wage"]["wage_ceiling"] = "20000"
saved = put("/api/config/statutory", cfg)
all_passed &= check("PUT persists new PF ceiling", saved["pf"]["wage"]["wage_ceiling"] == "20000")

# 4. GET /pf sub-resource reflects update
pf = get("/api/config/statutory/pf")
all_passed &= check("GET /pf ceiling = 20000", pf["wage"]["wage_ceiling"] == "20000")

# 5. PUT /esic sub-resource
esic = get("/api/config/statutory/esic")
esic["rates"]["employee_rate"] = "0.01"
esic_saved = put("/api/config/statutory/esic", esic)
all_passed &= check("PUT /esic employee rate saved", esic_saved["rates"]["employee_rate"] == "0.01")

# 6. Test expression (safe evaluator)
expr_body = {"expression": "pf_wage > 0", "context": {"pf_wage": 15000}}
expr_result = post("/api/config/statutory/test-expression", expr_body)
all_passed &= check("Expression eval returns bool True", expr_result["result"] is True)

# Unsafe expression should fail gracefully
unsafe = {"expression": "pf_wage > 0", "context": {"pf_wage": 0}}
unsafe_result = post("/api/config/statutory/test-expression", unsafe)
all_passed &= check("Expression eval False for pf_wage=0", unsafe_result["result"] is False)

# 7. Reset to defaults
reset = post("/api/config/statutory/reset")
all_passed &= check("Reset PF ceiling = 15000", reset["pf"]["wage"]["wage_ceiling"] == "15000")

# 8. Validate still works with ConfigService integration
val_body = json.dumps({
    "run_type": "regular",
    "employees": [{"employee_id": "EMP001", "basic": 20000, "hra": 8000,
                   "gross": 28000, "net": 27200, "pf_employee": 1800, "esic_employee": 157}],
}).encode()
req = urllib.request.Request(
    f"{base}/api/payroll/validate", data=val_body,
    headers={"Content-Type": "application/json"},
)
v = json.loads(urllib.request.urlopen(req).read())
all_passed &= check("Validate returns results", len(v["results"]) == 1)
all_passed &= check("Validate returns risk_scores", len(v.get("risk_scores", [])) == 1)
all_passed &= check("Validate findings present", len(v.get("findings", [])) > 0)

print()
print("ALL CHECKS PASSED" if all_passed else "SOME CHECKS FAILED")
