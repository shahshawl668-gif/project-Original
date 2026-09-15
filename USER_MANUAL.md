# PayrollCheck — User Manual

**India Payroll Intelligence & Compliance OS**

This guide explains how to use the full product: **Next.js** web app (sidebar navigation) and **FastAPI** backend with **PostgreSQL** or **SQLite** (local dev).

---

## 1. What this product does

PayrollCheck is **not** an HRMS and does not run payroll. It sits beside whatever
system already does — Keka, Darwinbox, ADP, a bureau, or a spreadsheet and a CA —
and answers two questions about the output.

**Is this month right?**

- **Ingests** four inputs: the salary register, the employee master, attendance,
  and the CTC report — each stored with history, so any month can be re-checked
  against the data as it stood then.
- **Validates** PF, ESIC, PT, LWF, income tax, gross/net, LOP proration,
  month-on-month movement, bonus and gratuity, minimum wage, and structural risk.
- **Compares the register against its inputs** — paid before joining, paid after
  exit, paid days disagreeing with attendance, PF deducted with no UAN. These are
  the errors no internal-consistency check can see, because a wrong input
  processed consistently looks perfectly valid.
- **Scores** each employee 0–100 (LOW / MEDIUM / HIGH).

**What is this costing and what are we exposed to?**

- **Cost bridge** — why payroll cost moved month on month, split into joiners,
  leavers, pay changes, attendance and arrears, reconciling exactly to the total.
- **Statutory exposure** — accumulated shortfall carried from the month it arose
  with interest and damages accruing by age, so a year-old PF gap reads at what
  it would actually cost to settle, not at its principal.
- **Sign-off and evidence pack** — who approved the month, what they saw, what
  they accepted and why, and which rules and rates were in force at the time.

### Findings are a record, not a report

A finding keeps its identity across months. An exception explained once stays
explained; a problem in its ninth month says so. Waiving something removes it
from the worklist but **never** from the exposure — an accepted risk is still a
risk, and every decision is written to an audit trail that is never rewritten.

### Who it is for

| | |
|---|---|
| **A payroll bureau or CA practice** | One login, many client companies. Each client is an *entity* with its own registers, statutory configuration and rate tables; analysts can be scoped to a subset of the book. |
| **An enterprise** | Simply an organization with one entity. Nothing to configure, no entity header to send — and no migration needed if a second legal employer appears later. |

---

## 2. Architecture (for operators)


| Layer            | Technology                                          |
| ---------------- | --------------------------------------------------- |
| Frontend         | Next.js (App Router), React, Tailwind               |
| Backend          | FastAPI, Pydantic                                   |
| Database         | PostgreSQL (recommended) or SQLite                  |
| Statutory config | JSON in DB (**Config-Driven Statutory Engine**)     |
| PT / LWF         | Per-entity **SlabRule** rows + optional reference seeds |
| Data scope       | **Organization → Entity**; every row carries `entity_id` |


**API base URL** (default local): `http://localhost:8000/api`

**Entity scope.** Every request acts on one entity. The web app sends
`X-Entity-Id`; API clients may do the same. Omitting it falls back to the
member's stored default, which is what a single-entity company relies on — so an
enterprise never has to think about the header. Roles are `owner`, `manager`,
`analyst` and `viewer`: viewers read, analysts write, and only owners and
managers add entities or sign off a period.

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

- `**pt_states`:** States where you operate and need **Professional Tax** slabs.
- `**lwf_states`:** States where **Labour Welfare Fund** applies.

Per-row **state** comes from the upload column `state` (aliases: `work_state`, `state_pt`, `location_state`). The row’s state must appear in the corresponding list, or the tenant **default** (first list entry) is used.

### 3.3 PT / LWF slabs

**UI:** Rule Engine → **PT / LWF Slabs**

- Import **defaults** per state (catalog from the product).
- Edit slabs: `min_salary`, `max_salary`, `deduction_amount`, `frequency`, `gender`, `applicable_months` (e.g. February PT top-up in Maharashtra), and for LWF `**employer_amount`** where applicable.

### 3.4 Statutory Engine (PF / ESIC — config-driven)

**UI:** Configuration → **Statutory Engine**

This edits `**/api/config/statutory`** (JSON): PF wage rules, rates, ceiling, voluntary PF, ESIC ceiling, rounding, eligibility exemptions (e.g. `contractor`), and **component mapping** for wage calculation.

- **Test expression** (if exposed in UI or via API): safe arithmetic/boolean checks for custom logic.
- After changes, run a small test payroll to confirm PF/ESIC match your payroll software.

### 3.5 Income tax & rule thresholds (FY-versioned)

**UI:** Configuration → **Income tax & thresholds**

Nothing statutory is hardcoded: income-tax slabs, Section 87A rebate,
surcharge brackets, cess, standard deductions, and Chapter VI-A caps are
stored **per financial year** and are fully editable. Known years
(FY 2025-26, FY 2026-27) are seeded as editable defaults; add the next FY
with one click (it copies the selected year), adjust rates when a Budget
changes them, and mark the year your payroll runs against as **default**.

The same page tunes **validation rule thresholds**: structural risk
percentages (STRUCT-001/002), mismatch tolerances (AGG/STAT rules),
month-on-month spike limits (MOM/ADV rules), the TDS-risk heuristic
(STAT-011) and the gratuity exemption cap (STAT-014).

**API:** `GET/PUT /api/config/statutory/income-tax`,
`PUT/DELETE /api/config/statutory/income-tax/years/{fy}`,
`GET/PUT /api/config/statutory/rule-thresholds`, plus `POST …/reset`
endpoints. Tax computation: `POST /api/income-tax/compute` and
`/api/income-tax/compare` accept an optional `financial_year`.

### 3.6 Formulas (optional)

**UI:** Rule Engine → **Formulas**

Create expressions (e.g. HRA = 50% of Basic) for documentation or future rule hooks; use **Test** to verify with sample variables.

### 3.7 CTC history

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
- `**total_days`** / `**month_days**` / `**days_in_month**` / `**working_days**` — **payroll denominator** for your company (e.g. **26** for fixed working-day month).  
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

From the API: `**POST /api/payroll/validate/export-excel`** with the same JSON body as validate.  
Produces **Summary**, **Findings**, **Risk Scores** sheets.

---

## 5. Rule engine overview (what gets checked)

Rules are grouped in layers (data quality → structure → aggregates → statutory → LOP → MoM → advanced). The **MST-\*** and **ATT-\*** families are different in kind: they compare the register against its *inputs* rather than against itself, and they run only for employees the relevant input actually covers — a client who has not uploaded attendance gets silence from them, not false positives. Examples:


| Rule ID    | Theme                                                                                                                |
| ---------- | -------------------------------------------------------------------------------------------------------------------- |
| DATA-*     | Missing ID, negatives, duplicates                                                                                    |
| COMP-*     | Unmapped columns, missing PF wage columns                                                                            |
| STRUCT-*   | Low Basic % of gross (PF avoidance), allowance-heavy                                                                 |
| AGG-*      | Gross vs sum of earnings; net vs gross minus statutory deductions                                                    |
| STAT-001 … | PF / ESIC / PT / LWF mismatches; bonus eligibility (STAT-012/013); gratuity cap (STAT-014); TDS risk hint (STAT-011) |
| LOP-*      | paid_days + lop_days vs denominator; proration vs CTC monthly × paid/total                                           |
| MOM-*      | New joiner, component spike/drop vs prior month, new components, increment arrear vs CTC                             |
| ADV-*      | Salary spikes/drops vs prior gross                                                                                   |
| ID-*       | PAN (206AA), Aadhaar (Verhoeff), UAN, ESI number, IFSC formats; working age; pay before DOJ / after DOL              |
| PF-004/008 | EPS split vs cap, post-Sep-2014 joiner EPS=0, EPS stop at 58, international-worker ceiling                           |
| ESI-005/006| Disability coverage ceiling (₹25,000), daily-wage employee-share exemption (₹176)                                    |
| PT-002/003 | Article 276 annual cap (₹2,500), PT deducted in a no-PT state                                                        |
| BON-*      | Payment of Bonus Act eligibility (₹21,000) and 8.33–20% band on min(Basic+DA, ₹7,000)                                |
| GRAT-002/3 | Gratuity service gate (5y, waived on death/disablement) and 15/26 formula check                                      |
| TDS-001/002| No-PAN 20% minimum (Sec 206AA); monthly TDS vs annualised projection for the declared regime                         |
| DATA-005…9 | Negative deductions; duplicate PAN / UAN / Aadhaar / bank account across employees                                   |

Optional identity/master-data columns the register may carry: `pan`, `aadhaar`,
`uan`, `esi_number`, `bank_account`, `ifsc`, `dob`, `doj`, `dol`, `tax_regime`,
`gender`, `disability`, `international_worker`, `adolescent_permit`,
`death_or_disablement`, `eps`, `bonus`, `gratuity`, `tds`. Every threshold these
rules use is editable under **Configuration → Income tax & thresholds**.


**Increment / arrear run:** Use `**increment_arrear`** when pay structure legitimately changes with arrears so **MOM-002** (spike) is not raised incorrectly.

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

## 7A. Employee master and attendance

Both upload in two steps: **upload** previews how your column headers were read,
**commit** stores it. The preview exists because a header that went unrecognised
silently disables the checks that depend on it — an unmatched "Date of Leaving"
column means nothing ever gets flagged as paid-after-exit.

Headers are matched against known spellings, so `Emp Code`, `Employee No` and
`Staff ID` all resolve to the employee id, and `DOJ`, `Joining Date` and
`Date of Join` all resolve to the joining date. Columns this schema does not
know are kept rather than dropped. Dates are read **day-first**: `03/04/2025` is
3 April, because Indian exports are dd/mm/yyyy and reading it the other way is a
silent eleven-month error.

**Employee master** (`POST /api/workforce/master/commit`, with
`meta={"effective_from": "YYYY-MM-01"}`) is effective-dated. Upload it again
whenever it changes; re-validating March reads March's version, so a June exit
does not make April's register report everyone as paid-after-exit.

| Worth having | Why |
|---|---|
| `date_of_joining` | Paid-before-joining, and gratuity service years |
| `date_of_exit` | Paid-after-exit — the most expensive thing here |
| `work_state` | PT and LWF follow where the person works, not where the company is registered |
| `skill_category` | Selects the minimum wage rate |
| `uan`, `esic_ip_number` | Filing blockers, checked where a deduction implies one |

**Attendance** (`POST /api/workforce/attendance/commit`, with
`meta={"period_month": "YYYY-MM-01"}`) takes calendar / present / paid / LOP /
OT days. Give it any two of calendar, paid and LOP and the third is derived — but
if you state all three and they disagree, that disagreement is reported rather
than quietly corrected.

Re-committing the same period or effective date **replaces** it, so a corrected
file is simply sent again.

---

## 7B. Findings worklist

`GET /api/findings` lists what is outstanding, ranked by severity, then by how
many months it has recurred, then by money. A recurring CRITICAL outranks a
larger one-off: the first is a process failure, the second is a typo.

Each finding is one *fingerprint* — the same employee, rule and component — held
steady across months and across changes in amount, so a PF shortfall that varies
in size is recognised as one ongoing problem rather than a fresh one each month.

`POST /api/findings/{fingerprint}/decision` records a decision:

- **acknowledged** — seen, being chased;
- **waived** — accepted. Requires a stated reason, and takes an optional expiry
  so that "accepted once" does not become "invisible forever" across a change of
  staff or of law;
- **open** — put it back on the list.

Findings that stop appearing resolve themselves; ones that come back are
reopened. Every transition is appended to a history that is never rewritten, and
`GET /api/findings/summary` reports waived exposure **beside** open exposure
rather than netting it away.

---

## 7C. Business intelligence

| Endpoint | Answers |
|---|---|
| `GET /api/bi/cost-bridge?period=YYYY-MM-01` | Why cost moved since last month |
| `GET /api/bi/trend?months=12` | Cost, headcount and cost per head over time |
| `GET /api/bi/exposure` | What the accumulated shortfall would cost to settle |
| `GET/PUT /api/bi/exposure/config` | Interest and damages rates |

**The bridge** splits the change into joiners, leavers, pay changes, attendance
and arrears. For someone present in both months the attribution order is fixed:
arrears first, so back-pay cannot look like a rise; then attendance, valued at
last month's daily rate, so a short month does not read as a pay cut; then the
residual, which is the real pay change. The bars sum to the net change exactly —
`unexplained` is rounding, and it is shown rather than hidden so you can see the
bridge closes.

**Exposure** ages each open shortfall from the month it arose and applies the
interest and damages its age attracts. The rates are configurable and carry no
legal force of their own; the defaults follow the rates in common use, and if
your advisers read them differently, edit them rather than waiting for a
release. Waived findings stay in the total and are disclosed on their own line.

---

## 7D. Minimum wage

Rates vary by state, by zone, by scheduled employment and by skill, and the VDA
half is revised twice a year — so no shipped dataset stays correct. **You
maintain the rates**, per entity, via `POST /api/minimum-wage/rates/import`
(re-importing a corrected sheet updates rather than duplicates) or the rates
screen. Record a `source_reference` on each: without one a rate is an assertion
rather than evidence.

`GET /api/minimum-wage/coverage` names the (state, skill) pairs in your
workforce that have no rate on file — worth checking before a run, since each
gap is an employee the tool cannot vouch for.

`POST /api/minimum-wage/check?period=YYYY-MM-01` runs a stored register against
the table. An employee with no applicable rate, or with no work state or skill on
the master, produces an **MW-003 "cannot verify"** finding. That is deliberate:
"no rate configured" and "paid correctly" must never look the same.

Which components count towards the floor is contested, so pick a `basis`:
`basic_da`, `wages_excl_hra` (default) or `gross`. Every finding states which
basis produced it. The floor is prorated by paid days.

---

## 7E. Sign-off and the evidence pack

1. `POST /api/signoff/submit` — prepare the period (any analyst).
2. `POST /api/signoff/sign` — approve it. **Owner or manager only**, and
   deliberately separate from preparation: whoever ran the payroll should not be
   the only person who ever looked at it.
3. `GET /api/signoff/{period}/evidence-pack` — the workbook.

Signing freezes a snapshot: counts, exposure, every outstanding finding, every
accepted one with its reason, and the statutory config, thresholds and minimum
wage rates in force. That last part matters — a finding is only defensible
alongside the rule and the rate that produced it. The snapshot is never
recomputed, so findings raised later do not rewrite what was approved, and a
digest lets a later reader confirm the record is the one that was signed.

Reopening is allowed, because corrections happen, but it is an event rather than
an erasure: the superseded snapshot and the stated reason are both kept.

The evidence pack is built from the signed snapshot where one exists and from
live data otherwise — and the cover sheet says which, so a draft can never be
mistaken for an approved record.

---

## 8. API quick reference


| Method   | Path                                                    | Purpose                                                   |
| -------- | ------------------------------------------------------- | --------------------------------------------------------- |
| GET/POST | `/api/components`                                       | List / create salary components                           |
| GET/PUT  | `/api/settings/statutory`                               | Legacy statutory settings + **pt_states**, **lwf_states** |
| GET/PUT  | `/api/config/statutory`                                 | Config-driven PF/ESIC/mapping                             |
| POST     | `/api/ctc/upload`, `/api/ctc/commit`                    | Parse / store CTC                                         |
| POST     | `/api/payroll/upload`                                   | Parse payroll; may persist register                       |
| POST     | `/api/payroll/validate`                                 | Run full validation                                       |
| POST     | `/api/payroll/validate/export-excel`                    | Excel audit                                               |
| GET      | `/api/payroll/registers`, `/api/payroll/registers/{id}` | History                                                   |
| GET/POST | `/api/rule-engine/slabs`, import-defaults               | PT/LWF                                                    |
| POST     | `/api/rule-engine/formula`                              | Custom formulas                                           |
| GET/PUT  | `/api/config/statutory/income-tax`                      | FY-versioned tax slabs/rebate/surcharge/cess              |
| PUT/DEL  | `/api/config/statutory/income-tax/years/{fy}`           | Add / remove one financial year                           |
| GET/PUT  | `/api/config/statutory/rule-thresholds`                 | Tunable rule-engine thresholds                            |
| POST     | `/api/income-tax/compute`, `/api/income-tax/compare`    | Old vs new regime projection (per FY)                     |
| GET      | `/api/org/context`                                      | Organization, role, entities — what the switcher reads    |
| GET/POST | `/api/org/entities`                                     | List / add entities (adding: owner or manager)            |
| POST     | `/api/org/entities/{id}/select`                         | Remember this entity as your default                      |
| POST     | `/api/workforce/master/upload`, `/master/commit`        | Employee master: preview headers, then store              |
| POST     | `/api/workforce/attendance/upload`, `/attendance/commit`| Attendance: preview headers, then store                   |
| GET      | `/api/findings`, `/api/findings/summary`                | Worklist and exposure by lifecycle state                  |
| POST     | `/api/findings/{fingerprint}/decision`                  | Acknowledge / waive / reopen                              |
| GET      | `/api/bi/cost-bridge`, `/api/bi/trend`, `/api/bi/exposure` | Cost movement and accumulated exposure                 |
| GET/POST | `/api/minimum-wage/rates`, `/rates/import`, `/coverage` | Rate table and gaps in it                                 |
| POST     | `/api/signoff/submit`, `/api/signoff/sign`              | Prepare and approve a period                              |
| GET      | `/api/signoff/{period}/evidence-pack`                   | Evidence workbook                                         |


Health: `**GET /api/health`**

---

## 9. Troubleshooting


| Symptom                            | Likely cause                                 | What to do                                                                     |
| ---------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------ |
| PT always zero                     | `pt_states` empty or row `state` not in list | Set **PT states** in **Settings → Statutory** (API: `/api/settings/statutory`) |
| LWF always zero                    | Same for `lwf_states`                        | Configure **LWF states** and import slabs                                      |
| Net pay mismatch (AGG-002)         | PT/LWF not computed, or wrong PF/ESIC        | Fix settings; align register columns with engine                               |
| Many LOP-002 warnings              | Calendar days vs 26-day payroll              | Add `**total_days: 26`** (or your standard) on each row                        |
| “PF component missing” for arrears | Old data / naming                            | Name arrear columns with **“arrear”**; refresh components                      |
| MoM noise                          | Prior month register missing                 | Upload previous month’s register for the same period chain                     |
| ESIC mismatch on contractors       | Exemption not applied                        | Set `employment_type` / check **exempt_employment_types** in statutory config  |


---

## 10. Known limitations (roadmap)

- **Minimum wage rates ship empty.** The engine and the checks are built, but the
  rate table is yours to load and maintain — see §7D. Coverage gaps are reported
  rather than passed over, but they are still gaps.
- **No ECR / challan reconciliation.** Validation compares computed against the
  register; it does not yet compare either against what was filed or what was
  paid. That three-way match is the most direct predictor of a notice and is the
  obvious next thing to build.
- **TDS:** heuristic risk flags plus regime projection — not a full Form 16
  computation.
- **Exposure interest and damages rates** are defaults in common use, not legal
  advice. Review them against your advisers' reading (§7C).
- **No payroll recomputation from first principles.** The tool checks and
  explains; it does not independently recompute gross from CTC and attendance.
- **F&F:** no dedicated leave encashment / notice pay modules.
- **PDF** audit report not built — use the **Excel** evidence pack.
- **Invitations** are not built: members are added to an organization directly
  in the database rather than by email invite.

---

## 11. Support files in the repo

- `**backend/e2e_full_test.py`** — End-to-end scenario script (components, slabs, CTC, March + April registers, validation).
- `**backend/payroll_audit_april2025.xlsx**` — Example export (after running tests).
- `**backend/e2e_test_report.txt**` — Text report from the e2e script.

---

*Document version: aligned with PayrollCheck codebase (config-driven statutory, PT/LWF multi-state, LOP `total_days` support).*