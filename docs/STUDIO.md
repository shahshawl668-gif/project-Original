# PeopleOps Studio — design and current state

PeopleOps Studio is the part of PeopleOpsLab where a client's other systems are
connected to it: the HRMS that owns the employee master, the attendance system,
the payroll system that produces the register, the finance system that wants
the results. It is built on the product's own services — the same parsers, the
same validation queue, the same findings, approvals and audit trail — so an
integration can never do something a screen could not, and never judge payroll
differently from how the product does.

**Studio never runs payroll.** It moves data in, starts validation, and reads
results. The independence claim holds: the register is still checked by an
engine that did not produce it.

This document is kept current with the code, phase by phase, per `CLAUDE.md`.
Where the design changed during building, the change is stated here.

---

## 1. What existed and what was missing (assessed 29 Sep 2026, at `cb2f0b6`)

| Capability | Before Studio | Verdict |
|---|---|---|
| Authentication | JWT sessions for people only (`deps.get_current_user`), four org roles, entity access, break-glass support | Reused for Studio screens. No machine identity existed |
| API keys / machine identities | None | **Built** (phase 1) |
| Versioned public API | `/api/v1` was an alias of the product API, which changes with the screens | **Built** a separate app at `/api/integration/v1` |
| Idempotency, rate limits, request-size limits | None (only a sign-in throttle message in the frontend) | **Built** |
| Correlation ids | `X-Request-Id` generated and logged, not returned in errors or stored | **Extended**: echoed, in every integration error, stored on runs |
| Background jobs | `validation_jobs` queue, `SKIP LOCKED`, leases, retries (PR #37) | **Reused**: the same worker loop drains Studio runs |
| Imports (master, CTC, attendance, register) | Upload screens only, with the commit logic inside each router. Duplicate rows silently kept-first; unreadable dates read as absent; unreadable CTC amounts read as **0** | **Refactored** into `services/ingest.py` and `services/register_ingest.py`, shared by screens and API. The API rejects what the screens used to absorb |
| Header mapping | Alias tables per file type; register mapping profiles (`import_profiles`) | Reused by the API. A versioned mapping editor is phase 2 |
| Lineage | Register uploads frozen with SHA-256 and row numbers; nothing on master/attendance/CTC records | **Added** a `lineage` column (run, source system, record id, batch, time) |
| Findings lifecycle, approvals, sign-off | Complete (PR #37) | Reused. Keys may acknowledge/comment/assign, never waive/resolve/publish/sign |
| BI | Dashboard query service with data basis (PR #37) | Reused as `/bi/query` |
| Audit | Append-only, per entity and org | Reused for every key, account and machine action |
| Secret storage for outbound credentials | None | Phase 2 — needs an encryption key setting |
| Outbound HTTP / SSRF protection | None | Phase 2 |
| Webhooks, event outbox | None | Phase 2 |
| Workflows, in-product notifications | None | Phase 3 |
| Sandboxed scripting | None; the formula evaluator is a whitelisted AST, in-process | Phase 4 — see §7 |
| Environments / releases | None; every company is one environment | Phase 4 |
| "Payroll Control Centre" | No page by that name. Month close (`/reconciliation`) and Validations (`/payroll/validation`) together do its job | Phase 3 links Studio into those pages |

---

## 2. Phase 1 — shipped

### Machine identities

A **service account** (`studio_service_accounts`) belongs to one organisation
and names the companies it may act on and its scopes. It is created with a
shadow `users` row whose role is `machine`:

* no password any hash can match, no organisation membership, no company role;
* login and password reset refuse the role; a session token naming it is
  refused by `get_current_user`; it is never counted as a person (the
  "first signup becomes admin" check excludes it);
* so every human permission check fails for it. What it may do is exactly its
  scopes, checked by the integration API and nowhere else.

The person creating or editing an account must be an owner or manager of
**every** company it names — a key can never reach further than its maker.

### Keys

`pol_<live|test|dev>_<8 hex>_<secret>`. Stored as SHA-256 only
(`studio_credentials.secret_hash`); shown once; the prefix is kept in clear so
a key found in a log can be identified and revoked by someone who never saw
it. Every key expires (≤ 365 days, default 90). Rotation issues a new key and
keeps the old one alive for a stated overlap (0–168 h, default 24). Revocation
and disabling the account are immediate. A wrong secret learns nothing about
the key's state; only the holder of the real secret is told "revoked" or
"expired". `last_used_at` is written at most once a minute.

### The integration API

A separate FastAPI application mounted at `/api/integration/v1`, with its own
OpenAPI document and error catalogue (`app/integration/`). The contract —
authentication, scopes, idempotency, pagination, limits, error codes and the
deprecation policy — is the OpenAPI `info.description`, rendered in Studio →
API Centre. The endpoint list is in `docs/handbook.html#integration` and is
checked against the code in CI.

Scopes: `imports:write`, `imports:read`, `validation:run`, `validation:read`,
`results:employee`, `findings:write`, `config:read`, `config:propose`,
`bi:read`, `signoff:read`.

**What no key can do**, by design and by test: publish a rule, waive or
resolve a finding, submit or sign a month, change access. Those answer
`403 approval_required` or have no endpoint.

### Imports

`POST /imports/{kind}` validates the envelope, stages the records gzipped on a
`studio_runs` row and answers `202` with the run. The worker processes it:

1. Each record is read under canonical names first, so a batch mixing
   `emp_id` and `employee_id` reads every record the same way.
2. Row checks: not an object, no employee id, a date/number/flag that cannot
   be read → **rejected**, with row number, field and reason. Screens read
   such values as absent; a feed nobody watches must not.
3. The same parser the screens use (`workforce_parse`, `ctc_parse`,
   `payroll_parse`) reads the survivors — identifiers as text, so `00123`
   stays `00123`.
4. Duplicates: identical → second **skipped**; different → **all rejected**
   (which is right cannot be known).
5. The shared commit (`services/ingest.py`) stores them — `upsert` (default;
   untouched people stay) or `replace` — and reports created / updated /
   unchanged / removed.
6. A salary register is **all or nothing**: any rejected row fails the run
   and nothing is stored, because validation reads a register as a whole and
   a register missing rows would report those people unpaid. A configured
   component with no column is missing, not zero, unless the caller sends
   `allow_missing_components: true`. `validate: true` queues validation once
   stored.

Reconciliation identities, asserted in tests and shown on every run page:
`received = accepted + rejected + skipped`;
`accepted = created + updated + unchanged`.

`POST /imports/{kind}/check` runs the real checks and the real commit inside a
transaction that is rolled back, so its counts are the counts the import would
report. For a salary register the storing step is not rehearsed (it commits),
only the row and column checks.

Rejected records keep a gzip copy for `STUDIO_REJECTION_RETENTION_DAYS` (30);
the rejection itself stays with the run. The copy is shown only to owners and
managers in Studio, and each viewing is audited. The API never returns it.

**Changed from the first design:** the plan was to stage large batches in a
separate table. The run row carries the gzip payload instead and clears it on
completion — one row is the queue entry, the record and the evidence, as with
`validation_jobs`.

### Idempotency, limits, correlation

* `Idempotency-Key` is **required** on import, retry, validation start and rule
  proposal; optional on comments. Stored per caller for 24 h
  (`studio_idempotency`); the same key and body replays the first response with
  `Idempotent-Replayed: true`; a different body is `409 idempotency_key_reused`;
  a key still in flight is `409 idempotency_in_progress`. A request that fails
  frees its key.
* Rate limit: `INTEGRATION_RATE_LIMIT_PER_MINUTE` (120) per key, sliding
  window, `X-RateLimit-*` headers, `429` with `Retry-After`. **Counted per API
  process** — exact on today's single instance; with several, the effective
  ceiling multiplies. Moving the counter to the database is the change to make
  before scaling out.
* Body limit `INTEGRATION_MAX_REQUEST_MB` (25) → `413`; batch limit
  `INTEGRATION_MAX_RECORDS` (50,000).
* `X-Request-Id` is accepted, echoed, included in every error and stored on
  the runs a request creates. Unexpected errors are logged with any key-shaped
  string redacted to its prefix.

### Worker and recovery

`studio_runs` is claimed by the existing worker loop after validation jobs
(`FOR UPDATE SKIP LOCKED` on PostgreSQL). A run whose worker went silent for
120 s is reclaimed. An import commits in one transaction, so a crash leaves
nothing behind and the retry starts clean. Failures are retried up to three
attempts, then the run fails with category `internal` and a recommended
action. Housekeeping (expired idempotency keys, expired record copies) runs at
most every ten minutes.

### Screens

`/studio` (overview and setup checklist), `/studio/api` (accounts, keys,
documentation), `/studio/runs` and `/studio/runs/[id]` (run history,
reconciliation, rejections, retry). Sections not yet built are listed as "not
in this release" and are not links.

### Measured (8,000 employees, PostgreSQL 16, 4 vCPU, in-process)

`python tools/benchmark_studio.py --sizes 8000` sends a whole month through the
integration API as JSON and validates it. Synthetic data from
`tools/synthetic_payroll.py`; planted defects computed independently of the
engine. Measured 29 Sep 2026:

| Step | Records | Seconds |
|---|---|---|
| Master dry run (`/check`, rolled back) | 8,000 | 3.3 |
| Master submit (202) | 8,000 (2.5 MB JSON) | 0.2 |
| Master import | 8,000 created | 3.3 |
| Master resend, identical | 8,000 unchanged | 1.5 |
| Attendance import | 8,000 created | 2.3 |
| CTC history import | 16,000 created (two dates each) | 11.5 |
| Prior month register | 8,000 | 4.7 |
| Register submit / import | 8,000 (3.2 MB JSON) | 0.4 / 4.2 |
| Validation (worker) | 8,000 employees, 19,464 findings | 68.0 |
| Read every finding back, 500 a page | 19,464 | 6.0 |

* Every run satisfied both reconciliation identities; all three planted defect
  sets (STAT-001, STAT-006, LOP-001) were found exactly.
* **Found and fixed while measuring:** the CTC commit looked up each record's
  existing row with its own query. At 16,000 records that was 28.7 s; reading
  them once per 1,000 employees made it 11.5 s. The upload screen shares the
  commit, so it is faster too.
* **Validation takes longer than the upload-path benchmark** on the same
  machine the same day (58.8 s first run, 35.0 s re-run; that month has no CTC
  history). The difference is the CTC comparisons this month has data for.
* **Memory:** the benchmark process — client and server together — started at
  155 MB and peaked at 571 MB, during validation (from 405 MB). The server-side
  share is not separable in this in-process harness, but validation alone
  added about 166 MB. **An 8,000-employee month sent through the API is not
  shown to fit a 512 MB instance**; the free Render plan the product runs on is
  512 MB. Measure on the deployed instance, or move the worker to its own
  service (`python -m app.worker`, `docs/BACKGROUND_JOBS.md`) before relying on
  it at that size.

### Lineage

Every master, attendance and CTC record now carries `lineage`: channel (`api`
or `upload`), run id, source system, source object, batch id, source record
id, mapping version, who imported it and when. Excluded from validation input
digests — provenance is not data, and re-sending identical data through
another channel must not make a run stale.

---

## 3. Phase 2 — REST connections, mapping, sync, reconciliation, webhooks

Not yet built. Its dependencies, stated now so they are not discovered later:

* **Secret storage** needs an encryption key the API reads from the
  environment (Fernet). Without it set in production, storing connection
  credentials must be refused, not silently kept in clear.
* **Outbound requests** need an allowlist per organisation and a resolver that
  refuses private, loopback, link-local and metadata addresses — checked at
  connect time, not only at save time, to defeat DNS rebinding — and never
  follows redirects.
* **Provider-specific connectors** (a named HRMS) need that provider's
  documented API and test access. None is available to this project today, so
  phase 2 builds a generic REST connector and the file path only.

## 4. Phase 3 — workflows and the month-close links

Not yet built.

## 5. Phase 4 — developer workspace and releases

Not yet built. See §7 on scripting.

---

## 6. Quick starts

### Administrator (no developer needed)

1. **Studio → API Centre → New service account.** Name it after the system
   that will send data ("HRMS nightly feed"). Tick only the companies it
   feeds. Choose the preset *Send data and validate* unless it needs more.
2. **Copy the key when it is shown** and give it to whoever configures that
   system, through its secret store — not email. It is not shown again.
3. Ask them to send a first batch to `/imports/employee_master/check`: it
   stores nothing and reports what would happen.
4. **Studio → Run history.** Open the run. Check the two identities are
   green. For every rejected record, the row, field and reason say what to
   fix at the source.
5. Fix at the source and resend only those records, or — if the cause was
   configuration here (a missing component) — fix that and press **Retry
   rejected records**.
6. When a register arrives with `validate: true`, the run links to the
   validation results; from there, Issues and Month close work as usual.
7. **Rotate** keys before they expire (the overview warns 14 days ahead).
   **Revoke** at once if a key may have leaked.

### Developer

```bash
export POL_KEY='pol_live_1a2b3c4d_<your key>'      # from the API Centre, once
export BASE='https://www.peopleopslab.in/api/proxy/api/integration/v1'
export COMPANY='<company id from GET /me>'

curl -sS "$BASE/me" -H "Authorization: Bearer $POL_KEY"

curl -sS -X POST "$BASE/imports/employee_master/check" \
  -H "Authorization: Bearer $POL_KEY" -H "X-Company-Id: $COMPANY" \
  -H "Content-Type: application/json" \
  -d '{"effective_from":"2026-06-01","records":[{"employee_id":"00123","employee_name":"Asha Rao (synthetic)"}]}'

curl -sS -X POST "$BASE/imports/employee_master" \
  -H "Authorization: Bearer $POL_KEY" -H "X-Company-Id: $COMPANY" \
  -H "Idempotency-Key: $(uuidgen)" -H "Content-Type: application/json" \
  -d '{"batch_id":"HRMS-2026-06-01","effective_from":"2026-06-01","records":[…]}'
# → 202 {"data": {"id": "<run id>", "status": "queued", …}}

curl -sS "$BASE/imports/<run id>" -H "Authorization: Bearer $POL_KEY" -H "X-Company-Id: $COMPANY"
curl -sS "$BASE/imports/<run id>/rejections" -H "Authorization: Bearer $POL_KEY" -H "X-Company-Id: $COMPANY"
```

Rules for a well-behaved client:

* Generate one `Idempotency-Key` per logical batch and reuse it on every retry
  of that batch.
* Poll with backoff (2 s, 4 s, 8 s … up to 60 s) until the status is
  `completed`, `partially_completed`, `failed` or `cancelled`.
* Branch on `error.code`, log `error.request_id`, show `error.detail`.
* Ignore response fields you do not know; v1 only adds.
* Send `_source_record_id` on each record so a rejection points back at your
  own record.

---

## 7. Scripting and isolation — the position

Advanced scripting (arbitrary transformation code) is **not enabled** and will
not be until it can run with genuine isolation: outside the API process, with
no database connection, no filesystem or network beyond named capabilities, no
environment secrets, and CPU, memory, time and output limits. The production
host today is a single Render web service; it offers no sandbox runtime
(no gVisor/Firecracker, no separate unprivileged container per execution), and
a subprocess on the same host could open sockets and read the environment.
`eval`/`exec` are not a substitute. Low-code expressions — the whitelisted AST
evaluator already used by rules and KPIs — are the supported way to transform
and test values.

## 8. Rollback

Every phase-1 schema change is additive: five new tables via `create_all` and
one nullable `lineage` JSON column on three tables (`record_import_lineage`).
Rolling back is redeploying the previous release; the old code ignores the new
tables and the new column. Keys issued under phase 1 simply stop working when
the integration API is absent.
