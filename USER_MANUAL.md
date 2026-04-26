# PayrollCheck — User Manual  
**India Payroll Intelligence & Compliance OS**

This guide explains how to use the full product: **Next.js** web app (sidebar navigation) and **FastAPI** backend with **PostgreSQL** or **SQLite** (local dev).

---

## 1. What this product does

- **Ingests** salary registers and CTC reports (CSV / Excel) with column auto-mapping.
- **Stores** historical salary registers (one per month) and CTC revisions for comparison and increment-arrear checks.
- **Validates** PF, ESIC, PT, LWF, gross/net, LOP proration, month-on-month changes, bonus/gratuity awareness, and structural risk (PF avoidance, allowance-heavy mixes).
- **Scores** each employee with a **0–100 risk score** (LOW / MEDIUM / HIGH).
- **Exports** an Excel audit workbook (summary, findings, risk scores).

There is **no login** in the current build: a single **system user** owns all data (multi-tenant isolation is still enforced in the API by that user id).

---

## 2. Architecture (for operators)

| Layer | Technology |
|--------|------------|
| Frontend | Next.js (App Router), React, Tailwind |
| Backend | FastAPI, Pydantic |
| Database | PostgreSQL (recommended) or SQLite |
| Statutory config | JSON in DB (**Config-Driven Statutory Engine**) |
| PT / LWF | Tenant **SlabRule** rows + optional reference seeds |

**API base URL** (default local): `http://localhost:8000/api`

---

## 3. First-time setup workflow

Do these **in order** before your first payroll validation.

### 3.1 Salary components

**UI:** Configuration → **Salary Components**

Define every earning column that appears in registers and CTC files. For each component set:

- **PF applicable** — counts toward PF wage (typically Basic / DA).
- **ESIC applicable** — counts toward ESIC wage (often broader than PF).
- **PT / LWF applicable** — included in PT and LWF wage bases where your policy requires.
- **Included in wages** — included in computed gross for aggregation checks.
- **Taxable** — used in simplified TDS-risk heuristics.

**Tip:** Arrear columns (e.g. “Basic Arrear”) should be named with **“Arrear”** in the name so optional-arrear rules behave correctly.

### 3.2 PT and LWF state lists (required for correct PT/LWF)

**API:** `PUT /api/settings/statutory`  
**Fields:** `pt_states`, `lwf_states` (arrays of state names, e.g. `"Maharashtra"`, `"Karnataka"`).

If these lists are **empty**, the engine may **not** compute PT/LWF for rows, which leads to **net pay mismatches** (register has PT/LWF but system expects zero).

- **`pt_states`:** States where you operate and need **Professional Tax** slabs.
- **`lwf_states`:** States where **Labour Welfare Fund** applies.

Per-row **state** comes from the upload column `state` (aliases: `work_state`, `state_pt`, `location_state`). The row’s state must appear in the corresponding list, or the tenant **default** (first list entry) is used.

### 3.3 PT / LWF slabs

**UI:** Rule Engine → **PT / LWF Slabs**

- Import **defaults** per state (catalog from the product).
- Edit slabs: `min_salary`, `max_salary`, `deduction_amount`, `frequency`, `gender`, `applicable_months` (e.g. February PT top-up in Maharashtra), and for LWF **`employer_amount`** where applicable.

### 3.4 Statutory Engine (PF / ESIC — config-driven)

**UI:** Configuration → **Statutory Engine**

This edits **`/api/config/statutory`** (JSON): PF wage rules, rates, ceiling, voluntary PF, ESIC ceiling, rounding, eligibility exemptions (e.g. `contractor`), and **component mapping** for wage calculation.

- **Test expression** (if exposed in UI or via API): safe arithmetic/boolean checks for custom logic.
- After changes, run a small test payroll to confirm PF/ESIC match your payroll software.

### 3.5 Formulas (optional)

**UI:** Rule Engine → **Formulas**

Create expressions (e.g. HRA = 50% of Basic) for documentation or future rule hooks; use **Test** to verify with sample variables.

### 3.6 CTC history

**UI:** CTC → **Upload CTC** then **CTC History**

- File must include **employee id** and **effective_from** (and annual components matching your component names).
- **Commit** stores records for **increment / arrear** expectations vs register.

---

## 4. Payroll upload and validation

### 4.1 Upload flow

**UI:** Payroll → **Upload & Validate**

1. Choose **run type**: `regular`, `arrear`, `increment_arrear`, etc.
2. Set **period month** (and effective range if required for arrear runs).
3. Upload CSV/XLSX.

**Strict header check:** If enabled, unknown columns may be rejected; you can relax this for exploratory files (see API `strict_header_check`).

### 4.2 Required / recommended columns

**Identifiers**

- `employee_id` / `emp_id` / `employee_code`
- `employee_name` / `name`

**Earnings**

- One column per configured component (e.g. `basic`, `hra`, …).
- Arrears: e.g. `basic_arrear` or mapped arrear fields.

**Statutory (for reconciliation)**

- `pf_employee`, `pf_employer` (or aliases)
- `esic_employee`, `esic_employer`
- `pt` / `pt_amount`
- `lwf_employee`, `lwf_employer`

**Attendance / LOP**

- `paid_days`, `lop_days` (or `lop`)
- **`total_days`** / **`month_days`** / **`days_in_month`** / **`working_days`** — **payroll denominator** for your company (e.g. **26** for fixed working-day month).  
  If omitted, the system uses **calendar days** for that month, which can trigger **LOP proration (LOP-002)** findings when your sheet uses full monthly amounts with `paid_days = 26`.

**Location**

- `state` (recommended) — must align with **pt_states** / **lwf_states** for correct PT/LWF.

**Other**

- `gender` — for gender-specific PT/LWF slabs.
- `employment_type` — e.g. `contractor` for ESIC exemption per config.
- `gross`, `net` — for **AGG-001** / **AGG-002** checks.

### 4.3 Storing registers

When upload **parses successfully** and components are not missing, the backend **persists** a **Salary Register** for the **period month** (first day of month).  
**Payroll → Register History** lists past months; use this for **month-on-month (MoM)** rules.

### 4.4 Validation results

**UI:** Payroll → **Results**

- Findings show **rule id**, **severity** (CRITICAL / WARNING / INFO), **status** (FAIL / PASS), **expected vs actual**, **suggested fix**, **financial impact**.
- **INFO** with status **FAIL** is used for *informational* flags (e.g. “ESIC ineligible above ₹21,000”) — read the **severity**, not only the word FAIL.

### 4.5 Risk score

Each employee gets a **0–100** score:

- Weights: CRITICAL FAIL 25, WARNING FAIL 10, INFO FAIL 2 (capped at 100).
- Large **financial impact** may add a small boost.
- **HIGH** if score ≥ 60 or duplicate-employee rule forces it.

### 4.6 Excel export

From the API: **`POST /api/payroll/validate/export-excel`** with the same JSON body as validate.  
Produces **Summary**, **Findings**, **Risk Scores** sheets.

---

## 5. Rule engine overview (what gets checked)

Rules are grouped in layers (data quality → structure → aggregates → statutory → LOP → MoM → advanced). Examples:

| Rule ID | Theme |
|--------|--------|
| DATA-* | Missing ID, negatives, duplicates |
| COMP-* | Unmapped columns, missing PF wage columns |
| STRUCT-* | Low Basic % of gross (PF avoidance), allowance-heavy |
| AGG-* | Gross vs sum of earnings; net vs gross minus statutory deductions |
| STAT-001 … | PF / ESIC / PT / LWF mismatches; bonus eligibility (STAT-012/013); gratuity cap (STAT-014); TDS risk hint (STAT-011) |
| LOP-* | paid_days + lop_days vs denominator; proration vs CTC monthly × paid/total |
| MOM-* | New joiner, component spike/drop vs prior month, new components, increment arrear vs CTC |
| ADV-* | Salary spikes/drops vs prior gross |

**Increment / arrear run:** Use **`increment_arrear`** when pay structure legitimately changes with arrears so **MOM-002** (spike) is not raised incorrectly.

For the **full rule list and field meanings**, refer to in-app help or `backend/app/services/rule_engine_v2.py` (docstring and `build_findings`).

---

## 6. Bonus checks (Payment of Bonus Act — simplified)

- **Eligibility** uses gross / ESIC wage threshold (e.g. **≤ ₹21,000** for statutory minimum bonus context in the engine).
- **Minimum / maximum rate** is checked against **PF wage (Basic/DA)**, with a **₹7,000/month** wage cap for the **minimum** percentage per common statutory interpretation in the product.

Always confirm with your CA for your exact scheme (interim bonus, ex-gratia, state amendments).

---

## 7. Dashboard

**UI:** **Dashboard**

Shows setup progress, recent activity, and charts driven by last runs/registers. Upload and validate payroll to populate meaningful stats.

---

## 8. API quick reference

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/api/components` | List / create salary components |
| GET/PUT | `/api/settings/statutory` | Legacy statutory settings + **pt_states**, **lwf_states** |
| GET/PUT | `/api/config/statutory` | Config-driven PF/ESIC/mapping |
| POST | `/api/ctc/upload`, `/api/ctc/commit` | Parse / store CTC |
| POST | `/api/payroll/upload` | Parse payroll; may persist register |
| POST | `/api/payroll/validate` | Run full validation |
| POST | `/api/payroll/validate/export-excel` | Excel audit |
| GET | `/api/payroll/registers`, `/api/payroll/registers/{id}` | History |
| GET/POST | `/api/rule-engine/slabs`, import-defaults | PT/LWF |
| POST | `/api/rule-engine/formula` | Custom formulas |

Health: **`GET /api/health`**

---

## 9. Troubleshooting

| Symptom | Likely cause | What to do |
|--------|----------------|------------|
| PT always zero | `pt_states` empty or row `state` not in list | Set **PT states** in **Settings → Statutory** (API: `/api/settings/statutory`) |
| LWF always zero | Same for `lwf_states` | Configure **LWF states** and import slabs |
| Net pay mismatch (AGG-002) | PT/LWF not computed, or wrong PF/ESIC | Fix settings; align register columns with engine |
| Many LOP-002 warnings | Calendar days vs 26-day payroll | Add **`total_days: 26`** (or your standard) on each row |
| “PF component missing” for arrears | Old data / naming | Name arrear columns with **“arrear”**; refresh components |
| MoM noise | Prior month register missing | Upload previous month’s register for the same period chain |
| ESIC mismatch on contractors | Exemption not applied | Set `employment_type` / check **exempt_employment_types** in statutory config |

---

## 10. Known limitations (roadmap)

- **TDS:** Heuristic only — not full old/new regime computation.
- **Gratuity:** Cap check present; full service-years validation needs DOJ in HR data.
- **F&F:** No dedicated leave encashment / notice pay modules yet.
- **PDF** audit report not built — use **Excel export**.
- **Multi-user RBAC** not enabled in this build.

---

## 11. Support files in the repo

- **`backend/e2e_full_test.py`** — End-to-end scenario script (components, slabs, CTC, March + April registers, validation).
- **`backend/payroll_audit_april2025.xlsx`** — Example export (after running tests).
- **`backend/e2e_test_report.txt`** — Text report from the e2e script.

---

*Document version: aligned with PayrollCheck codebase (config-driven statutory, PT/LWF multi-state, LOP `total_days` support).*
