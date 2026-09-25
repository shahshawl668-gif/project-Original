# Go-live runbook — Peopleopslab

How to get this product from a repository to a live service holding a real
client's payroll data, and how to prove at each step that it is safe to
continue.

`DEPLOYMENT.md` is the infrastructure reference — what to click, which
environment variable goes where. **This document is the sequence**: the order of
operations, the tests that gate each step, and what "done" means.

> **The one rule.** Nothing goes to production that has not survived a parallel
> run against a real month (Phase 4). Every earlier phase exists to make that
> parallel run cheap, not to replace it.

---

## Phase 0 — Decisions before any deployment

Settle these first. Changing them later is expensive.

| # | Decision | Default | Why it matters |
|---|---|---|---|
| D1 | Hosting shape | Vercel (frontend) + Render (API + Postgres) | Repo ships `render.yaml` and `railway.json` Blueprints |
| D2 | Region | India / Singapore | This is salary, PAN, Aadhaar and bank data. Under the DPDP Act 2023, where it rests is a decision you must be able to defend |
| D3 | Domain | `peopleopslab.in`, API at `api.` | Already wired through `render.yaml` and `vercel.json` |
| D4 | First client | One friendly entity, one month | A bureau's book is not a pilot |
| D5 | Who signs off | Named payroll lead at the client | Acceptance is theirs, not yours |
| D6 | Statutory verification | Client's own payroll expert reviews every seeded rate | The seeds are a starting point with **no legal force** |

### D6 is a blocker, not a formality

The product ships PT slabs, LWF rates, PF and ESI configuration and income-tax
slabs as editable defaults. They mirror common practice. **They are not legal
advice and nobody at your end has verified them for the client's states.**
Before a client's first production run, their payroll expert must review:

- PT slabs for every state in `pt_states`
- LWF rates and applicable months for every state in `lwf_states`
- PF configuration: ceiling, restriction basis, EDLI and admin rates
- ESI wage ceiling and rates
- Income-tax slabs for the financial year being validated
- The daily-rate basis (calendar / 26 / 30) against the client's own policy

Record the review. It is the first thing an auditor will ask about.

---

## Phase 1 — Pre-flight, on your own machine

Everything here must pass before anything is deployed anywhere.

### 1.1 Backend — the full suite

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-postgres.txt -r requirements-dev.txt

ruff check app tests          # must print "All checks passed!"
bandit -c pyproject.toml -r app   # must report 0 issues at every severity
pytest -q tests               # must report 730 passed (or more)
```

**What green means here.** 730 tests covering the statutory engines, the cost
taxonomy, attendance rules, reconciliation, the expression sandboxes, entity
isolation, and an end-to-end scenario with planted defects. It does **not** mean
the UI works — that is Phase 3.4.

**If `bandit` prints "nosec encountered … no failed test":** expected. Bandit
walks every AST node on an annotated line and warns for the ones that did not
need the waiver. Exit code is still 0.

### 1.2 Database parity — run the suite on PostgreSQL

SQLite is the development default. Production is PostgreSQL. A suite that only
ever runs on SQLite has not tested the database you are about to deploy on.

```bash
# start a throwaway PostgreSQL 16 (Linux; adjust the path for your install)
export PGDIR=/var/lib/postgresql/testdata
sudo rm -rf $PGDIR && sudo mkdir -p $PGDIR
sudo chown postgres:postgres $PGDIR && sudo chmod 700 $PGDIR
sudo -u postgres /usr/lib/postgresql/16/bin/initdb -D $PGDIR -U postgres --auth=trust
sudo -u postgres /usr/lib/postgresql/16/bin/pg_ctl -D $PGDIR \
  -o '-p 5433 -c listen_addresses=127.0.0.1' -l /tmp/pg.log start

psql -h 127.0.0.1 -p 5433 -U postgres -c "CREATE DATABASE payroll_test;"

cd backend
DATABASE_URL="postgresql://postgres@127.0.0.1:5433/payroll_test" pytest -q tests
```

**Expected: the same pass count as SQLite.** Verified at baseline —
730 passed on PostgreSQL 16.13, identical to SQLite.

This exercises the dialect-aware paths in `app/migrations.py`: `UUID` versus
`CHAR(32)`, the SQLite table-rebuild fallback that Postgres does not need, and
the `postgres://` → `postgresql+psycopg2://` URL normalisation in `config.py`.

### 1.3 Upgrade path — prove an existing database survives

New tables come from `create_all`; new columns come from `_COLUMN_PATCHES` in
`app/database.py`. Both must work against a database that already holds data.

```bash
# create a database at the previous release, load a month of data, then
# start the new build against it and confirm nothing was lost
DATABASE_URL="postgresql://postgres@127.0.0.1:5433/payroll_upgrade" \
  python -c "from fastapi.testclient import TestClient; from app.main import app; \
             TestClient(app).__enter__()"
```

Confirm afterwards that row counts in `salary_register_rows`, `employee_records`
and `findings` are unchanged, and that the new columns exist and are `NULL`.

### 1.4 Frontend

```bash
cd frontend
npm ci
npm run lint                  # must print no warnings or errors
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run build   # must compile
npm audit --omit=dev          # record findings; see Phase 5.3
```

### 1.5 Full stack, locally

```bash
docker compose -f docker/docker-compose.yml up --build
# frontend http://localhost:3000   API http://localhost:8000   Postgres :5432
```

Sign up, create an entity, and walk one month end to end (Phase 3.4). If it
cannot be done locally it will not be done on a deployed host.

### Gate 1 — do not proceed unless

- [ ] `ruff` clean, `bandit` clean, suite green on SQLite
- [ ] Suite green on PostgreSQL with the same count
- [ ] Upgrade against a populated database loses nothing
- [ ] Frontend lints and builds
- [ ] One month walked end to end in Docker

---

## Phase 2 — Staging

Staging exists so that the first time you see a deployed environment is not the
day a client is watching.

### 2.1 Provision

```
Render → New → Blueprint → connect the repo → confirm render.yaml
```

Provisions `payroll-saas-api` (Docker, health check `/api/health`) and
`payroll-saas-db` (PostgreSQL 16). Override for staging:

| Variable | Staging value |
|---|---|
| `ENV` | `staging` |
| `ALLOW_ANONYMOUS_API` | `false` |
| `JWT_SECRET` | generated — **different from production** |
| `CORS_ORIGINS` | your staging Vercel URL |
| `DATABASE_URL` | injected by Render |

Frontend on Vercel, root directory `frontend`, with `BACKEND_URL` pointing at
the staging API. **`BACKEND_URL` has no `NEXT_PUBLIC_` prefix** — it is read
server-side by the proxy route and must never reach the browser.

### 2.2 Confirm the deployment is actually up

```bash
curl -s https://<staging-api>/api/health
# {"success":true,"data":{"status":"ok","version":"1.1.0","env":"staging"},"error":null}

curl -s https://<staging-frontend>/api/proxy/api/health
# the same envelope, proving the Next.js proxy reaches the API
```

If the second fails with `proxy_misconfigured`, `BACKEND_URL` is unset on Vercel.

### Gate 2

- [ ] Both health checks return the envelope, with `env` reading `staging`
- [ ] Render logs show migrations ran once and the app started
- [ ] No CORS error in the browser console on the login page

---

## Phase 3 — The test plan

Seven layers. Each catches something the others cannot. Run all of them against
staging before any client data is involved.

### 3.1 Layer 1 — Automated suite (already run in Phase 1)

Re-run against the deployed commit, not your working tree:

```bash
git checkout <the commit you deployed> && pytest -q tests
```

### 3.2 Layer 2 — API smoke on the deployed host

Checks that the wiring survived deployment — not the logic, which Layer 1 covers.

```bash
API=https://<staging-api>

curl -s $API/api/health | jq .success                     # true
curl -s -o /dev/null -w "%{http_code}\n" $API/api/reports  # 401 — auth required

# signup → login → authenticated read
TOKEN=$(curl -s -X POST $API/api/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"qa@yourdomain.in","password":"Strong-Pwd-123","company_name":"QA Co"}' \
  | jq -r .data.access_token)

curl -s $API/api/reports -H "Authorization: Bearer $TOKEN" | jq '.data.reports | length'
# 11
```

**Every no-argument GET must not return 500.** The suite asserts this over the
whole OpenAPI surface; this layer confirms it survived the deploy. Three shipped
endpoints once returned 500 on every call, so this check is not theoretical.

### 3.3 Layer 3 — Tenant isolation

The check that matters most on a multi-client deployment.

1. Create two organisations, A and B, each with an entity and a register.
2. As A, call any endpoint with B's entity id in `X-Entity-Id`.
3. **Expected: HTTP 404, not 403.** A 403 confirms the entity exists; 404 does
   not, so the header cannot be used to enumerate entity ids.
4. Confirm A's reports contain no row belonging to B.

### 3.4 Layer 4 — UAT with a planted-defect pack

**This is the layer that decides whether the product works.** Load a register
you have deliberately broken and confirm each defect is caught, at the right
severity, with the right employee named — and that nobody else is flagged.

Build the pack from `backend/tests/test_regression_end_to_end.py`, which
generates exactly this scenario: ten employees, three months, two states, three
departments, a joiner, a leaver, and six planted defects.

| # | Plant this | Expect | Severity |
|---|---|---|---|
| U1 | An employee with PF wages and `pf_employee = 0` | `STAT-001` | CRITICAL |
| U2 | `pt = 0` where the state slab is due | `STAT-008` | not INFO |
| U3 | No PAN and `tds = 0` | `TDS-001` | CRITICAL |
| U4 | An attendance file where days do not sum to the month | `ATT-010` | refused before storage |
| U5 | Attendance stating 30 paid days with 4 lost | `ATT-011` | CRITICAL |
| U6 | Three LOP days, full month paid | `ATT-020` with a rupee value | CRITICAL |
| U7 | Overtime hours, no overtime component | `ATT-022` | WARNING |
| U8 | A bank row paying an account not on the master | `bank.account_differs_from_master` | high |
| U9 | An employee due pay with no bank line | `bank.not_in_file` | high |
| U10 | A bank row for a code on no register | `bank.not_in_register` | high |
| U11 | A JV template with the TDS payable rule deleted | `jv.measure_unmapped`, out of balance by exactly the TDS | high |

**Then check the negative case, which matters just as much.** In the same run:

- [ ] No employee other than the intended one is flagged by that rule
- [ ] A workspace with no attendance register produces **no** attendance
      findings — silence, not a screen of false positives
- [ ] A month with no bank file reports **unreconciled**, not clean

### 3.5 Layer 5 — Cross-module agreement

For one month, in the UI, confirm the same number in three places:

| Check | Where |
|---|---|
| Voucher debits == dashboard CTC | `/reconciliation/jv` vs `/cost` |
| Debits − credits == 0 | `/reconciliation/jv` |
| Headcount identical | `/payroll/history`, `/cost`, `/reconciliation/jv` |
| Department split sums to the total | `/cost`, switch grouping |

If any pair disagrees, **stop**. This is the product's core promise and the
suite asserts all four; a disagreement on a deployed host means a configuration
or data problem that will surface in front of the client.

### 3.6 Layer 6 — Security

| # | Check | Expected |
|---|---|---|
| S1 | `curl $API/api/reports` with no token | 401 |
| S2 | `ALLOW_ANONYMOUS_API` in production | forced `false` by `config.py` |
| S3 | `JWT_SECRET` is not the shipped default | app logs a loud warning if it is |
| S4 | Response headers | `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` present |
| S5 | A viewer-role login | employee identity masked as `EMP-XXXXXX` |
| S6 | An analyst calling `/api/bi/pay-equity` | 403 — owner/manager only |
| S7 | Pay equity on an entity that has not enabled it | 403 with the reason |
| S8 | TLS | valid certificate on both hosts, HTTP redirects to HTTPS |
| S9 | Repository scan | no secret, key or employee datum committed |

Run `/security-review` on the release branch before cutover.

### 3.7 Layer 7 — Performance

Against staging, with a register representative of your largest client:

| Check | Target |
|---|---|
| Validate 5,000 employees | under 60s |
| Cost dashboard, 24 months | under 3s |
| Bank file, 10,000 rows | under 30s to parse and store |
| 11 reports generated back to back | no timeout, no memory error |

Render's starter plan is a single small instance. If any of these misses,
increase the plan before blaming the code.

### Gate 3 — the go/no-go

- [ ] Layers 1–7 all pass
- [ ] Every U1–U11 defect caught with the right employee and severity
- [ ] Negative cases confirm no false positives and honest silence
- [ ] Cross-module identities hold on a deployed host
- [ ] D6 statutory verification signed off by the client's expert

---

## Phase 4 — Parallel run

**The real acceptance test, and the one nothing else replaces.**

Run one complete real month through Peopleopslab *alongside* the client's
existing process, changing nothing in their process. Two to three cycles is
better than one.

### 4.1 Procedure

1. Client uploads the real employee master, CTC, attendance and register for a
   **closed** month — one already paid, so nothing is at risk.
2. Run validation, cost analysis and both reconciliations.
3. Sit with the client's payroll lead and walk every finding.
4. Classify each one:

| Verdict | Meaning | Action |
|---|---|---|
| **True positive** | A real defect the client did not know about | This is the product's value. Record it |
| **Known and accepted** | Real, and the client has a reason | Waive on the record |
| **Configuration error** | The rule is right, the setup was wrong | Fix the config, re-run |
| **False positive** | The product is wrong | **Stop. Fix the code before go-live** |

### 4.2 Exit criteria

- [ ] Zero unexplained false positives
- [ ] At least one true positive the client did not already know about — if
      there are none across two months, the product is not earning its place
      and that is worth knowing before you charge for it
- [ ] The client's payroll lead states in writing that the findings are sound
- [ ] Cost dashboard totals match the client's own management accounts
- [ ] The JV balances and the client's accountant accepts the mapping

### 4.3 What a failed parallel run looks like

A false positive is not a tuning exercise. If the product reports an
overpayment that did not happen, fix the rule — a client who is shown one
fabricated finding will not trust the ninety that are real.

---

## Phase 5 — Production cutover

### 5.1 Before the switch

| # | Step |
|---|---|
| P1 | Generate a **fresh** `JWT_SECRET` (`openssl rand -hex 48`), different from staging |
| P2 | Set `ENV=production` and confirm `ALLOW_ANONYMOUS_API=false` |
| P3 | `CORS_ORIGINS` = exactly your production hosts, no wildcard |
| P4 | Set `BACKEND_URL` on Vercel production to the production API |
| P5 | Confirm the Postgres plan is paid, not free — free tiers expire and delete |
| P6 | Confirm automated daily backups are on, and **restore one** to prove it works |
| P7 | Point DNS: apex A `76.76.21.21`, `www` CNAME `cname.vercel-dns.com`, `api` CNAME the Render host |
| P8 | Wait for TLS to go green on all three |
| P9 | Tag the release: `git tag -a v1.0.0 -m "First production release" && git push --tags` |

### 5.2 The switch

```bash
API=https://api.peopleopslab.in
curl -s $API/api/health | jq '.data.env'      # "production"
curl -s https://peopleopslab.in/api/proxy/api/health | jq .success   # true
```

Then repeat Layer 2 and Layer 6 against production. Create the client's real
organisation and entity. Do **not** import client data until both pass.

### 5.3 Accept the known gaps, in writing

These do not block a controlled first go-live, but you are accepting them:

| Gap | Risk you are taking | Mitigate by |
|---|---|---|
| No retention/deletion policy engine | DPDP erasure requests need manual handling | Document a manual procedure with an owner and an SLA |
| No rate limiting on auth | Credential stuffing | Cloudflare or Vercel rate rules in front of `/api/auth/*` |
| `xlsx` npm advisory | Frontend dependency finding | Confirm server-side `openpyxl` is the generation path |
| Bank presets unverified | A wrong column mapping | The test-against-a-file step is mandatory, not optional |
| Python pinned to 3.12 (`passlib`/`crypt`) | Cannot upgrade runtime | Replace `passlib` before 3.13 |

---

## Phase 6 — After go-live

### 6.1 Day one

- [ ] Watch Render logs for the first real upload end to end
- [ ] Confirm the audit trail recorded it with the right actor
- [ ] Generate all 11 reports and open each one
- [ ] Confirm the first bank reconciliation matches what the client expects

### 6.2 First week

| Cadence | Check |
|---|---|
| Daily | Error rate in logs; any 500 is an incident, not noise |
| Daily | Backup completed |
| Weekly | Database size and connection count against plan limits |
| Weekly | Findings the client marked false positive — each is a bug |

### 6.3 Monthly, with the payroll cycle

- [ ] Statutory rates still current — a Budget or state notification changes them
- [ ] Re-run the suite on the deployed commit
- [ ] Review waivers approaching expiry
- [ ] Confirm sign-off completed for the prior month

---

## Phase 7 — Rollback

Decide the trigger in advance so nobody debates it during an incident.

**Roll back if:** data is being written wrongly, any tenant can see another's
data, or authentication fails. **Do not roll back for:** a cosmetic defect, a
single noisy rule (suppress it instead), or a slow report.

| Layer | How | Time |
|---|---|---|
| Frontend | Vercel → Deployments → previous → Promote to Production | under 1 min |
| API | Render → Deploys → last green → Redeploy | 2–5 min |
| Database | Render → Postgres → Backups → Restore | 10–30 min, **loses data since the backup** |

A schema change cannot be rolled back by redeploying the API — the columns are
already there. New columns are additive and nullable, so an older build ignores
them; this is why migrations never drop or rename in a release.

---

## Appendix A — Environment variables

### Backend

| Variable | Required | Production value |
|---|---|---|
| `ENV` | yes | `production` |
| `DATABASE_URL` | yes | injected by Render; `postgres://` is normalised automatically |
| `JWT_SECRET` | yes | `openssl rand -hex 48` — unique per environment |
| `CORS_ORIGINS` | yes | exact hosts, comma-separated, no wildcard |
| `ALLOW_ANONYMOUS_API` | yes | `false` |
| `CORS_ORIGIN_REGEX` | no | preview deployments only |
| `PORT` | platform | injected |
| `WEB_CONCURRENCY` | no | `2` to start |

### Frontend

| Variable | Required | Notes |
|---|---|---|
| `BACKEND_URL` | yes | **server-only** — no `NEXT_PUBLIC_` prefix |
| `NEXT_PUBLIC_API_URL` | optional | direct fallback path |
| `NEXT_PUBLIC_USE_API_RELAY` | optional | `1` forces the proxy on any host |

---

## Appendix B — Quick reference

```bash
# full local verification
cd backend && ruff check app tests && bandit -c pyproject.toml -r app && pytest -q tests
cd ../frontend && npm run lint && npm run build

# production health
curl -s https://api.peopleopslab.in/api/health | jq .
curl -s https://peopleopslab.in/api/proxy/api/health | jq .

# rotate the JWT secret (invalidates every session — announce first)
openssl rand -hex 48
```

---

## Appendix C — The shortest honest summary

| Phase | Proves | Blocking |
|---|---|---|
| 1 Pre-flight | The code is sound on both databases | yes |
| 2 Staging | It deploys and the wiring holds | yes |
| 3 Test plan | It catches real defects and does not invent any | yes |
| 4 Parallel run | It works on **this client's** real data | yes |
| 5 Cutover | Production is configured and secured | yes |
| 6 Monitoring | It keeps working | ongoing |
| 7 Rollback | You can undo it | rehearse once |

Phases 1–3 can be done in a few days. **Phase 4 takes at least one payroll
cycle and cannot be compressed** — a month is a month. Plan for four to six
weeks from this document to a client's first production month.

### D6 — the verification worksheet

The sign-off is an artefact, not a conversation. Generate it:

```bash
cd backend
python tools/statutory_worksheet.py statutory_verification_worksheet.xlsx
```

It reads the values out of the application rather than a typed copy, so the
worksheet cannot disagree with what the software computes with. 164 values
across four tabs: income tax for the current FY, PF and ESIC, PT for 22 states,
LWF for 15.

Give it to the reviewer with one instruction — fill every yellow cell. The
Sign-off tab counts Y, N and unchecked per tab on its own and will not read
"D6 SATISFIED" until nothing is left unchecked.

Re-run it whenever a Budget lands or a state amends a schedule. The tool is the
same; only the numbers it extracts change.

Two things it deliberately leaves out, both stated on its first tab:

* **Minimum wages** — per state, per skill category, revised about twice a year,
  and held as tenant data rather than a shipped default. They need their own
  review. A missing rate already surfaces as a finding rather than a pass, so an
  unmaintained table reads as unverified instead of clean.
* **The Labour Codes** — everything here assumes the Acts currently in force. If
  the Codes have commenced, the definition of "wages" moves and PF basis,
  gratuity and bonus move with it. That is a redesign, not a rate correction.
