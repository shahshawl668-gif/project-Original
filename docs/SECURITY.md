# PeopleOpsLab — security assessment and ISMS readiness

**Status on 30 September 2026.** An internal assessment by an engineer working in
the repository, followed by fixes. It is **not** a certification, not an audit,
and not an independent penetration test — none of those has happened. The
product is **not** ISO/IEC 27001 certified, and nothing in this repository may
say or imply that it is. It is not "fully secure"; no system is, and the open
items in §9 are real.

| Document | What it is | Status |
|---|---|---|
| This file | Scope, inventory, data flows, threat model, what was found and fixed, what remains | Assessment — current |
| [`security/CONTROL_REGISTER.md`](security/CONTROL_REGISTER.md) | Control register and control-to-evidence matrix | Current; controls marked by evidence, not by intent |
| [`security/INCIDENT_RUNBOOK.md`](security/INCIDENT_RUNBOOK.md) | What to do when something happens | Draft procedure — not yet exercised |
| [`security/PENTEST_SCOPE.md`](security/PENTEST_SCOPE.md) | Brief for an independent assessor | Ready to send; no assessor engaged |
| [`security/isms/`](security/isms/) | ISO/IEC 27001 document set | **Templates.** None approved, none operating |
| [`evidence/restore-drill-2026-09-30.md`](evidence/restore-drill-2026-09-30.md) | Recorded restore test | Synthetic data only — not production |
| [`../security/dependency-exceptions.json`](../security/dependency-exceptions.json) | Assessed dependency advisories | Current; review dates enforced by CI |

---

## 1. Scope and method

**In scope:** the repository at `shahshawl668-gif/project-Original` — the FastAPI
backend, the Next.js frontend and relay, the integration API, PeopleOps Studio,
CI — and the production configuration visible through the Render API
(metadata only: plans, regions, settings; no production data was read).

**Out of scope, and why:** active testing of production (not authorised, and
the brief forbids it); third-party scanning; the people and processes of the
business, which cannot be assessed from a repository; Render, GitHub and the
domain registrar as organisations.

**Method.** Read the code for each trust boundary; write a test that tries the
attack; fix what the test finds; keep the test. Every "Implemented" in the
control register points at a test or a command that was run, with its result.
All active testing used local databases and synthetic data.

**Standards, checked against their publishers on 30 September 2026:**

| Standard | Version relied on | Note |
|---|---|---|
| ISO/IEC 27001 | **2022, with Amendment 1:2024** (climate action changes to clauses 4.1 and 4.2) | The amendment adds a requirement to decide whether climate change is a relevant issue — see `isms/01-scope-and-context.md` |
| OWASP ASVS | **5.0.0** (May 2025), Level 2 | 17 chapters, V1–V17. Requirement IDs quoted in the register were read from the published 5.0 text, not recalled |
| DPDP Act 2023 / DPDP Rules 2025 | Rules notified 13–14 Nov 2025; most operative rules (including breach intimation, Rule 7) commence 18 months after publication | Summary from published commentary. **Needs qualified legal review** — this document gives no legal opinion |
| CERT-In directions under s.70B(6) IT Act | 28 April 2022 | Report specified incidents within 6 hours; keep ICT logs 180 days within India. **Applicability needs legal review** |

ISO certification does not satisfy DPDP, CERT-In or contractual obligations,
and the reverse is also true. They are assessed separately (§8).

## 2. What the product holds — inventory

| Asset | Where | Classification | Why it matters |
|---|---|---|---|
| Salary registers, CTC, attendance, employee master | PostgreSQL (`salary_register_rows`, `ctc_records`, `attendance_rows`, `employee_records`) | **Confidential — personal data** (names, PAN, UAN, bank accounts, pay) | The whole product; a leak harms employees who never chose this vendor |
| Findings, comments, evidence attachments | `finding_records`, `finding_states`, `finding_attachments` | Confidential — personal data | Attachments are arbitrary client files |
| Generated reports and evidence packs | `report_jobs.artifact` (in the database, 30-day retention) | Confidential — personal data | Leave the product by design |
| Configuration, statutory settings, rules | config tables | Internal | Wrong configuration → wrong findings |
| Audit trail | `audit_events` | Confidential — integrity critical | Evidence of who did what |
| Security event log | `security_events` (new) | Internal — contains sign-in identifiers | Evidence of attacks on accounts |
| Password hashes, refresh-token digests, TOTP secrets (sealed), recovery-code digests | `users`, `refresh_tokens` | **Secret** | Account takeover |
| Integration keys (SHA-256), connection secrets (Fernet) | `studio_credentials`, `studio_connections` | **Secret** | Access to clients' other systems |
| `JWT_SECRET`, `STUDIO_SECRET_KEY`, `DATABASE_URL` | Render environment | **Secret** | Forge any session; read every secret; read every row |
| Source code and CI | GitHub | Internal | Supply-chain path into production (auto-deploy from `main`) |

## 3. Data flows and trust boundaries

```
 Payroll user's browser ──TB1──▶ Next.js web (Render, Singapore)
   tokens in localStorage          │  /api/proxy relay (allow-listed headers)
                                    ▼
 Integration client ────TB2──▶ FastAPI API (Render, Singapore) ◀──TB5── Platform staff browser
   pol_live_… key                  │   also reachable directly at *.onrender.com
                                    │
          ┌──────────TB3────────────┼──────────────TB4──────────────┐
          ▼                         ▼                               ▼
  PostgreSQL (Render, Singapore)  Other systems (Studio pulls,   Uploaded files
  free plan, no backups, no HA    webhooks out) — SSRF guard     (xlsx/csv) parsed in-process
                                   + allow-list + HMAC
```

| Boundary | Crosses | Principal control |
|---|---|---|
| TB1 browser → web/API | Every user action | Bearer token; `X-Entity-Id` resolved server-side against membership (404 for a stranger's company) |
| TB2 machine → integration API | Imports, reads | Hashed, scoped, expiring keys; per-key rate limit; idempotency |
| TB3 API → database | Everything | One application role; tenant filter in every query (verified by the sweep, §5) |
| TB4 API → other systems | Studio connections, webhooks | HTTPS-only, allow-listed host, public-address check with pinning, no redirects, response size cap |
| TB5 platform staff → client data | Support | No access by role; time-boxed, read-only, masked break-glass grants recorded in the *client's* trail |
| Files → parser | Uploads | Size ceilings, expanded-size check, `defusedxml`, no macros, typed parsing |

## 4. Threat model (STRIDE, per boundary)

| # | Threat | Boundary | Before this work | Now |
|---|---|---|---|---|
| T1 | Company A reads or changes company B's data by naming B's identifiers | TB1 | Entity header checked; object-level checks per route, untested as a whole. **One route answered 200** for a foreign CTC upload id (empty list, but it confirmed nothing and crashed on a malformed id) | Fixed. A sweep replays 75 of B's identifiers against all 127 identifier-taking routes as A (9,525 requests): no 2xx, no 5xx, both dialects |
| T2 | Password guessing / credential stuffing | TB1, TB5 | **No throttling at all** | Per-identifier lock after 10 failures in 15 min, including on unknown addresses; equal-time rejection |
| T3 | Account enumeration | TB1 | Password-reset answer said whether the address existed | Uniform answers; rate limited |
| T4 | Stolen password alone is enough | TB1, TB5 | **No second factor** | TOTP with recovery codes; organisation- and platform-level enforcement that cannot lock out |
| T5 | Stolen refresh token used indefinitely | TB1 | Rotation existed; replay undetected; sessions extendable forever; reset left sessions alive | Replay ends the whole family; 12-hour absolute limit; reset/"sign out everywhere"/admin revocation end every session |
| T6 | Malicious workbook exhausts memory or reads files | Files | Only a request-size cap on the integration API | Expanded-size check before parsing; `defusedxml` pinned; 50 MB body ceiling on every route |
| T7 | Exported spreadsheet runs attacker's formula (`=HYPERLINK`, DDE) | Exports | **Live formulas were written** into run exports and evidence packs from employee names | All generated workbooks force strings to text; tested |
| T8 | Downloads of payroll data leave no trace | Exports | Reports audited; run export, evidence pack, findings export, JV and attachments **not** | All audited as `export.downloaded` |
| T9 | Audit trail edited to hide an action | TB3 | Append-only by convention | Database trigger refuses UPDATE/DELETE (owner can still drop it — open item) |
| T10 | Clickjacking, MIME sniffing, script injection via the web app | TB1 | No security headers anywhere | Headers on API and web; enforced CSP (inline scripts still allowed — open item) |
| T11 | Log forging via request id | TB1 | Caller's `X-Request-Id` written to logs verbatim | Accepted only if a plain token |
| T12 | Vulnerable or tampered dependency | Supply chain | No dependency audit, no SBOM, no secret scan | CI gate on unassessed advisories; SBOMs; history secret scan; Dependabot |
| T13 | Credential committed to the repository | Supply chain | Two literal example passwords in docs | Replaced; scan in CI; rotation of any real account is an owner action (§9) |
| T14 | Support staff read client payroll silently | TB5 | Break-glass grants, client-recorded, masked | Unchanged; staff sign-in now also throttled, MFA-capable and logged |
| T15 | SSRF through Studio connections | TB4 | Guarded (allow-list, address checks, pinning) | Unchanged; in the pentest scope |
| T16 | Data loss | TB3 | **Free database, no backups, expiring 22 Oct 2026** | Unchanged — needs a paid plan (§9). Restore procedure now tested on synthetic data |
| T17 | Denial of service against the web tier | TB1 | Next.js 14.2.18 with known advisories incl. a critical middleware bypass | 14.2.35; image optimiser off; seven App Router advisories remain until the 15.5+ upgrade |

## 5. What was found and fixed

Each item has a regression test that fails without the fix.

| # | Finding | Severity | Fix | Test |
|---|---|---|---|---|
| F1 | `GET /api/ctc/uploads/{id}` answered 200 (empty) for another company's upload, and 500 for a malformed id | Medium | Ownership check, typed id, 404 | `test_isolation_sweep.py` |
| F2 | No sign-in throttling on client or platform sign-in | High | `auth_security` throttle | `test_auth_security.py::test_guessing_locks…` |
| F3 | Password reset revealed which addresses have accounts | Medium | Uniform answer + rate limit | `…::test_a_password_reset_request_says_nothing…` |
| F4 | Password reset did not end existing sessions | High | Session versions | `…::test_a_password_reset_ends_every_session` |
| F5 | No second factor | High (for payroll data) | TOTP, recovery codes, enforcement | `…::test_two_step_sign_in`, `…requiring_it_for_staff…`, `…owner_can_require…` |
| F6 | Refresh-token replay undetected; sessions without an absolute limit | Medium | Rotation marks, family revocation, `auth_time` | `…::test_a_replayed_refresh_token…`, `…absolute_limit…` |
| F7 | Error handler dropped every header on an `HTTPException` (so `Retry-After` never reached clients) | Low | Headers passed through | `…::test_guessing_locks…` asserts `Retry-After` |
| F8 | Formula injection in Excel exports | Medium | `export_safety` | `test_export_safety.py` |
| F9 | Several payroll exports not audited | Medium | `export.downloaded` records | `test_export_safety.py` |
| F10 | Workbook "zip bomb" parsed without limit | Medium | `upload_safety` | `test_upload_safety.py` |
| F11 | `defusedxml` present only by accident of a transitive dependency | Low | Pinned; test asserts openpyxl uses it | `test_upload_safety.py` |
| F12 | No security headers; OpenAPI UI public in production; request-id log forging | Medium | `http_guard`, `expose_api_docs`, `safe_request_id` | `test_auth_security.py` HTTP tests |
| F13 | Audit trail editable through the application's connection | Medium | Trigger on both dialects | `test_audit_append_only.py` |
| F14 | Common passwords accepted; refused passwords echoed back in 422 bodies | Medium | `password_policy`; redaction | `…::test_a_common_password…` |
| F15 | Next.js 14.2.18 with a critical middleware-bypass advisory and several DoS advisories | High | 14.2.35, image optimiser off; DOMPurify ≥ 3.4.16 | `npm audit` + `tools/dependency_audit.py` |
| F16 | Literal passwords in two documents | Low–Medium | Placeholders; `.gitleaksignore` records the review | gitleaks: no findings |
| F17 | No dependency audit, SBOM or secret scan; CI tests SQLite only | Medium | CI jobs `backend-postgres`, `supply-chain`; Dependabot | Run locally (§6); first CI run on the PR |

Nothing was changed in production: no deploy, no setting, no data. The fixes
reach production when the pull request is merged and Render auto-deploys `main`.

## 6. Testing — what was run, and what it showed

All on 30 September 2026, in an isolated container, on synthetic data.

| Test | Result |
|---|---|
| Backend suite, SQLite | **1,188 passed, 1 skipped** (the skip is the existing PostgreSQL-only cancel test). The files changed after that run were re-run on both dialects: 54 passed + 1 skipped / 55 passed |
| Backend suite, PostgreSQL 16 | **1,190 passed**, including the isolation sweep |
| Cross-company sweep | 127 routes × 75 of company B's identifiers = 9,525 requests as company A: 0 leaks, 0 server errors. One earlier PostgreSQL run failed and was not reproducible in four further runs; its log was lost when the run was stopped for unrelated edits — **recorded as an open item, not dismissed as a flake** |
| Frontend auth tests | 17 passed (3 new: second step) |
| Frontend typecheck, lint | Clean |
| bandit | 0 issues (one reviewed `nosec`: HMAC-SHA1 in RFC 6238 TOTP) |
| pip-audit | Initially 1 advisory (ecdsa, CVE-2024-23342, via python-jose) — not reachable (HS256 only). Removed by replacing python-jose with PyJWT: **no known vulnerabilities**. Tokens verified interchangeable in both directions, so the deploy signs no one out and a rollback is safe; forged tokens (wrong key, `alg=none`, expired) refused — `test_a_forged_token_opens_nothing` |
| npm audit (runtime) | 33 advisories across next, xlsx, postcss, nanoid — each assessed in `dependency-exceptions.json`; 9 **apply** and are provisional |
| gitleaks, full history (336 commits) | 2 findings (example passwords in docs) → fixed and recorded; 0 after |
| Browser walk, production build, API in production mode | Signed in; enrolled two-step sign-in through the page (10 recovery codes shown once); signed out and back in with a code; a wrong code refused with a message; "sign out everywhere" returned to sign-in and the old access token then got 401. API: all headers incl. HSTS, `/docs` and `/openapi.json` 404. Web: CSP and headers present. **No CSP violation on any page left to load**, including the formula editor (Monaco), Studio mapping, dashboards and Report Builder. Observed: when a navigation aborts an in-flight relay request, the client's existing fallback retries it against the direct API URL, and the CSP blocks that retry if the URL is not the relay's — harmless; fixed on 1 Oct 2026 — the fallback no longer fires while the page is being left (`tests/auth.test.cjs`, two tests) |
| Restore drill | PASS — 85 tables, 39,411 rows identical by content digest; application booted and signed in on the copy |

## 7. Hosting and organisational verification gaps

Read from the Render API on 30 September 2026 (metadata only):

| Item | Found | Gap |
|---|---|---|
| Database plan | `free`, expires **2026-10-22**, no high availability, no read replica | Deletion on expiry; **no backups exist to restore** |
| Region | **Singapore** (database and API) | CERT-In log localisation; DPDP cross-border considerations — legal review |
| API health check | none configured | A broken deploy is not held back |
| API exposure | reachable directly at `*.onrender.com`, allow-list `0.0.0.0/0` | CORS limits browsers, not other clients; a WAF/edge rate limit would add IP-level throttling, which the app cannot do reliably behind the relay |
| Auto-deploy | on every commit to `main` | Branch protection and required reviews on `main` could not be verified from here |
| Secrets | `JWT_SECRET`, `STUDIO_SECRET_KEY` in Render environment | Who can read them, and rotation history, cannot be verified from here |

Cannot be assessed from a repository at all: staff screening and training,
device security, access reviews, supplier contracts (Render, GitHub), the
DPA offered to clients, insurance, and physical security. The ISMS templates
in `security/isms/` name each as a record the organisation must produce.

## 8. Privacy, contractual and reporting obligations

Assessed separately from ISO, and **only as far as identifying them**; each
needs qualified review:

- **DPDP Act 2023 / Rules 2025.** For client payroll the client is likely the
  Data Fiduciary and PeopleOpsLab a Data Processor acting under contract — the
  contract should say so. Breach intimation (Rule 7: without delay, then
  detailed within 72 hours) falls on the fiduciary, who will need the
  processor's help within that clock; the runbook's notification step is built
  for that. Most operative rules commence in 2027; confirm dates.
- **CERT-In directions (2022).** 6-hour reporting of specified incidents;
  180-day log retention in India. Hosting in Singapore needs a view.
- **Client contracts.** Security schedules, breach-notice periods, audit
  rights, sub-processor lists (Render, GitHub) — not visible here.

## 9. Remaining risks, owners and next actions

Owners are roles; the business must name people. Priority: P0 now, P1 this
month, P2 this quarter.

| # | Risk | Owner | Priority | Next action |
|---|---|---|---|---|
| R1 | Free database deleted on 22 Oct; no backups | Business owner | **P0** | Paid plan with point-in-time recovery; then run `restore_drill.py` against a restored production backup in a separate instance and file the record |
| R2 | Data and logs outside India | Business owner + legal | **P0** | Legal view on CERT-In and DPDP; if needed, move to an India region. Render offers Oregon, Ohio, Virginia, Frankfurt and Singapore (render.com/docs/regions, checked 30 Sep 2026), so this means another host |
| R3 | Possible production account with a published password (`qa@peopleopslab.in`) | Platform owner | **P0** | Check whether it exists; if so, change its password or remove its access |
| R4 | Next.js App Router DoS advisories | Engineering | P1 | Upgrade to Next.js 15.5+ (major: React 19, async request APIs) and retest; exceptions expire 30 Nov 2026 |
| R5 | `xlsx` advisories (browser-side parsing) | Engineering | P1 | Install 0.20.3 from cdn.sheetjs.com, or parse previews server-side |
| R6 | Two-step sign-in is optional until an owner turns it on | Each client owner; platform owner for staff | P1 | Enrol all platform staff, then set `REQUIRE_MFA_FOR_PLATFORM_STAFF=true`; recommend clients turn on `members_require_mfa` |
| R7 | Tokens in `localStorage` (readable by any script that runs on the page) | Engineering | P2 | Move the refresh token to an `HttpOnly` cookie on the relay; then nonce-based CSP to drop `'unsafe-inline'` |
| R8 | Audit trail protected from the application, not from the database owner | Engineering | P2 | Ship `audit_events` to write-once storage outside the database (object lock), or anchor daily digests off-site |
| R9 | No breached-password check (ASVS 6.2.12); bcrypt ignores bytes past 72 | Engineering | P2 | k-anonymity breached-password lookup (sends a hash prefix to a third party — a privacy decision); pre-hash or move to Argon2id with rehash on sign-in |
| R10 | No IP-level throttling; API reachable directly | Engineering | P2 | Edge rate limiting / WAF in front of both services; restrict the API to the relay |
| R11 | No alerting on security events | Engineering | P2 | Alert on `refresh/detected`, lock bursts, `mfa_disabled`, support grants; ship logs to a retained store (180 days) |
| R12 | ~~Users cannot list their sessions (ASVS 7.5.2)~~ | Engineering | Done | Session list with per-session end on `/account/security` (1 Oct 2026); ending one takes effect at its next refresh, ≤ 30 min |
| R13 | One unexplained PostgreSQL sweep failure | Engineering | P2 | Run the sweep in CI on PostgreSQL (now in place) and capture the next failure's output |
| R14 | ~~`python-jose` pulls unmaintained `ecdsa`~~ | Engineering | Done | Replaced with PyJWT (1 Oct 2026) |
| R15 | No independent assessment | Business owner | P1 before real client data | Engage a tester with `security/PENTEST_SCOPE.md` |
| R16 | ISMS exists only as templates | Business owner | P1 | Approve scope, policy, risk method; start the records each template names |
| R17 | Statutory rates unsigned (GO_LIVE D6) | Payroll professional | P0 before real data | Unchanged by this work |

## 10. Accurate status

- **Implemented and tested in code:** F1–F17 above.
- **Deployed:** nothing yet. Merging the PR deploys it (Render auto-deploy).
  The migration is additive and signs no one out; two-step enforcement is off
  until someone turns it on.
- **Operating evidence:** one restore drill on synthetic data; none from production.
- **ISO/IEC 27001:** readiness templates only. Certification requires an ISMS
  that has operated long enough to produce records, an internal audit, a
  management review, and a Stage 1 and Stage 2 audit by an accredited
  certification body. None of that has happened.
- **Independent assessment:** not performed.
