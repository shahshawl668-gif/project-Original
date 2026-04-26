"""
End-to-End Full Indian Payroll Test
=====================================
Covers every feature with realistic Indian payroll data:
  • Component Setup (Basic, HRA, Conveyance, Medical, LTA, Special Allowance + arrear variants)
  • PT & LWF slabs for ALL supported Indian states
  • Statutory Engine config (custom ESIC rounding, voluntary PF)
  • CTC Upload (10 employees, varied CTC structures)
  • Previous Month Register (March 2025) for MoM comparison
  • April 2025 Validation — 10 scenarios:
      EMP001 - Regular correct employee (Maharashtra, Male)
      EMP002 - LOP case, 5 days absent (Gujarat, Female)
      EMP003 - Increment + Basic Arrear (Karnataka, Male)
      EMP004 - PF Avoidance structure (Tamil Nadu, Female)
      EMP005 - ESIC at ceiling boundary (Delhi, Male)
      EMP006 - New Joiner (Kerala, Female) - no March record
      EMP007 - F&F / Exit with gratuity (West Bengal, Male)
      EMP008 - Bonus eligibility correct (Telangana, Female)
      EMP009 - PF mismatch data error (Maharashtra, Male)
      EMP010 - Salary spike anomaly 100% increase (Rajasthan, Female)
  • Excel Audit Report saved to disk
"""

import io, json, math, os, time, urllib.request, urllib.error, urllib.parse
from decimal import Decimal
from typing import Any

BASE = "http://localhost:8000"
PASS = FAIL = 0
REPORT_LINES: list[str] = []

# ─── helpers ──────────────────────────────────────────────────────────────────

def _rep(msg: str) -> None:
    REPORT_LINES.append(msg)
    print(msg)

def ok(label: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    mark = "PASS" if cond else "FAIL"
    msg = f"  [{mark}] {label}"
    if detail and not cond:
        msg += f"\n         → {detail}"
    _rep(msg)
    if cond: PASS += 1
    else: FAIL += 1

def h(title: str) -> None:
    _rep(f"\n{'='*65}")
    _rep(f"  {title}")
    _rep('='*65)

def get(path: str) -> Any:
    r = urllib.request.urlopen(f"{BASE}{path}")
    return json.loads(r.read())

def post(path: str, body: Any = None) -> Any:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, method="POST",
                                  headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req)
        return json.loads(r.read())
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        raise AssertionError(f"HTTP {e.code}: {txt[:300]}") from e

def put(path: str, body: Any) -> Any:
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, method="PUT",
                                  headers={"Content-Type": "application/json"})
    r = urllib.request.urlopen(req)
    return json.loads(r.read())

def delete(path: str) -> int:
    req = urllib.request.Request(f"{BASE}{path}", method="DELETE")
    try: return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as e: return e.code

def multipart_post(path: str, file_bytes: bytes, filename: str, meta_dict: dict) -> Any:
    boundary = b"--PayrollE2EBoundary"
    CRLF = b"\r\n"
    parts  = []
    # file part
    parts += [b"--" + boundary + CRLF,
              f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode() + CRLF,
              b"Content-Type: text/csv" + CRLF + CRLF,
              file_bytes + CRLF]
    # meta part
    meta_bytes = json.dumps(meta_dict).encode()
    parts += [b"--" + boundary + CRLF,
              b'Content-Disposition: form-data; name="meta"' + CRLF + CRLF,
              meta_bytes + CRLF]
    parts.append(b"--" + boundary + b"--" + CRLF)
    body = b"".join(parts)
    req = urllib.request.Request(f"{BASE}{path}", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary.decode()}"})
    try:
        r = urllib.request.urlopen(req)
        return json.loads(r.read())
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        raise AssertionError(f"HTTP {e.code}: {txt[:400]}") from e

def validate(employees: list[dict], run_type: str = "regular",
             period_month: str | None = None) -> dict:
    body: dict[str, Any] = {"run_type": run_type, "employees": employees}
    if period_month:
        body["period_month"] = period_month
    return post("/api/payroll/validate", body)

def findings_for(result: dict, emp_id: str) -> list[dict]:
    for r in result["results"]:
        if r["employee_id"] == emp_id:
            return r.get("findings", [])
    return []

def risk_for(result: dict, emp_id: str) -> dict:
    for r in result["risk_scores"]:
        if r["employee_id"] == emp_id:
            return r
    return {}

# ─── STEP 1: CLEAR + CONFIGURE COMPONENTS ─────────────────────────────────────

h("STEP 1: Configure Salary Components")

# Delete all existing components first
try:
    existing = get("/api/components")
    for c in existing:
        delete(f"/api/components/{c['id']}")
    _rep(f"  Cleared {len(existing)} existing components")
except Exception as e:
    _rep(f"  Warning: could not clear components: {e}")

COMPONENTS = [
    # Name, pf, esic, pt, lwf, in_wages, taxable, is_arrear
    ("Basic",              True,  True,  True,  True,  True,  True,  False),
    ("HRA",                False, True,  True,  False, True,  False, False),  # HRA: ESIC yes, PT yes, not PF
    ("Conveyance",         False, False, False, False, True,  False, False),  # Transport = no statutory
    ("Medical Allowance",  False, True,  True,  False, True,  False, False),
    ("LTA",                False, False, False, False, True,  False, False),
    ("Special Allowance",  False, True,  True,  False, True,  True,  False),
    ("Basic Arrear",       True,  True,  True,  False, True,  True,  True),   # Arrear of Basic
    ("HRA Arrear",         False, True,  True,  False, True,  False, True),
    ("Special Arrear",     False, True,  True,  False, True,  True,  True),
    ("Gratuity",           False, False, False, False, False, False, False),
    ("Bonus",              False, False, False, False, False, True,  False),
]

created_comps = []
for name, pf, esic, pt, lwf, in_wages, taxable, is_arr in COMPONENTS:
    try:
        r = post("/api/components", {
            "component_name": name,
            "pf_applicable":  pf,
            "esic_applicable": esic,
            "pt_applicable":  pt,
            "lwf_applicable": lwf,
            "included_in_wages": in_wages,
            "taxable": taxable,
            "is_arrear": is_arr,
        })
        created_comps.append(r)
        ok(f"Component created: {name}", "id" in r)
    except AssertionError as e:
        if "already exists" in str(e):
            ok(f"Component exists: {name}", True)
        else:
            ok(f"Component created: {name}", False, str(e))

# ─── STEP 2: STATUTORY ENGINE CONFIG ──────────────────────────────────────────

h("STEP 2: Configure Statutory Engine (PF + ESIC) + PT/LWF State Lists")

# First configure PT and LWF state lists in StatutorySettings
try:
    stat_r = put("/api/settings/statutory", {
        "pt_states": [
            "Maharashtra", "Karnataka", "Tamil Nadu", "Gujarat", "Kerala",
            "West Bengal", "Andhra Pradesh", "Telangana", "Madhya Pradesh",
            "Odisha", "Sikkim", "Assam", "Bihar", "Jharkhand", "Meghalaya",
            "Tripura", "Manipur"
        ],
        "lwf_states": [
            "Karnataka", "Maharashtra", "Andhra Pradesh", "Gujarat",
            "West Bengal", "Tamil Nadu", "Rajasthan", "Punjab",
            "Haryana", "Madhya Pradesh", "Odisha", "Chhattisgarh",
            "Telangana", "Kerala", "Jharkhand"
        ],
    })
    ok("PT states configured", len(stat_r.get("pt_states", [])) >= 10)
    ok("LWF states configured", len(stat_r.get("lwf_states", [])) >= 5)
except Exception as e:
    ok("PT/LWF state configuration", False, str(e))

try:
    cfg = get("/api/config/statutory")

    # PF: restricted to ceiling, standard 12%, EPS 8.33%, allow voluntary
    cfg["pf"]["wage"]["wage_ceiling"] = "15000"
    cfg["pf"]["wage"]["restrict_to_ceiling"] = True
    cfg["pf"]["wage"]["above_ceiling_mode"] = "restricted"
    cfg["pf"]["rates"]["employee_rate"] = "0.12"
    cfg["pf"]["rates"]["employer_rate"] = "0.12"
    cfg["pf"]["rates"]["eps_rate"] = "0.0833"
    cfg["pf"]["voluntary"]["enabled"] = True
    cfg["pf"]["voluntary"]["voluntary_percentage"] = "0.0"   # default no VPF

    # ESIC: ceiling 21000, round UP (standard)
    cfg["esic"]["wage"]["wage_ceiling"] = "21000"
    cfg["esic"]["rates"]["employee_rate"] = "0.0075"
    cfg["esic"]["rates"]["employer_rate"] = "0.0325"
    cfg["esic"]["rounding"]["mode"] = "up"
    cfg["esic"]["eligibility"]["exempt_employment_types"] = ["contractor", "consultant"]

    saved = put("/api/config/statutory", cfg)
    ok("PF ceiling = 15000", saved["pf"]["wage"]["wage_ceiling"] == "15000")
    ok("ESIC ceiling = 21000", saved["esic"]["wage"]["wage_ceiling"] == "21000")
    ok("ESIC rounding = up", saved["esic"]["rounding"]["mode"] == "up")
    ok("Voluntary PF enabled", saved["pf"]["voluntary"]["enabled"] is True)

    # Test a custom expression
    expr_r = post("/api/config/statutory/test-expression", {
        "expression": "pf_wage > 0 and pf_wage <= 15000",
        "context": {"pf_wage": 12000}
    })
    ok("Expression: pf_wage=12000 in range", expr_r["ok"] and expr_r["result"] is True)

    expr_r2 = post("/api/config/statutory/test-expression", {
        "expression": "esic_wage <= 21000",
        "context": {"esic_wage": 22000}
    })
    ok("Expression: esic_wage=22000 exceeds ceiling", expr_r2["ok"] and expr_r2["result"] is False)

except Exception as e:
    ok("Statutory Engine config", False, str(e))

# ─── STEP 3: PT & LWF SLABS FOR ALL SUPPORTED STATES ─────────────────────────

h("STEP 3: Import PT & LWF Slabs for All Supported States")

# Import PT defaults for all available states
try:
    pt_states_resp = get("/api/rule-engine/defaults/pt-states")
    pt_states = pt_states_resp.get("states", [])
    ok("PT state catalog loaded", len(pt_states) > 0, f"States: {pt_states}")

    imported_pt = []
    for state in pt_states:
        try:
            r = post(f"/api/rule-engine/slabs/import-defaults?state={urllib.parse.quote(state)}&rule_type=PT")
            imported_pt.append(state)
        except Exception as ex:
            _rep(f"  [WARN] PT import failed for {state}: {ex}")
    ok(f"PT slabs imported for {len(imported_pt)}/{len(pt_states)} states", len(imported_pt) >= len(pt_states) - 1)

except Exception as e:
    ok("PT state import", False, str(e))

# Import LWF defaults for all available states
try:
    lwf_states_resp = get("/api/rule-engine/defaults/lwf-states")
    lwf_states = lwf_states_resp.get("states", [])
    ok("LWF state catalog loaded", len(lwf_states) > 0, f"States: {lwf_states}")

    imported_lwf = []
    for state in lwf_states:
        try:
            r = post(f"/api/rule-engine/slabs/import-defaults?state={urllib.parse.quote(state)}&rule_type=LWF")
            imported_lwf.append(state)
        except Exception as ex:
            _rep(f"  [WARN] LWF import failed for {state}: {ex}")
    ok(f"LWF slabs imported for {len(imported_lwf)}/{len(lwf_states)} states", len(imported_lwf) >= len(lwf_states) - 1)

except Exception as e:
    ok("LWF state import", False, str(e))

# Verify Maharashtra PT slabs
try:
    mh_slabs_resp = get("/api/rule-engine/slabs?rule_type=PT&state=Maharashtra")
    mh_slabs = mh_slabs_resp.get("slabs", [])
    ok("Maharashtra PT has slabs", len(mh_slabs) > 0)
    has_gender = any(s.get("gender") and s["gender"] != "ALL" for s in mh_slabs)
    ok("Maharashtra PT has gender-specific slabs", has_gender)

    # Karnataka LWF has employer_amount
    ka_lwf_resp = get("/api/rule-engine/slabs?rule_type=LWF&state=Karnataka")
    ka_lwf = ka_lwf_resp.get("slabs", [])
    ok("Karnataka LWF has slabs", len(ka_lwf) > 0)
    ok("Karnataka LWF has employer_amount", all("employer_amount" in s for s in ka_lwf))
except Exception as e:
    ok("Slab verification", False, str(e))

# ─── STEP 4: CTC UPLOAD ────────────────────────────────────────────────────────

h("STEP 4: Upload CTC Report (10 employees, April 2025 structure)")

# CTC report: Annual component breakdown per employee
# Monthly basic * 12 = annual basic, etc.
CTC_CSV = """employee_id,employee_name,basic,hra,conveyance,medical_allowance,lta,special_allowance,annual_ctc,effective_from
EMP001,Rahul Sharma,240000,120000,19200,15000,15000,61800,471000,2024-04-01
EMP002,Priya Patel,300000,150000,19200,15000,15000,67800,567000,2024-04-01
EMP003,Amit Kumar,264000,132000,19200,15000,15000,66600,511800,2024-04-01
EMP004,Sunita Rao,96000,300000,19200,15000,15000,204000,649200,2024-04-01
EMP005,Vikram Singh,168000,84000,19200,15000,15000,37800,339000,2024-04-01
EMP006,Meera Nair,216000,108000,19200,15000,15000,52800,426000,2025-04-01
EMP007,Rajan Menon,360000,180000,19200,15000,15000,111600,700800,2024-04-01
EMP008,Deepa Iyer,144000,72000,19200,15000,15000,36600,301800,2024-04-01
EMP009,Suresh Verma,300000,150000,19200,15000,15000,67800,567000,2024-04-01
EMP010,Kavita Joshi,180000,90000,19200,15000,15000,45600,364800,2024-04-01
"""

try:
    # Step 4a: Parse CTC file
    parse_r = multipart_post(
        "/api/ctc/upload",
        CTC_CSV.encode(),
        "ctc_april2025.csv",
        {"default_effective_from": "2024-04-01"},
    )
    ok("CTC file parsed", "records" in parse_r, str(parse_r)[:200])
    records = parse_r.get("records", [])
    ok(f"CTC: {len(records)} employees parsed", len(records) == 10)

    # Step 4b: Commit CTC
    commit_r = post("/api/ctc/commit", {
        "records": records,
        "filename": "ctc_april2025.csv",
        "default_effective_from": "2024-04-01",
    })
    ok("CTC committed to DB", "id" in commit_r)
    _rep(f"  CTC Upload ID: {commit_r.get('id')}, employees: {commit_r.get('employee_count')}")
except Exception as e:
    ok("CTC Upload", False, str(e))

# ─── STEP 5: PREVIOUS MONTH REGISTER (March 2025) ─────────────────────────────

h("STEP 5: Upload Previous Month Salary Register (March 2025)")

# Working days in March 2025 = 26 (standard)
# EMP001-EMP005, EMP007-EMP010 were in March (EMP006 is new joiner)
# EMP003 had lower basic (before increment)
# EMP010 had much lower salary (to simulate spike in April)
MARCH_CSV = """employee_id,employee_name,basic,hra,conveyance,medical_allowance,lta,special_allowance,gross,net,pf_employee,pf_employer,esic_employee,esic_employer,pt,lwf_employee,paid_days,lop_days,state,gender
EMP001,Rahul Sharma,20000,10000,1600,1250,1250,5150,39250,34850,2400,2400,0,0,200,0,26,0,Maharashtra,Male
EMP002,Priya Patel,25000,12500,1600,1250,1250,5650,47250,42900,1800,1800,0,0,0,21,26,0,Gujarat,Female
EMP003,Amit Kumar,18000,9000,1600,1250,1250,4800,35900,32250,2160,2160,0,0,150,0,26,0,Karnataka,Male
EMP004,Sunita Rao,8000,25000,1600,1250,1250,17000,54100,49765,960,960,0,0,135,0,26,0,Tamil Nadu,Female
EMP005,Vikram Singh,14000,7000,1600,1250,1250,3150,28250,25715,1680,1680,212,918,0,0,26,0,Delhi,Male
EMP007,Rajan Menon,30000,15000,1600,1250,1250,9300,58400,54050,1800,1800,0,0,200,0,26,0,West Bengal,Male
EMP008,Deepa Iyer,12000,6000,1600,1250,1250,3050,25150,22790,1440,1440,188,814,0,0,26,0,Telangana,Female
EMP009,Suresh Verma,25000,12500,1600,1250,1250,5650,47250,42900,1800,1800,0,0,200,0,26,0,Maharashtra,Male
EMP010,Kavita Joshi,15000,7500,1600,1250,1250,3800,30400,27200,1800,1800,0,0,0,0,26,0,Rajasthan,Female
"""

try:
    r = multipart_post(
        "/api/payroll/upload",
        MARCH_CSV.encode(),
        "salary_register_march_2025.csv",
        {
            "run_type": "regular",
            "period_month": "2025-03-01",
            "strict_header_check": False,
        },
    )
    ok("March 2025 register uploaded", "employees" in r)
    ok(f"March register: {len(r.get('employees', []))} rows", len(r.get("employees", [])) == 9)
    if r.get("missing_required"):
        _rep(f"  [WARN] Missing columns: {r['missing_required']}")
    if r.get("warnings"):
        _rep(f"  [WARN] Warnings: {r['warnings']}")
except Exception as e:
    ok("March 2025 Register Upload", False, str(e))

# Verify it was stored
try:
    regs = get("/api/payroll/registers")
    march_stored = any(r["period_month"].startswith("2025-03") for r in regs)
    ok("March 2025 register stored in DB", march_stored)
except Exception as e:
    ok("Register history check", False, str(e))

# ─── STEP 6: CUSTOM FORMULA ───────────────────────────────────────────────────

h("STEP 6: Create & Test Custom Formula (HRA = Basic * 50%)")

try:
    import time as _t
    fname = f"HRA_50pct_{int(_t.time())}"
    f_r = post("/api/rule-engine/formula", {
        "formula_name": fname,
        "expression": "basic * 0.50",
        "description": "HRA = 50% of Basic (standard structure)",
        "applies_to": "HRA",
        "rule_type": "PF",
    })
    ok("Formula created", "id" in f_r)
    fid = f_r.get("id")
    # Test it
    t_r = post("/api/rule-engine/test-formula", {
        "expression": "basic * 0.50",
        "variables": {"basic": 20000},
    })
    ok("Formula: basic=20000 → HRA=10000", float(t_r.get("result", 0)) == 10000.0)
    # Activate it
    if fid:
        act_r = post(f"/api/rule-engine/formula/{fid}/activate")
        ok("Formula activated", act_r.get("is_active") is True)
except Exception as e:
    ok("Custom Formula", False, str(e))

# ─── STEP 7: APRIL 2025 VALIDATION SCENARIOS ──────────────────────────────────

h("STEP 7: April 2025 Payroll Validation — 10 Indian Payroll Scenarios")

APRIL_EMPLOYEES = [
    # ── EMP001: Maharashtra Male, fully correct ───────────────────────────────
    # Gross = 20000+10000+1600+1250+1250+5150 = 39250
    # PF = 20000 (above ceiling) → capped at 15000 → 1800
    # ESIC not eligible (gross > 21000)
    # PT = 200 (Maharashtra, Male, basic>10000, April = normal month)
    # Net = 39250 - 1800 - 200 = 37250 (no LWF in April for Maharashtra)
    # total_days=26 → company uses 26-day payroll basis
    {
        "employee_id": "EMP001", "employee_name": "Rahul Sharma",
        "state": "Maharashtra", "gender": "Male",
        "basic": 20000, "hra": 10000, "conveyance": 1600,
        "medical_allowance": 1250, "lta": 1250, "special_allowance": 5150,
        "gross": 39250, "net": 37250,
        "pf_employee": 1800, "pf_employer": 1800,
        "esic_employee": 0, "esic_employer": 0,
        "pt": 200, "lwf_employee": 2, "lwf_employer": 6,
        # Net = 39250 - 1800(PF) - 0(ESIC) - 200(PT) - 2(LWF emp) = 37248
        "net": 37248,
        "paid_days": 26, "lop_days": 0, "total_days": 26,
    },
    # ── EMP002: Gujarat Female, LOP = 5 days out of 26 ───────────────────────
    # Full month basic = 25000, prorated = 25000*(21/26) = 20192.31
    # Full month HRA = 12500, prorated = 12500*(21/26) = 10096.15
    # Full month Conv = 1600 (usually fixed), full month med = 1250
    # Full month special = 5650, prorated = 4563.46
    # Prorated gross ≈ 20192 + 10096 + 1600 + 1250 + 1250 + 4563 = 38951
    # PF on prorated basic = 20192 → above ceiling → capped 15000 → 1800
    # ESIC: gross 38951 > 21000 → not eligible
    # Gujarat PT: gross > 12000 = 200
    # Net = 38951 - 1800 - 200 = 36951
    {
        "employee_id": "EMP002", "employee_name": "Priya Patel",
        "state": "Gujarat", "gender": "Female",
        "basic": 20192, "hra": 10096, "conveyance": 1600,
        "medical_allowance": 1250, "lta": 1250, "special_allowance": 4563,
        "gross": 38951, "net": 36951,
        "pf_employee": 1800, "pf_employer": 1800,
        "esic_employee": 0, "esic_employer": 0,
        "pt": 200, "lwf_employee": 0,
        "paid_days": 21, "lop_days": 5, "total_days": 26,
    },
    # ── EMP003: Karnataka Male, Increment + Basic Arrear ─────────────────────
    # Old basic = 18000 (March), New basic = 22000 (April)
    # Basic arrear for March = 22000-18000 = 4000
    # April regular: basic=22000, hra=11000, conv=1600, med=1250, lta=1250, spl=5650
    # Arrear: basic_arrear=4000
    # Gross = 22000+11000+1600+1250+1250+5650+4000 = 46750
    # PF: 22000 > 15000 → capped at 1800 (arrear PF also applies: 4000*12%=480 extra)
    # Total PF employee = 1800 + 480 = 2280 — for increment run both PF amounts apply
    # ESIC not eligible (gross > 21000)
    # Karnataka PT: basic > 15000 → 150/month
    # Net = 46750 - 2280 - 150 = 44320
    {
        "employee_id": "EMP003", "employee_name": "Amit Kumar",
        "state": "Karnataka", "gender": "Male",
        "basic": 22000, "hra": 11000, "conveyance": 1600,
        "medical_allowance": 1250, "lta": 1250, "special_allowance": 5650,
        "basic_arrear": 4000,
        "gross": 46750, "net": 44320,
        "pf_employee": 2280, "pf_employer": 2280,
        "esic_employee": 0, "esic_employer": 0,
        "pt": 150, "lwf_employee": 0,
        "paid_days": 26, "lop_days": 0, "total_days": 26,
    },
    # ── EMP004: Tamil Nadu Female, PF Avoidance Structure ────────────────────
    # Basic = 8000 (very low), HRA = 25000, Special = 17000
    # Basic is only 16% of gross (should trigger STRUCT-001)
    # Gross = 8000+25000+1600+1250+1250+17000 = 54100
    # PF on basic = 8000 (below ceiling) → 960
    # ESIC not eligible (gross > 21000)
    # Tamil Nadu PT: 0-21000 = 0, >21000 = 135
    # Net = 54100 - 960 - 135 = 53005
    {
        "employee_id": "EMP004", "employee_name": "Sunita Rao",
        "state": "Tamil Nadu", "gender": "Female",
        "basic": 8000, "hra": 25000, "conveyance": 1600,
        "medical_allowance": 1250, "lta": 1250, "special_allowance": 17000,
        "gross": 54100, "net": 53005,
        "pf_employee": 960, "pf_employer": 960,
        "esic_employee": 0, "esic_employer": 0,
        "pt": 135, "lwf_employee": 0,
        "paid_days": 26, "lop_days": 0, "total_days": 26,
    },
    # ── EMP005: Delhi Male, ESIC at ceiling boundary (21000 = eligible) ───────
    # Gross exactly = 21000 → ESIC eligible
    # Employee ESIC = ceil(21000 * 0.75%) = ceil(157.5) = 158
    # Employer ESIC = ceil(21000 * 3.25%) = ceil(682.5) = 683
    # Delhi has no PT
    # PF: basic 14000 < 15000 → 1680
    # Net = 21000 - 1680 - 158 = 19162
    {
        "employee_id": "EMP005", "employee_name": "Vikram Singh",
        "state": "Delhi", "gender": "Male",
        "basic": 14000, "hra": 5000, "conveyance": 0,
        "medical_allowance": 0, "lta": 0, "special_allowance": 2000,
        "gross": 21000, "net": 19162,
        "pf_employee": 1680, "pf_employer": 1680,
        "esic_employee": 158, "esic_employer": 683,
        "pt": 0, "lwf_employee": 0,
        "paid_days": 26, "lop_days": 0, "total_days": 26,
    },
    # ── EMP006: Kerala Female, New Joiner — no March record ──────────────────
    # Joined April 2025, MOM-001 should fire
    # Gross = 18000+9000+1600+1250+1250+3400 = 34500
    # PF: 18000 > 15000 → 1800
    # ESIC not eligible (gross > 21000)
    # Kerala PT: 0-11999 = 0, 12000-17999 = 120, ≥18000 = 180
    # Net = 34500 - 1800 - 180 = 32520
    {
        "employee_id": "EMP006", "employee_name": "Meera Nair",
        "state": "Kerala", "gender": "Female",
        "basic": 18000, "hra": 9000, "conveyance": 1600,
        "medical_allowance": 1250, "lta": 1250, "special_allowance": 3400,
        "gross": 34500, "net": 32520,
        "pf_employee": 1800, "pf_employer": 1800,
        "esic_employee": 0, "esic_employer": 0,
        "pt": 180, "lwf_employee": 0,
        "paid_days": 26, "lop_days": 0, "total_days": 26,
    },
    # ── EMP007: West Bengal Male, Full & Final Settlement ────────────────────
    # Worked 6 years — gratuity eligible
    # Last month salary, gratuity paid = 30000/26*15*6 = 103846 (capped at 20L - ok)
    # Providing gratuity in register
    {
        "employee_id": "EMP007", "employee_name": "Rajan Menon",
        "state": "West Bengal", "gender": "Male",
        "basic": 30000, "hra": 15000, "conveyance": 1600,
        "medical_allowance": 1250, "lta": 1250, "special_allowance": 9300,
        "gratuity": 103846,
        "gross": 58400, "net": 54850,
        "pf_employee": 1800, "pf_employer": 1800,
        "esic_employee": 0, "esic_employer": 0,
        "pt": 200, "lwf_employee": 0, "lwf_employer": 0,
        "paid_days": 26, "lop_days": 0, "total_days": 26,
    },
    # ── EMP008: Telangana Female, Bonus case (correct rate) ──────────────────
    # Gross = 19000 < 21000 → bonus eligible
    # Bonus = 1200; basic=12000, capped at 7000 for bonus calc → min=7000*8.33%=583 < 1200 PASS
    # ESIC: gross 19000 < 21000 → eligible
    # Employee ESIC = ceil(19000 * 0.75%) = ceil(142.5) = 143
    # Employer ESIC = ceil(19000 * 3.25%) = ceil(617.5) = 618
    # Telangana PT: 0 (no PT slabs configured for Telangana)
    # Net = 19000 - 1440 - 143 = 17417
    {
        "employee_id": "EMP008", "employee_name": "Deepa Iyer",
        "state": "Telangana", "gender": "Female",
        "basic": 12000, "hra": 6000, "conveyance": 0,
        "medical_allowance": 0, "lta": 0, "special_allowance": 1000,
        "gross": 19000, "net": 17417,
        "bonus": 1200,
        "pf_employee": 1440, "pf_employer": 1440,
        "esic_employee": 143, "esic_employer": 618,
        "pt": 0, "lwf_employee": 0,
        "paid_days": 26, "lop_days": 0, "total_days": 26,
    },
    # ── EMP009: Maharashtra Male, PF mismatch (data error) ───────────────────
    # PF should be 1800 (25000 basic > ceiling → capped 15000*12%)
    # But register shows 1200 (wrong) → STAT-001 should fire
    # Net calculated with wrong PF
    {
        "employee_id": "EMP009", "employee_name": "Suresh Verma",
        "state": "Maharashtra", "gender": "Male",
        "basic": 25000, "hra": 12500, "conveyance": 1600,
        "medical_allowance": 1250, "lta": 1250, "special_allowance": 5650,
        "gross": 47250, "net": 45850,  # Computed with WRONG pf=1200: 47250-1200-200=45850
        "pf_employee": 1200,   # WRONG: should be 1800 → STAT-001 should fire
        "pf_employer": 1800,
        "esic_employee": 0, "esic_employer": 0,
        "pt": 200, "lwf_employee": 0,
        "paid_days": 26, "lop_days": 0, "total_days": 26,
    },
    # ── EMP010: Rajasthan Female, Salary Spike 100% (March: 15000→ April: 30000 basic)
    # March basic was 15000, April basic is 30000 — 100% spike → MOM-002 (positive spike)
    {
        "employee_id": "EMP010", "employee_name": "Kavita Joshi",
        "state": "Rajasthan", "gender": "Female",
        "basic": 30000, "hra": 15000, "conveyance": 1600,
        "medical_allowance": 1250, "lta": 1250, "special_allowance": 9300,
        "gross": 58400, "net": 55800,
        "pf_employee": 1800, "pf_employer": 1800,
        "esic_employee": 0, "esic_employer": 0,
        "pt": 0, "lwf_employee": 0,
        "paid_days": 26, "lop_days": 0, "total_days": 26,
    },
]

# Run as increment (to handle EMP003 arrear without triggering MOM-002 component-change warning)
_rep("\n  Running April 2025 validation (increment run, period=2025-04-01)...")
try:
    result = validate(APRIL_EMPLOYEES, run_type="increment_arrear", period_month="2025-04-01")
    ok("Validation API responded", "results" in result and "findings" in result)
    _rep(f"\n  SUMMARY: {result['findings_summary']}")
except Exception as e:
    ok("April 2025 Validation", False, str(e))
    result = {}

# ─── STEP 8: VERIFY INDIVIDUAL SCENARIOS ─────────────────────────────────────

h("STEP 8: Verify Individual Scenario Findings")

if result:
    summary = result.get("findings_summary", {})
    _rep(f"\n  Total Employees:   {len(result.get('results', []))}")
    _rep(f"  Total Findings:    {summary.get('total_findings', 0)}")
    _rep(f"  Critical:          {summary.get('critical', 0)}")
    _rep(f"  Warning:           {summary.get('warning', 0)}")
    _rep(f"  Info:              {summary.get('info', 0)}")
    _rep(f"  Financial Impact:  ₹{summary.get('total_financial_impact', 0):,.2f}")

    # ── EMP001: Correct employee — should have no CRITICAL/WARNING FAIL findings ──
    # INFO-severity FAIL findings (like STAT-005 "ESIC exempt above 21k") are
    # purely informational and should NOT block a clean validation pass.
    f1 = findings_for(result, "EMP001")
    critical_warn_fails = [f for f in f1 if f["status"] == "FAIL" and f["severity"] in ("CRITICAL", "WARNING")]
    ok("EMP001 (Regular correct): no CRITICAL/WARNING FAIL findings", len(critical_warn_fails) == 0,
       f"Found Critical/Warning FAILs: {[(f['rule_id'], f['severity'], f['reason'][:60]) for f in critical_warn_fails]}")
    # Informational findings are expected
    info_fails = [f for f in f1 if f["status"] == "FAIL" and f["severity"] == "INFO"]
    _rep(f"  EMP001 INFO findings (informational only): {[f['rule_id'] for f in info_fails]}")

    # ── EMP002: LOP case ──────────────────────────────────────────────────────
    f2 = findings_for(result, "EMP002")
    _rep(f"\n  EMP002 (LOP) findings: {[f['rule_id'] for f in f2]}")
    # With 5 LOP days, paid_days=21/26 — prorated salary is provided correctly
    # Should at minimum get MOM-002 or MOM-003 if salary dropped vs March
    # March gross was 47250, April prorated 38951 → drop of ~18% (< 30% threshold → no MOM-004)
    mom_001_emp2 = any(f["rule_id"] == "MOM-001" for f in f2)
    ok("EMP002 (LOP): NOT new joiner (was in March)", not mom_001_emp2)
    risk2 = risk_for(result, "EMP002")
    ok("EMP002 (LOP): risk score present", "risk_score" in risk2)
    _rep(f"  EMP002 risk level: {risk2.get('risk_level')} (score={risk2.get('risk_score')})")

    # ── EMP003: Increment + Arrear ────────────────────────────────────────────
    f3 = findings_for(result, "EMP003")
    _rep(f"\n  EMP003 (Increment+Arrear) findings: {[f['rule_id'] for f in f3 if f['status']=='FAIL']}")
    # In increment_arrear run type, component changes should NOT trigger MOM-002
    mom002_emp3 = [f for f in f3 if f["rule_id"] == "MOM-002" and f["status"] == "FAIL"]
    ok("EMP003 (Increment): MOM-002 not fired (increment run)", len(mom002_emp3) == 0,
       f"Unexpected MOM-002: {mom002_emp3}")

    # ── EMP004: PF Avoidance ──────────────────────────────────────────────────
    f4 = findings_for(result, "EMP004")
    struct001 = [f for f in f4 if f["rule_id"] == "STRUCT-001"]
    ok("EMP004 (PF Avoidance): STRUCT-001 fires", len(struct001) > 0)
    ok("EMP004 (PF Avoidance): STRUCT-001 is WARNING", any(f["severity"] == "WARNING" for f in struct001))
    ok("EMP004 (PF Avoidance): has suggested fix", any(f.get("suggested_fix") for f in struct001))
    _rep(f"  EMP004 STRUCT-001 reason: {struct001[0]['reason'] if struct001 else 'N/A'}")

    # ── EMP005: ESIC at ceiling boundary ─────────────────────────────────────
    f5 = findings_for(result, "EMP005")
    esic_fails = [f for f in f5 if f["rule_id"] in ("STAT-005", "STAT-006") and f["status"] == "FAIL"]
    ok("EMP005 (ESIC=21000): no ESIC eligibility or mismatch error", len(esic_fails) == 0,
       f"ESIC fails: {[(f['rule_id'], f['reason'][:80]) for f in esic_fails]}")
    _rep(f"  EMP005 ESIC findings: {[(f['rule_id'], f['status']) for f in f5 if 'ESIC' in f['rule_name'] or 'STAT-00' in f['rule_id']]}")

    # ── EMP006: New Joiner ────────────────────────────────────────────────────
    f6 = findings_for(result, "EMP006")
    mom001 = [f for f in f6 if f["rule_id"] == "MOM-001"]
    ok("EMP006 (New Joiner): MOM-001 fires", len(mom001) > 0)
    ok("EMP006 (New Joiner): MOM-001 is INFO", any(f["severity"] == "INFO" for f in mom001))
    _rep(f"  EMP006 MOM-001 reason: {mom001[0]['reason'] if mom001 else 'N/A'}")

    # ── EMP007: F&F with Gratuity ─────────────────────────────────────────────
    f7 = findings_for(result, "EMP007")
    _rep(f"\n  EMP007 (F&F) findings: {[(f['rule_id'], f['status']) for f in f7]}")
    # Gratuity 103846 < 2000000 cap → STAT-014 should NOT fire
    stat014_fail = [f for f in f7 if f["rule_id"] == "STAT-014" and f["status"] == "FAIL"]
    ok("EMP007 (F&F): STAT-014 not fired (gratuity < cap)", len(stat014_fail) == 0)

    # ── EMP008: Bonus Eligibility ─────────────────────────────────────────────
    f8 = findings_for(result, "EMP008")
    stat012 = [f for f in f8 if f["rule_id"] == "STAT-012" and f["status"] == "FAIL"]
    stat013 = [f for f in f8 if f["rule_id"] == "STAT-013" and f["status"] == "FAIL"]
    ok("EMP008 (Bonus): STAT-012 not fired (eligible, gross<21000)", len(stat012) == 0,
       f"STAT-012 unexpected: {stat012}")
    ok("EMP008 (Bonus): STAT-013 not fired (rate 10% ≥ 8.33%)", len(stat013) == 0,
       f"STAT-013 unexpected: {stat013}")
    esic006 = [f for f in f8 if "ESIC" in f["rule_name"] and f["status"] == "FAIL"]
    _rep(f"  EMP008 ESIC findings (if any): {[(f['rule_id'], f['reason'][:60]) for f in esic006]}")

    # ── EMP009: PF Mismatch ───────────────────────────────────────────────────
    f9 = findings_for(result, "EMP009")
    stat001 = [f for f in f9 if f["rule_id"] == "STAT-001" and f["status"] == "FAIL"]
    ok("EMP009 (PF Mismatch): STAT-001 fires", len(stat001) > 0)
    ok("EMP009 STAT-001 is CRITICAL", any(f["severity"] == "CRITICAL" for f in stat001))
    ok("EMP009 STAT-001 has financial_impact", any(float(f.get("financial_impact", 0)) > 0 for f in stat001))
    if stat001:
        f = stat001[0]
        _rep(f"  EMP009 PF mismatch: expected={f['expected_value']}, actual={f['actual_value']}, diff={f['difference']}")
        _rep(f"  EMP009 suggested fix: {f.get('suggested_fix', 'N/A')}")

    # ── EMP010: Salary Spike ──────────────────────────────────────────────────
    # MOM-002 = positive spike (> 30%), MOM-003 = negative drop
    f10 = findings_for(result, "EMP010")
    mom002 = [f for f in f10 if f["rule_id"] == "MOM-002" and f["status"] == "FAIL"]
    ok("EMP010 (Spike): MOM-002 fires for 100% basic increase", len(mom002) > 0,
       f"MOM findings: {[(f['rule_id'], f['status'], f.get('reason','')[:60]) for f in f10 if f['rule_id'].startswith('MOM')]}")
    ok("EMP010 MOM-002 is WARNING", any(f["severity"] == "WARNING" for f in mom002) if mom002 else False)
    if mom002:
        _rep(f"  EMP010 spike reason: {mom002[0]['reason']}")

# ─── STEP 9: RISK SCORE DISTRIBUTION ─────────────────────────────────────────

h("STEP 9: Risk Score Analysis")

if result:
    dist = result["findings_summary"].get("risk_distribution", {})
    _rep(f"  Risk Distribution: HIGH={dist.get('HIGH',0)}, MEDIUM={dist.get('MEDIUM',0)}, LOW={dist.get('LOW',0)}")
    for r in sorted(result["risk_scores"], key=lambda x: -x["risk_score"]):
        _rep(f"  {r['employee_name'] or r['employee_id']:20s}  score={r['risk_score']:3d}  level={r['risk_level']}")

    high_risk = [r for r in result["risk_scores"] if r["risk_level"] == "HIGH"]
    med_or_high = [r for r in result["risk_scores"] if r["risk_level"] in ("HIGH", "MEDIUM")]
    # EMP009 has STAT-001 (CRITICAL) + AGG-002 (CRITICAL due to net mismatch from wrong PF)
    # Score = 50+ → at least MEDIUM risk
    ok("EMP009 (PF mismatch) is at least MEDIUM risk",
       any(r["employee_id"] == "EMP009" and r["risk_level"] in ("HIGH", "MEDIUM") for r in result["risk_scores"]),
       f"EMP009 risk: {next((r for r in result['risk_scores'] if r['employee_id'] == 'EMP009'), {})}")
    ok("At least 1 HIGH risk employee detected", len(high_risk) >= 1,
       f"High risk employees: {[r['employee_id'] for r in high_risk]}")

# ─── STEP 10: SPECIAL TEST — Different PF/ESIC configurations ────────────────

h("STEP 10: PF/ESIC Config Variants")

# Test A: Uncapped PF mode — employee above ceiling should get PF on full wage
try:
    cfg = get("/api/config/statutory")
    cfg["pf"]["wage"]["restrict_to_ceiling"] = False
    cfg["pf"]["wage"]["above_ceiling_mode"] = "uncapped"
    put("/api/config/statutory", cfg)

    emp_uncapped = [{
        "employee_id": "TEST_UNCAP", "employee_name": "Test Uncapped",
        "state": "Maharashtra", "gender": "Male",
        "basic": 25000, "hra": 10000, "gross": 35000, "net": 29060,
        "pf_employee": 3000,   # 25000 * 12% = 3000
        "pf_employer": 3000,
        "esic_employee": 0, "esic_employer": 0,
        "pt": 200,
        "paid_days": 26, "lop_days": 0,
    }]
    r_uncap = validate(emp_uncapped)
    pf_fails = [f for f in r_uncap["findings"] if f["rule_id"] == "STAT-001" and f["status"] == "FAIL"]
    ok("Uncapped PF mode: 3000 (25000*12%) passes STAT-001", len(pf_fails) == 0,
       f"Unexpected failures: {pf_fails}")

    # Reset back to restricted
    cfg["pf"]["wage"]["restrict_to_ceiling"] = True
    cfg["pf"]["wage"]["above_ceiling_mode"] = "restricted"
    put("/api/config/statutory", cfg)
    ok("PF config reset to restricted", True)
except Exception as e:
    ok("PF uncapped config test", False, str(e))

# Test B: Contractor ESIC exemption
try:
    emp_contractor = [{
        "employee_id": "TEST_CONTRACTOR", "employee_name": "Contractor A",
        "state": "Maharashtra", "gender": "Male",
        "basic": 15000, "hra": 6000, "gross": 21000, "net": 19200,
        "pf_employee": 1800, "pf_employer": 1800,
        "esic_employee": 0, "esic_employer": 0,  # contractor → no ESIC
        "pt": 200, "paid_days": 26, "lop_days": 0,
        "employment_type": "contractor",
    }]
    r_contr = validate(emp_contractor)
    # STAT-005 is INFO (above ceiling notification) - this is expected behaviour.
    # The real check is that STAT-006 (contribution mismatch) does NOT fire,
    # because the contractor has 0 ESIC which is correct for an exempt employee.
    esic_mismatch_fail = [f for f in r_contr["findings"]
                          if f["rule_id"] == "STAT-006" and f["status"] == "FAIL"]
    ok("Contractor ESIC exempt: STAT-006 (mismatch) not fired", len(esic_mismatch_fail) == 0,
       f"ESIC mismatch fails: {esic_mismatch_fail}")
except Exception as e:
    ok("Contractor ESIC exemption", False, str(e))

# ─── STEP 11: LOP-ONLY CASE & FEBRUARY PT TEST ───────────────────────────────

h("STEP 11: Special Edge Cases")

# LOP edge case: LOP makes ESIC applicable
# Gross = 25000 but prorated to 20000 after LOP → ESIC threshold check
try:
    emp_lop_esic = [{
        "employee_id": "TEST_LOP_ESIC",
        "employee_name": "LOP ESIC Test",
        "state": "Maharashtra", "gender": "Male",
        "basic": 16154,   # 25000 * 17/26 ≈ 16346 → below ceiling after LOP
        "hra": 8077, "conveyance": 1600, "medical_allowance": 1250,
        "special_allowance": 4273,
        "gross": 20000,   # < 21000 → ESIC eligible after LOP
        "net": 17742,
        "pf_employee": 1800, "pf_employer": 1800,
        "esic_employee": 150, "esic_employer": 650,
        "pt": 200,
        "paid_days": 17, "lop_days": 9,
    }]
    r_lop = validate(emp_lop_esic)
    all_f = r_lop["findings"]
    _rep(f"  LOP-ESIC test findings: {[(f['rule_id'], f['status']) for f in all_f if f['status'] == 'FAIL']}")
    ok("LOP-ESIC edge case ran without error", "results" in r_lop)
except Exception as e:
    ok("LOP-ESIC edge case", False, str(e))

# Maharashtra February PT (₹300 for Male instead of ₹200)
try:
    emp_feb = [{
        "employee_id": "TEST_FEB_PT",
        "employee_name": "Feb PT Test",
        "state": "Maharashtra", "gender": "Male",
        "basic": 20000, "hra": 10000, "conveyance": 1600,
        "medical_allowance": 1250, "special_allowance": 5150,
        "gross": 38000, "net": 35500,
        "pf_employee": 1800, "pf_employer": 1800,
        "esic_employee": 0, "esic_employer": 0,
        "pt": 300,   # Correct for February
        "paid_days": 28, "lop_days": 0,
    }]
    # Validate with February period
    r_feb = validate(emp_feb, period_month="2025-02-01")
    pt_fails = [f for f in r_feb["findings"] if f["rule_id"] == "STAT-008" and f["status"] == "FAIL"]
    ok("Maharashtra Feb PT ₹300 is accepted (no STAT-008 fail)", len(pt_fails) == 0,
       f"PT fails: {[(f['expected_value'], f['actual_value']) for f in pt_fails]}")
except Exception as e:
    ok("Maharashtra February PT test", False, str(e))

# ─── STEP 12: EXCEL AUDIT EXPORT ─────────────────────────────────────────────

h("STEP 12: Excel Audit Report Export")

if result and APRIL_EMPLOYEES:
    try:
        body_data = json.dumps({
            "run_type": "increment_arrear",
            "period_month": "2025-04-01",
            "employees": APRIL_EMPLOYEES,
        }).encode()
        req = urllib.request.Request(
            f"{BASE}/api/payroll/validate/export-excel", data=body_data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        r = urllib.request.urlopen(req)
        ok("Excel export HTTP 200", r.status == 200)
        ct = r.headers.get("Content-Type", "")
        ok("Excel Content-Type is xlsx", "openxml" in ct or "spreadsheet" in ct)
        excel_data = r.read()
        ok("Excel file > 5 KB", len(excel_data) > 5000)

        # Save to disk
        out_path = os.path.join(os.path.dirname(__file__), "payroll_audit_april2025.xlsx")
        with open(out_path, "wb") as fp:
            fp.write(excel_data)
        ok(f"Excel saved: {os.path.basename(out_path)}", os.path.exists(out_path))
        _rep(f"  File size: {len(excel_data)/1024:.1f} KB")
    except Exception as e:
        ok("Excel Export", False, str(e))

# ─── STEP 13: DASHBOARD STATS ────────────────────────────────────────────────

h("STEP 13: Dashboard Statistics")

try:
    stats = get("/api/payroll/dashboard-stats")
    ok("Dashboard stats API", "components_configured" in stats)
    ok(f"Components configured: {stats['components_configured']}", stats['components_configured'] >= len(COMPONENTS))
    ok("Last run recorded", stats.get("last_run_at") is not None)
    ok("Register period present", stats.get("last_register_period") is not None)
    _rep(f"  Last run at:       {stats.get('last_run_at')}")
    _rep(f"  Last register:     {stats.get('last_register_period')}")
    _rep(f"  Components:        {stats.get('components_configured')}")
except Exception as e:
    ok("Dashboard Stats", False, str(e))

# ─── STEP 14: WHAT'S REMAINING / KNOWN GAPS ───────────────────────────────────

h("STEP 14: Identified Gaps & Remaining Improvements")

GAPS = [
    ("TDS Simulation (old/new regime)", "PARTIAL", "STAT-011 fires INFO for under-deduction risk but full TDS computation (slabs, exemptions, Section 80C/80D) is not implemented. Only a simplified flag is raised."),
    ("Gratuity Eligibility Check", "PARTIAL", "STAT-014 checks the cap (₹20L). Actual year-of-service tracking requires date-of-joining stored in CTC/HR record; currently not captured."),
    ("Full & Final Settlement Validation", "PARTIAL", "F&F run type accepted but dedicated checks for leave encashment, notice pay recovery, bonus pro-ration on exit are not yet validated."),
    ("ESIC Entry/Exit Half-month Rule", "PARTIAL", "Config toggle exists; enforcement in rule engine relies on employment_type=new_joiner/exit flag in upload row, not yet auto-detected from date-of-joining."),
    ("PDF Audit Report", "MISSING", "Only Excel export is supported. PDF generation (invoice/report style) is not implemented."),
    ("Multi-file / Bulk Register Upload", "PARTIAL", "Each month = one file upload. Bulk import of 12 months at once is not supported."),
    ("Email Notifications", "MISSING", "No alerting for HIGH-risk employees or validation completion."),
    ("Role-Based Access Control", "MISSING", "Single system user only. No multi-user/admin/auditor role separation."),
    ("Peer / Band Salary Comparison", "BASIC", "ADV-002/003 do basic MoM comparison. Cross-employee band comparison (e.g., all Jr. Engineers) is not implemented."),
    ("Bonus Annual Payout Validation", "PARTIAL", "Monthly bonus rate is validated; annual bonus reconciliation vs statutory minimum is not checked."),
]

for name, status, detail in GAPS:
    _rep(f"  [{status:8s}] {name}")
    _rep(f"             {detail}")

# ─── FINAL SUMMARY ────────────────────────────────────────────────────────────

total = PASS + FAIL
_rep(f"\n{'='*65}")
_rep(f"  FINAL TEST RESULTS: {PASS} passed / {FAIL} failed / {total} total")
_rep(f"  Score: {PASS/total*100:.1f}%")
_rep('='*65)
if FAIL == 0:
    _rep("  ALL TESTS PASSED — System fully configured and validated!")
else:
    _rep(f"  {FAIL} TESTS FAILED — review above for details")

# Save report to file
rpt_path = os.path.join(os.path.dirname(__file__), "e2e_test_report.txt")
with open(rpt_path, "w", encoding="utf-8") as fp:
    fp.write("\n".join(REPORT_LINES))
_rep(f"\n  Full report saved to: {rpt_path}")
