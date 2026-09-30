# Control register and control-to-evidence matrix

Baseline: **ISO/IEC 27001:2022 (incl. Amd 1:2024) Annex A** and **OWASP ASVS
5.0.0 Level 2**, plus controls the risk assessment selected. Last reviewed 30
September 2026.

**How to read the status.** A control is marked from evidence, never from
intent or documentation alone:

| Status | Means |
|---|---|
| **Implemented — verified** | Code or configuration exists *and* a named test or command was run against it, with the result recorded here |
| **Partial** | Some of the requirement is met and verified; the gap is stated |
| **Not implemented** | Nothing yet |
| **Organisational — not verifiable here** | Depends on people, contracts or records a repository cannot show |

**Citation rule.** Annex A references give the control number and title from
ISO/IEC 27001:2022. ASVS references give the requirement ID only where the
text was read from the published 5.0 standard (V6 and V7 on 30 Sep 2026);
elsewhere the chapter is cited, and a requirement-level mapping is left to the
external assessor rather than guessed. A mapping is a claim that the control
*addresses* the requirement, not that an auditor has accepted it.

Owners are roles. Priority: P0 now · P1 this month · P2 this quarter.

---

## A. Access and tenant isolation

### AC-01 — One company never reaches another's data
- **Requirement:** ISO A.8.3 *Information access restriction*; A.5.15 *Access control*. ASVS V8 (Authorization).
- **Area / assets:** every tenant-scoped route; all client payroll data.
- **Threat / risk:** Company A names company B's identifier (T1). Impact: disclosure of personal data across clients — the most damaging failure this product can have.
- **Implementation / evidence:** `X-Entity-Id` resolved server-side against membership (`deps.get_current_entity`); a stranger's company is 404. Object-level ownership checks in routes. `ctc.py` fixed (F1).
- **Remediation required:** none outstanding in code.
- **Owner · priority:** Engineering · done.
- **Verification · result:** `tests/test_isolation_sweep.py` — 127 identifier-taking routes × 75 of company B's identifiers, as company A, read and write methods: **0 leaks, 0 server errors** on SQLite and PostgreSQL. The route list is read from the application, so new routes are swept automatically.
- **Residual / dependencies:** one earlier PostgreSQL run failed and did not reproduce (R13). Admin routes are excluded from the sweep and covered by `test_support_access.py`.

### AC-02 — Platform staff have no access to client payroll by role
- **Requirement:** A.8.2 *Privileged access rights*; A.5.18 *Access rights*.
- **Area / assets:** `/api/admin/*`, support sessions.
- **Threat / risk:** insider or compromised staff account reads client data (T14).
- **Implementation / evidence:** platform role grants no tenant access; break-glass grants are time-boxed, read-only, masked, recorded in the client's trail (existing). Staff sign-in is now throttled, MFA-capable, and logged (`security_events`).
- **Remediation required:** turn on `REQUIRE_MFA_FOR_PLATFORM_STAFF` after enrolment (R6).
- **Owner · priority:** Platform owner · P1.
- **Verification · result:** `tests/test_support_access.py`, `tests/test_portal_auth.py` pass; `test_requiring_it_for_staff_locks_no_one_out` passes.
- **Residual:** enforcement is off by default until the owner decides.

### AC-03 — Least privilege inside a company
- **Requirement:** A.5.15, A.8.3; A.8.11 *Data masking*. ASVS V8.
- **Implementation / evidence:** owner / manager / analyst / viewer roles; identity masked below analyst and always under support (`deps.get_identity`); maker-checker switches.
- **Verification · result:** existing role tests in the suite pass on both dialects.
- **Status:** Implemented — verified. **Residual:** field-level export permissions beyond masking are not configurable (P2).

## B. Authentication and sessions

### AU-01 — Anti-automation on sign-in
- **Requirement:** A.8.5 *Secure authentication*. ASVS 6.1.1, 6.3.1.
- **Area / assets:** `/api/auth/login`, `/platform-login`, `/mfa/verify`, `/password-reset-request`.
- **Threat / risk:** credential stuffing, brute force (T2).
- **Implementation / evidence:** `app/services/auth_security.py` — per-identifier failures shared through the database; 10 in 15 minutes locks for 15 minutes (`LOGIN_*` settings); unknown addresses locked the same way; `Retry-After` returned; locks expire on their own; `app.auth_recovery unlock`.
- **Remediation required:** IP-level limiting at an edge (R10) — the app sees the relay's address.
- **Owner · priority:** Engineering · P2 for the edge part.
- **Verification · result:** `test_guessing_locks_the_identifier_even_against_the_right_password`, `test_guessing_the_second_step_locks_it` — pass.
- **Status:** Partial (no IP dimension).

### AU-02 — No account enumeration
- **Requirement:** ASVS 6.3.8 (L3, adopted by risk).
- **Implementation / evidence:** identical 401 for wrong address and wrong password; dummy bcrypt verification for unknown addresses; uniform password-reset answer.
- **Verification · result:** `test_a_wrong_address_and_a_wrong_password_read_the_same`, `test_a_password_reset_request_says_nothing…` — pass. Timing equalisation is by construction, not measured.
- **Status:** Implemented — verified (message and status); timing not measured.

### AU-03 — Password policy
- **Requirement:** A.5.17 *Authentication information*. ASVS 6.2.1, 6.2.4, 6.2.9, 6.2.12.
- **Implementation / evidence:** 8–128 characters; refused if among the 10,000 most common (SecLists / NCSC list, MIT, in `app/data`); checked at sign-up, invitation and reset; refused values not echoed in 422 bodies.
- **Remediation required:** breached-password check (6.2.12); bcrypt 72-byte limit (R9).
- **Verification · result:** `test_a_common_password_is_refused…` — pass.
- **Status:** Partial (6.2.12 not met).

### AU-04 — Multi-factor authentication
- **Requirement:** A.8.5. ASVS 6.3.3, 6.5.1, 6.5.5, 6.5.8, 6.4.3, 6.4.4, 6.5.6.
- **Implementation / evidence:** TOTP via `cryptography` (RFC 6238, 30 s step, ±1 step), secret sealed with Fernet, codes single-use (`mfa_last_step`), 10 single-use recovery codes stored as SHA-256; enrolment needs the password; organisation switch `members_require_mfa` and `REQUIRE_MFA_FOR_PLATFORM_STAFF`, both lock-out-safe (enrol-only sessions); password reset does not remove the factor; lost factor → `app.auth_recovery reset-mfa` after out-of-band identity check.
- **Remediation required:** turn enforcement on (R6); identity-proofing procedure for 6.4.4 is written in the runbook but not yet exercised.
- **Owner · priority:** Client owners / platform owner · P1.
- **Verification · result:** `test_two_step_sign_in`, `test_requiring_it_for_staff_locks_no_one_out`, `test_an_owner_can_require…`, `test_a_password_reset_does_not_bypass_two_step_sign_in`, `test_the_recovery_tool_removes_a_lost_second_factor` — pass. Frontend: 3 new tests in `tests/auth.test.cjs` — pass.
- **Status:** Implemented — verified (capability). 6.3.3 is met only where enforcement is on.

### AU-05 — Session lifetime and revocation
- **Requirement:** ASVS 7.3.1, 7.3.2, 7.4.3, 7.5.1, 7.5.2. A.8.5.
- **Implementation / evidence:** access 30 min; refresh rotated with replay detection (family ends after 60 s grace); absolute 12 h from sign-in (`auth_time`); `session_version` ends every session on reset, "sign out everywhere", MFA enrolment, admin or operator action; re-authentication (password) before MFA changes.
- **Remediation required:** a list of active sessions (7.5.2 asks to *view* them) — R12.
- **Verification · result:** `test_a_password_reset_ends_every_session`, `test_sign_out_everywhere`, `test_a_replayed_refresh_token_ends_the_session_family`, `test_a_session_ends_at_its_absolute_limit…`, `test_a_token_from_before_session_versions_still_works` — pass.
- **Status:** Partial (7.5.2 view).

### AU-06 — Token storage in the browser
- **Requirement:** ASVS V3 (Web Frontend Security), V7.
- **Implementation / evidence:** tokens in `localStorage`; a CSP limits which scripts can run.
- **Remediation required:** `HttpOnly` cookie for the refresh token via the relay; nonce CSP (R7).
- **Owner · priority:** Engineering · P2.
- **Status:** Not implemented.

## C. Data, secrets and cryptography

### DS-01 — Secrets at rest
- **Requirement:** A.8.24 *Use of cryptography*; A.5.17. ASVS V11, V13.
- **Implementation / evidence:** bcrypt (passlib); refresh tokens, reset tokens, invitation tokens, integration keys stored as SHA-256; connection secrets and TOTP secrets Fernet-sealed with `STUDIO_SECRET_KEY` (rotation by key list); no custom cryptography.
- **Verification · result:** `test_two_step_sign_in` asserts the secret is not stored in clear; existing Studio secret tests pass.
- **Residual:** `STUDIO_SECRET_KEY` now also protects second factors — losing it forces re-enrolment. Key custody is organisational.
- **Status:** Implemented — verified.

### DS-02 — No credentials in source, bundles, URLs, logs or samples
- **Requirement:** A.8.4 *Access to source code*; A.5.17; A.8.15 *Logging*. ASVS V13, V16.
- **Implementation / evidence:** gitleaks over the full history in CI; `.gitleaksignore` records two reviewed findings; security events and log lines never carry passwords, tokens or codes; validation errors redact secret fields; the MFA challenge lives in memory only.
- **Verification · result:** gitleaks 8.21.2 over 336 commits: 2 findings (example passwords in docs) → replaced → 0. Tests assert no password, code or recovery code appears in any event.
- **Remediation required:** confirm/rotate the `qa@peopleopslab.in` account (R3).
- **Status:** Implemented — verified; rotation pending.

### DS-03 — Personal data in logs
- **Requirement:** A.8.15; A.5.34 *Privacy and protection of PII*.
- **Implementation / evidence:** request logs carry method, path, status, time, request id; security events keep the sign-in identifier (needed to investigate an attack on an account) in the database, not in general logs.
- **Residual:** unhandled-exception logs include exception text, which could contain a value (P2 review).
- **Status:** Partial.

## D. Reports, exports and files

### EX-01 — Exports audited
- **Requirement:** A.8.12 *Data leakage prevention*; A.8.15. ASVS V16.
- **Implementation / evidence:** `export.downloaded` for run export, evidence pack, findings export, JV, evidence attachment; reports already audited.
- **Verification · result:** `test_export_safety.py` asserts audit rows — pass.
- **Residual:** an expired link stops *further* downloads; a file already on a device is outside the product's control.
- **Status:** Implemented — verified.

### EX-02 — Exports cannot carry live formulas
- **Requirement:** ASVS V1 (Encoding and Sanitization).
- **Implementation / evidence:** `app/services/export_safety.py` on every generated workbook; CSV exports with free text escape leading `= + - @` (existing).
- **Verification · result:** `test_a_formula_in_an_employee_name_is_exported_as_text` — the raw sheet XML contains no `<f>`; without the guard openpyxl writes `<f>2+5</f>` (checked). Pass.
- **Residual:** the JV CSV is an import file for accounting systems and is not escaped (escaping would corrupt amounts); its free-text fields come from client configuration.
- **Status:** Implemented — verified.

### UP-01 — Uploaded files are data, bounded
- **Requirement:** ASVS V5 (File Handling). A.8.7 *Protection against malware* (partial — no AV scanning).
- **Implementation / evidence:** 50 MB body ceiling on every route before reading; expanded-size check on `.xlsx`; `defusedxml` pinned; macros never read; attachments served as `attachment` with `nosniff` and a `default-src 'none'` policy.
- **Verification · result:** `test_upload_safety.py` — zip bomb refused before parsing, macro workbook read as data, `DEFUSEDXML` true; `test_an_oversized_body_is_refused…` — pass.
- **Remediation required:** malware scanning of evidence attachments (P2, needs a scanning service — a paid or hosted decision).
- **Status:** Partial.

## E. API, Studio and web

### AP-01 — Security headers and API surface
- **Requirement:** ASVS V3, V4, V13. A.8.9 *Configuration management*.
- **Implementation / evidence:** `app/http_guard.py`; `next.config.mjs` CSP and headers; OpenAPI UI off in production; request id sanitised; `poweredByHeader` off; image optimiser off.
- **Verification · result:** `test_every_answer_carries_the_security_headers`, `test_a_forged_request_id_is_replaced`, `test_production_hides_the_interactive_api_reference` — pass. Web headers verified in a production build (see PR).
- **Residual:** CSP allows `'unsafe-inline'` scripts (R7).
- **Status:** Partial.

### AP-02 — Studio outbound calls (SSRF), webhooks, scripting
- **Requirement:** ASVS V4, V15. A.8.20 *Networks security*.
- **Implementation / evidence:** existing: allow-list, HTTPS, public-address check with pinning, no redirects, response cap, HMAC webhooks with freshness and de-duplication, scripting disabled (no sandbox) with declarative transforms only.
- **Verification · result:** existing Studio test suites pass on both dialects. Not re-attacked in this work — in the pentest scope.
- **Status:** Implemented — verified by existing tests.

### AP-03 — Integration API keys
- **Requirement:** A.5.17, A.8.5. ASVS V4, V6.
- **Implementation / evidence:** existing: SHA-256 stored, scopes, company list, expiry ≤ 1 year, rotation overlap, per-key rate limit, idempotency.
- **Status:** Implemented — verified by existing tests. **Residual:** rate limit is per process.

## F. Logging, monitoring, records

### LG-01 — Security event log
- **Requirement:** A.8.15 *Logging*; A.8.16 *Monitoring activities*. ASVS V16.
- **Implementation / evidence:** `security_events` — sign-ins (success, failure, blocked), MFA, refresh replay, resets, revocations, support sessions, unlocks, reads of the log itself; `GET /api/admin/security/events`.
- **Remediation required:** alerting and off-platform retention of 180 days (R11; CERT-In).
- **Verification · result:** event assertions in `test_auth_security.py` — pass.
- **Status:** Partial (no alerting).

### LG-02 — Audit trail integrity
- **Requirement:** A.5.33 *Protection of records*; A.5.28 *Collection of evidence*.
- **Implementation / evidence:** no application path edits `audit_events`; DB trigger refuses UPDATE/DELETE on `audit_events` and `security_events` (FK cascades allowed on PostgreSQL).
- **Verification · result:** `test_audit_append_only.py` on SQLite and PostgreSQL — pass; cascade still deletes (checked by hand, rolled back).
- **Residual:** database owner can drop the trigger (R8).
- **Status:** Partial.

## G. Development and supply chain

### SD-01 — Secure development and testing
- **Requirement:** A.8.25 *Secure development life cycle*; A.8.28 *Secure coding*; A.8.29 *Security testing in development and acceptance*; A.8.32 *Change management*.
- **Implementation / evidence:** CI: ruff, bandit, tests on SQLite **and PostgreSQL** (new), docs check, supply-chain job (new). Security regression tests listed above.
- **Remediation required:** branch protection with required reviews and required checks on `main` — not verifiable from here (organisational).
- **Status:** Partial.

### SD-02 — Vulnerability management of dependencies
- **Requirement:** A.8.8 *Management of technical vulnerabilities*.
- **Implementation / evidence:** `tools/dependency_audit.py` fails on unassessed advisories and expired reviews; `security/dependency-exceptions.json`; Dependabot; Next.js 14.2.35; DOMPurify ≥ 3.4.16.
- **Verification · result:** audit gate run locally: 34 advisories reported, 0 unassessed; a synthetic unknown advisory fails it (checked).
- **Remediation required:** Next.js 15.5+ (R4); `xlsx` 0.20.3 (R5); PyJWT (R14).
- **Status:** Partial.

### SD-03 — Software bill of materials
- **Requirement:** A.5.9 *Inventory of information and other associated assets* (software part).
- **Implementation / evidence:** CycloneDX SBOMs (backend runtime environment: 50 components; frontend runtime: 130) generated in CI and kept as artifacts.
- **Verification · result:** both commands run locally, output valid CycloneDX (1.6 / 1.4).
- **Status:** Implemented — verified.

### SD-04 — Test data
- **Requirement:** A.8.33 *Test information*; A.8.31 *Separation of development, test and production environments*.
- **Implementation / evidence:** all tests and drills use synthetic data; Studio environments are separate companies.
- **Status:** Implemented for this work. Organisational rule to keep it so: `isms/05-secure-development.md`.

## H. Continuity and recovery

### BC-01 — Backup and restore
- **Requirement:** A.8.13 *Information backup*; A.5.30 *ICT readiness for business continuity*; A.5.29 *Information security during disruption*.
- **Implementation / evidence:** `backend/tools/restore_drill.py`; `docs/DATABASE_MIGRATION.md`.
- **Verification · result:** drill on synthetic data — **PASS** (`docs/evidence/restore-drill-2026-09-30.md`): 85 tables, 39,411 rows identical by digest; app booted and signed in on the copy.
- **Remediation required:** production has **no backups** (free plan) and expires 22 Oct 2026 (R1). Paid plan with PITR, then a production-backup drill.
- **Owner · priority:** Business owner · **P0**.
- **Status:** Not implemented for production. Procedure verified.

## I. Governance (organisational)

| ID | Annex A | Status | Record the organisation must produce |
|---|---|---|---|
| GV-01 | 5.1 *Policies for information security* | Template only | Approved policy (`isms/02-information-security-policy.md`) |
| GV-02 | 5.9, 5.12 inventory and classification | Draft in `SECURITY.md` §2 | Owned, reviewed asset register |
| GV-03 | 5.19, 5.23 suppliers and cloud | Not implemented | Supplier register with Render, GitHub; their assurance reports; DPAs |
| GV-04 | 5.24–5.26 incidents | Draft runbook | Exercised runbook; incident log |
| GV-05 | 5.31, 5.34 legal and privacy | Not implemented | Legal register; DPDP/CERT-In view (§8 of `SECURITY.md`) |
| GV-06 | 5.35 *Independent review of information security* | Not implemented | Pentest report (`PENTEST_SCOPE.md`), internal audit |
| GV-07 | 6.3 awareness and training | Not verifiable here | Training records |
| GV-08 | Clause 4.1/4.2 climate (Amd 1:2024) | Template question | A recorded decision on relevance |

The full Statement of Applicability must be completed against the purchased
text of ISO/IEC 27001:2022 Annex A (93 controls). `isms/04-statement-of-applicability.md`
lists only the controls this register addresses, and says so.
