# Business Requirements Document — PayrollCheck

**India Payroll Validation, Cost Intelligence & Reconciliation**

| | |
|---|---|
| Document owner | Product |
| Status | Baseline for first production release |
| Applies to | `backend/` FastAPI service, `frontend/` Next.js app |
| Last verified against code | 730 automated tests passing on SQLite and PostgreSQL 16 |

---

## 1. Purpose

Indian payroll is run by systems that mark their own homework. A payroll engine
computes PF, files the ECR, produces the bank file and posts the journal
voucher — and then reports that all four agree. They always agree, because one
system produced all four.

PayrollCheck is the independent second opinion. It **never runs payroll**, which
is precisely what qualifies it to check one. It reads the outputs of whatever
system a company already uses — Keka, Darwinbox, ADP, greytHR, a bureau, or a
spreadsheet and a CA — and answers three questions the producing system cannot
answer about itself:

1. **Is this month right?** — statutory arithmetic, inputs, structure.
2. **What did it cost, and to whom?** — cost intelligence for management.
3. **Did it reach the bank and the ledger?** — disbursement and posting.

### 1.1 Business problem

| Problem | Cost of leaving it |
|---|---|
| PF/ESI/PT/TDS computed on the wrong wage base | Interest under s.7Q and damages under s.14B of the EPF Act, accruing monthly |
| Attendance not reflected in pay | Silent overpayment; no internal check can see it |
| Payments to accounts that are not on the employee master | Direct fraud loss, undetectable after the fact |
| Journal voucher that does not equal payroll cost | Audit qualification; management accounts diverge from reality |
| Every correction argued from memory | No defensible record at audit or in a dispute |

### 1.2 Success criteria

| # | Criterion | How measured |
|---|---|---|
| S1 | Finds real defects in a client's live register on the first run | Findings accepted as valid by the client's payroll lead |
| S2 | The ledger and the management dashboard never disagree | Asserted on every build (§6.1) |
| S3 | Never reports a clean month it did not verify | Absence-of-evidence states asserted on every build |
| S4 | A month's position is reconstructable a year later | Evidence pack + append-only audit trail |
| S5 | A new client is productive within one working day | Configuration, not code changes |

---

## 2. Scope

### 2.1 In scope

* Ingestion of four inputs with full history: **employee master**, **CTC master**,
  **attendance register**, **salary register**.
* **90 validation rules** across 19 families (§4.2).
* Cost intelligence over a **15-measure taxonomy** and **9 reporting dimensions**.
* Bank file and journal voucher **reconciliation** with **26 exception kinds**.
* Budget upload, approval, variance and forecast.
* Gender pay gap analysis, behind per-entity authorisation.
* **11 Excel reports**, period sign-off and evidence pack.
* Multi-entity tenancy for bureaux and multi-employer groups.

### 2.2 Explicitly out of scope

These are **non-goals**, not backlog items. Several are non-goals precisely
because doing them would destroy the product's independence.

| Out of scope | Why |
|---|---|
| Running payroll — computing and issuing pay | A system that produced the numbers cannot independently check them |
| Filing returns (ECR, Form 24Q, ESI) with the authorities | The product reports *readiness*; it never claims anything was filed |
| HRMS: leave, recruitment, appraisal, onboarding | Different product, different buyer |
| Statutory advice | The product reports arithmetic and discrepancy; a qualified adviser decides |
| Disbursing funds or holding client money | No payment rails, by design |

### 2.3 Assumptions

| # | Assumption | If it fails |
|---|---|---|
| A1 | The client can export a salary register as CSV or XLSX | No ingestion; blocks everything |
| A2 | Registers carry a stable employee code | Line-level matching degrades to totals only |
| A3 | Statutory rates are **verified by the client's payroll expert** before production use | Seeded defaults are a starting point and carry no legal force |
| A4 | The client's own bank file is available for reconciliation | Module 4 reports the month unreconciled |
| A5 | Attendance is available at employee-month granularity | Attendance rules stay silent rather than guess |

---

## 3. Users and access

### 3.1 Segments

| Segment | Shape | Primary value |
|---|---|---|
| Payroll bureau / CA practice | One login, many client entities | Catch client errors before the client does |
| Mid-market enterprise (200–5,000) | One organisation, one or few entities | Independent check on an outsourced or in-house run |
| Group with multiple legal employers | One organisation, several entities | Per-entity statutory config, consolidated cost view |

### 3.2 Roles

Access is scoped **Organization → Entity**. Every stored row carries an
`entity_id`; every request acts on exactly one entity, named by an
`X-Entity-Id` header or falling back to the member's default.

| Role | Read | Upload / edit config | Approve, sign off, delete | Employee-level pay | Gender pay gap |
|---|---|---|---|---|---|
| **owner** | ✓ | ✓ | ✓ | ✓ | ✓ (if entity enabled) |
| **manager** | ✓ | ✓ | ✓ | ✓ | ✓ (if entity enabled) |
| **analyst** | ✓ | ✓ | — | ✓ | — |
| **viewer** | ✓ | — | — | masked | — |

**R1 — Separation of preparation and approval.** The role that uploads a
register is not automatically the role that signs the period off. Approving a
budget, approving the JV mapping that posts to the ledger, signing a period and
closing a reconciliation are restricted to owner and manager.

**R2 — Masking by default below analyst.** A business-unit head reading their
own cost must not thereby learn every salary in their team. Identity is masked
to a stable pseudonym (`EMP-3F9A2C`) derived by HMAC, not a reversible hash. Any
caller may request masking for a session; nobody can request their way *out* of
it, because that decision belongs to their role.

**R3 — Pay equity is doubly gated.** The analysis runs only where (a) the entity
has switched it on, recorded with who did so and when, and (b) the caller is an
owner or manager. India mandates no gender pay reporting; running it is the
employer's decision, not the product's — and on a bureau's login, one client
authorising it must not enable it across the book.

---

## 4. Functional requirements

### 4.1 Module 1 — Attendance validation

| # | Requirement |
|---|---|
| F1.1 | Accept an attendance file at employee-month granularity; recognise common column spellings without configuration |
| F1.2 | Validate the file **against itself before storing it**, through an endpoint that stores nothing |
| F1.3 | Report days that do not sum to the month, paid days contradicting loss of pay, a wrong month length, impossible values, and duplicate rows |
| F1.4 | Check pay against attendance: loss of pay never deducted, pay with no paid days, overtime worked and not paid, overtime below the statutory rate |
| F1.5 | Report an employee on the attendance register and on no payslip |
| F1.6 | Never fabricate a full-month wage. Where no agreed CTC and no clean prior month exist, report that the check could not be performed |
| F1.7 | Daily-rate basis is configurable: calendar days, fixed 26, or fixed 30. The finding names the basis it used |

**Rationale for F1.2.** Once paid days are derived from loss of pay, the two can
never disagree — so the same check run after commit would pass every file,
including ones that stated both figures and contradicted themselves.

**Rationale for F1.6.** A fabricated overpayment sent to a client is worse than
an unanswered question.

### 4.2 Module 2 — Payroll validation

90 rules in 19 families. Counts are of distinct rule identifiers in the engine.

| Family | # | Covers |
|---|---|---|
| `ATT` | 15 | Attendance and pay-against-attendance (§4.1) |
| `STAT` | 12 | PF, ESI, PT, LWF, TDS against computed expectation |
| `DATA` | 9 | Structural problems in the uploaded file |
| `ID` | 8 | PAN, Aadhaar, UAN, ESIC IP validity |
| `MOM` | 6 | Month-on-month movement, component spikes and drops |
| `MST` | 5 | Register against employee master — paid before joining, paid after exit |
| `GRAT` | 4 | Gratuity eligibility and computation |
| `ARR` | 4 | Arrears: window, months, expectation against CTC |
| `AGG` | 4 | Gross and net against components |
| `PF` | 3 | EPS split, restriction basis, ceiling |
| `LOP` | 3 | Loss-of-pay proration |
| `ADV` | 3 | Salary spike and drop ratios |
| `TDS` | 2 | Section 206AA (no PAN), s.192 projection risk |
| `STRUCT` | 2 | Allowance-heavy structure, PF-wage suppression |
| `PT` | 2 | Article 276 cap, state applicability |
| `MW` | 2 | Minimum wage by state and skill category |
| `ESI` | 2 | Wage ceiling, eligibility |
| `COMP` | 2 | Component configuration against file columns |
| `BON` | 2 | Statutory bonus eligibility and quantum |

| # | Requirement |
|---|---|
| F2.1 | Every statutory rate, slab and threshold is **configurable and effective-dated**. Nothing statutory is hardcoded |
| F2.2 | A finding keeps its identity across months. Explained once, it stays explained; in its ninth month it says so |
| F2.3 | Waiving removes a finding from the worklist and **never** from the exposure. An accepted risk is still a risk and is reported separately |
| F2.4 | Every finding is classified as **missing** / **mismatch** / **issue** — three categories mapping to three different actions and three different people |
| F2.5 | A register stating `0` is making a claim; a register with no such column is making none. The two must produce different findings |
| F2.6 | Each employee-month carries a 0–100 risk score with a visible breakdown |

**Rationale for F2.5.** This distinction was a live defect twice. `0` read as
absent downgraded "PF was not deducted" from critical to informational, and
separately disabled the loss-of-pay checks for every employee whose register
honestly said zero.

### 4.3 Module 3 — Cost intelligence

| # | Requirement |
|---|---|
| F3.1 | Cost is assembled as **earnings + employer contributions = CTC**. Deductions sit *inside* gross and are never added on top |
| F3.2 | 15 measures: 5 earnings, 5 employer contributions, 5 employee deductions, plus 4 roll-ups and net |
| F3.3 | Analysis by 9 dimensions, **snapshotted onto the register row at upload** so a reorganisation cannot rewrite last year's cost by department |
| F3.4 | The register's own statutory figure wins; the engine computes only to fill a gap. Every response states how much it read versus computed |
| F3.5 | Gratuity is always computed at 15/26/12 of Basic & DA, because no register carries it |
| F3.6 | Any dimensional split must sum back to the entity total; unassigned values get a visible bucket |
| F3.7 | Budget is versioned by approval and never overwritten. A forecast is never presented as an actual |
| F3.8 | Filing readiness reports what is *due* and *ready*. No status may ever read as "filed" |

### 4.4 Module 4 — Bank & JV reconciliation

| # | Requirement |
|---|---|
| F4.1 | Bank file layout is **data, not code** — a per-entity profile describing delimiters, column positions, amount units, sign convention, header and trailer rows |
| F4.2 | The parser never guesses. A missing required mapping is an error naming the field; an unreadable cell is reported, not defaulted to zero |
| F4.3 | A profile can be tested against a real file, storing nothing |
| F4.4 | Matching is on **employee code alone** — never name, never amount |
| F4.5 | JV mapping is a per-entity template of ordered rules, each naming **measures from the cost taxonomy**, an account and a side |
| F4.6 | Options must cover real practice: accrual or cash basis; one voucher or one per cost centre; summary, component or employee detail; signed or two-column amounts; voucher date rule; rounding policy; net from stated or computed |
| F4.7 | Export in the import shape of common ledgers, labelled as a starting point rather than a specification |
| F4.8 | A JV template is **approved** before it is the mapping the entity posts with; editing an approved template withdraws its approval |
| F4.9 | Reconciliation results are **stored**, because a reconciliation is only a control if it leaves a record. Closing a run records acceptance; it never erases exceptions |
| F4.10 | 26 exception kinds, each carrying what it means and what to do |

**F4.11 — The account check.** An account in the bank file that is not the
account on the employee master, *as the master stood at that period*, is
reported at high severity. This is the single highest-value check in the module
and the only one that can detect account substitution.

### 4.5 Cross-cutting

| # | Requirement |
|---|---|
| F5.1 | Append-only audit trail of every upload, configuration change, approval and sign-off, with actor and timestamp |
| F5.2 | Period sign-off with an evidence pack: what was checked, found, accepted, by whom, and which rules and rates were in force |
| F5.3 | Every report carries a provenance sheet naming its inputs, filters, masking state, generator and generation time |
| F5.4 | Absence of evidence is reported as loudly as error — a month with no bank file is *unreconciled*, not clean |

---

## 5. Non-functional requirements

### 5.1 Security and privacy

This product processes **salary, PAN, Aadhaar, UAN and bank account numbers** —
personal and financial data under the Digital Personal Data Protection Act 2023.

| # | Requirement | Status |
|---|---|---|
| N1.1 | Passwords stored only as a one-way hash | Implemented |
| N1.2 | JWT access and refresh tokens; anonymous API access forced off in production | Implemented |
| N1.3 | No credential, key or employee datum in source control | Enforced; `bandit` on every build |
| N1.4 | Identity masked by default below analyst role | Implemented |
| N1.5 | Every query scoped by `entity_id`; cross-entity access returns *not found* rather than *forbidden*, so the API cannot be used to probe for entity ids | Implemented |
| N1.6 | Expression evaluation sandboxed against denial of service and escape | Implemented; 72 dedicated tests |
| N1.7 | TLS everywhere; security headers set at the edge | Implemented |
| N1.8 | Documented retention and deletion policy | **Not built — see §8** |
| N1.9 | Data residency in India | Deployment choice; Vercel `bom1`, Render Singapore/India region |

### 5.2 Quality

| # | Requirement | Status |
|---|---|---|
| N2.1 | Automated test suite gating every merge | 730 tests |
| N2.2 | Suite green on the production database engine | PostgreSQL 16 verified |
| N2.3 | Static analysis and security scan on every build | `ruff` + `bandit`, both clean |
| N2.4 | No shipped endpoint may return 500 on a no-argument call | Smoke test over the OpenAPI surface |
| N2.5 | Cross-module agreement asserted, not assumed | §6.1 |
| N2.6 | Monetary arithmetic in `Decimal` with `ROUND_HALF_UP`, never float | Implemented |

### 5.3 Performance and availability

| # | Target | Basis |
|---|---|---|
| N3.1 | Validate a 5,000-employee register within 60s | Configuration loaded once per request, not per row |
| N3.2 | Cost dashboard responds within 3s over 24 months | Single costing pass, memoised slab lookups |
| N3.3 | Bank file up to 50,000 rows per upload | Enforced limit with an explicit error beyond it |
| N3.4 | 99.5% monthly availability | Managed platform SLA; payroll is monthly, not real-time |
| N3.5 | Daily database backup, 7-day point-in-time recovery | Managed Postgres |

---

## 6. Acceptance criteria

### 6.1 Cross-module identities — asserted on every build

Any module can be internally consistent and still contradict its neighbour. A
client shown one payroll cost on a dashboard and another in their books will not
care which is right.

| # | Identity |
|---|---|
| AC1 | voucher debits **==** dashboard CTC |
| AC2 | voucher debits − credits **== 0**, by arithmetic, for a complete mapping |
| AC3 | headcount is one number across register, dashboard and voucher |
| AC4 | Σ(any dimensional split) **==** the entity total |
| AC5 | the voucher's salary-payable credit **==** the dashboard's net |

### 6.2 Behavioural acceptance — a planted-defect scenario

Acceptance is measured against a ten-employee, three-month, two-state scenario
carrying deliberate defects. A product that returns HTTP 200 on a perfect file
has proved almost nothing.

| # | Planted defect | Must be caught as |
|---|---|---|
| AC6 | PF wages present, nothing deducted | `STAT-001`, CRITICAL |
| AC7 | Three days lost, thirty days paid | `ATT-020`, CRITICAL, valued in rupees |
| AC8 | Overtime worked, none paid | `ATT-022` |
| AC9 | Paid to an account not on the master | `bank.account_differs_from_master`, high |
| AC10 | Due pay, no line in the bank file | `bank.not_in_file`, high |
| AC11 | Paid to a code on no register | `bank.not_in_register`, high |
| AC12 | An attendance file that does not add up | Refused before storage |

**AC13 — No false positives.** In the same run, no employee other than the
intended one may be flagged by the rule in question.

**AC14 — Honest silence.** A workspace with no attendance register produces no
attendance findings at all, rather than flagging every employee as unverifiable.

---

## 7. Configuration principle

Anything that legitimately differs between companies is **data**. Anything that
would let a client configure away a defect is **not**.

| Configurable per entity | Deliberately fixed |
|---|---|
| Bank file layouts, JV accounts and split, posting basis, export shape | The voucher balance check |
| Daily-rate basis, day tolerance, overtime multiple | "This file does not add up" |
| Statutory rates, slabs, ceilings, effective dates | The `earnings + employer = CTC` identity |
| Rupee tolerances, spike thresholds | Tolerance wide enough to bury a statutory minimum |
| Rule suppressions — recorded, with who and when | Silent suppression |

Where a company's practice and the law disagree, the finding stays. It can be
**waived on the record**, with a name and a date against it. That is a different
thing from switching it off, and the difference is the entire value of an
independent second opinion.

---

## 8. Known gaps at baseline

Stated plainly because a BRD that hides them is not a baseline.

| # | Gap | Impact | Disposition |
|---|---|---|---|
| G1 | No data retention or deletion policy engine | DPDP Act obligation unmet for erasure requests | Required before processing a third party's data at scale |
| G2 | `passlib` imports `crypt`, removed in Python 3.13 | Blocks a runtime upgrade | Pinned to Python 3.12; replace before upgrading |
| G3 | `xlsx` npm advisory with no fixed version | Frontend dependency audit shows a high finding | Server-side generation is `openpyxl`; assess client-side usage |
| G4 | `validation.py` at ~59% line coverage | Highest-complexity module, thinnest coverage | Raise before major refactor |
| G5 | No rate limiting on authentication endpoints | Credential stuffing exposure | Add at the edge before public signup |
| G6 | Bank presets unverified against live bank specifications | A wrong mapping reconciles against the wrong column | Mitigated by the mandatory test-against-a-file step |
| G7 | No automated browser end-to-end tests | UI regressions caught only by manual pass | Acceptable at this scale; revisit at multi-tenant volume |

---

## 9. Glossary

| Term | Meaning here |
|---|---|
| **Entity** | One legal employer. The unit of data isolation and statutory configuration |
| **Register** | The salary register — what payroll paid, one row per employee per month |
| **Measure** | One line of the cost taxonomy, e.g. `er_pf`, `basic_da` |
| **Dimension** | A reporting attribute, e.g. department, cost centre — snapshotted at upload |
| **Finding** | One rule failing for one employee in one month, with identity across months |
| **Exception** | One reconciliation difference, stored against a run |
| **Exposure** | Accumulated statutory shortfall with interest and damages by age |
| **Evidence pack** | The workbook proving what a signed period contained |
