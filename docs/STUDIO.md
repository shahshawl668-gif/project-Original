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
| Header mapping | Alias tables per file type; register mapping profiles (`import_profiles`) | Reused by the API. **Built** a versioned mapping editor (phase 2) that runs before them |
| Lineage | Register uploads frozen with SHA-256 and row numbers; nothing on master/attendance/CTC records | **Added** a `lineage` column (run, source system, record id, batch, time) |
| Findings lifecycle, approvals, sign-off | Complete (PR #37) | Reused. Keys may acknowledge/comment/assign, never waive/resolve/publish/sign |
| BI | Dashboard query service with data basis (PR #37) | Reused as `/bi/query` |
| Audit | Append-only, per entity and org | Reused for every key, account and machine action |
| Secret storage for outbound credentials | None | **Built** (phase 2): Fernet under `STUDIO_SECRET_KEY`, refused in production without it |
| Outbound HTTP / SSRF protection | None | **Built** (phase 2): allow-list, HTTPS, public addresses only, pinned connect, no redirects |
| Webhooks, event outbox | None | **Built** (phase 2) |
| Workflows, in-product notifications | None | **Built** (phase 3) |
| Sandboxed scripting | None; the formula evaluator is a whitelisted AST, in-process | **Not enabled**, by decision — see §7. A developer workspace tests the low-code evaluators instead |
| Environments / releases | None; every company is one environment | **Built** (phase 4): companies marked development / test / production; releases of configuration only |
| "Payroll Control Centre" | No page by that name. Month close (`/reconciliation`) and Validations (`/payroll/validation`) together do its job | **Linked** (phase 3): both show the month's integration picture |

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

## 3. Phase 2 — shipped: connections, mapping, sync, reconciliation, webhooks

### Secrets (`services/studio/secrets.py`)

Connection credentials, OAuth tokens and webhook signing secrets are sealed
with Fernet under `STUDIO_SECRET_KEY`. A comma-separated list rotates: the first
key encrypts, every key decrypts, and `reencrypt` moves old ciphertext to the
new key. **In production an unset key refuses to store any secret**
(`SecretStoreUnavailable`, shown to the person as "set STUDIO_SECRET_KEY") —
the design's condition, kept. Outside production a key is derived from
`JWT_SECRET` so development works without setup. Nothing that leaves the
service is plaintext: screens and API responses get `••••1234` masks, logs get
redacted text, and decrypted values go only to the outbound client and the
signer. Losing the key makes stored secrets unreadable; the connections are
then re-entered — nothing else is lost.

### Outbound requests (`services/studio/egress.py`)

Every call Studio makes — a connection's test, sample or sync, an OAuth token
exchange, a webhook delivery — goes through one function with three locks:

1. the host is on the **organisation's allow-list** (`studio_allowed_hosts`,
   exact or `*.example.com`), kept by an owner or manager on the Connections
   page;
2. **HTTPS**;
3. every address the host resolves to is **globally routable**. Loopback,
   private, carrier-grade NAT, multicast and reserved ranges are refused;
   link-local — which includes the cloud metadata address `169.254.169.254` —
   is refused *always*, even in development.

The resolution happens inside the connection (`GuardedBackend`): the socket
connects to the address that was checked, while TLS still verifies the
certificate against the host name, so DNS rebinding between check and connect
does not get through. Redirects are reported, never followed. Responses are
capped at `STUDIO_HTTP_MAX_RESPONSE_MB` and `STUDIO_HTTP_TIMEOUT_SECONDS`.
`STUDIO_ALLOW_PRIVATE_DESTINATIONS` relaxes locks 2 and 3 (not link-local) for
local development against a mock system; production forces it off.

### Connections (`services/studio/connections.py`)

A connection records name, system kind (HRMS, attendance, finance, payroll,
file transfer, other), provider (`rest` or `file`), environment, base URL,
auth method and credentials, timezone, description, and its health: last test,
last success, last failure and the reason.

| Auth method | Holds | Notes |
|---|---|---|
| `none` | — | |
| `api_key_header` | header name, key | |
| `bearer` | token | |
| `basic` | username, password | For an integration or API user the other system issued — the form says never to use a person's own password |
| `oauth2_client_credentials` | client id and secret, token URL, scope | Token fetched and cached until it expires |
| `oauth2_authorization_code` | client id and secret, authorise and token URLs, scope | **Connect** sends the person to the provider with `state` (single use, ten minutes, `studio_oauth_states`) and a PKCE S256 challenge; the code comes back to `/studio/connections/oauth`, is exchanged once, and the tokens are sealed and refreshed when they expire. Nobody types a password into Studio |

Credentials are replaced, never shown: rotating one is entering the new value.

**The generic REST connector** reads an authenticated GET returning a JSON
list, or an object holding one at a stated path, paged by page number, offset
or cursor, with an optional "modified since" parameter. **The file connector**
is for systems that export files: the file is imported through a published
mapping on the mapping page. **No provider-specific connector was built.** None
of the providers' documented APIs or test tenants were available to this
project; a connector written against guesses would fail in ways nobody could
test. Adding one is a new `provider` value and a fetch function, with its
tests run against that provider's sandbox.

### Streams and sync (`services/studio/sync.py`)

A **stream** is one source object on a connection: path, the record list's
location, pagination, the data type it feeds, the mapping profile (or a pinned
version), match key, full or incremental with the cursor parameter and field,
deletion handling, import options, retry limit, and a schedule — every hour,
day at a time, or week on a weekday at a time, in a named timezone (default
Asia/Kolkata). The worker loop starts due streams (`schedule_due`); **Sync
now** starts one by hand. One live run per stream: a second start returns the
live run.

The behaviour, per the brief's list:

| Question | Answer |
|---|---|
| Source of truth, direction | The other system, for the fields it sends. Inbound only; Studio never writes back to a source |
| Matching | Employee id (plus effective date for CTC), leading zeros kept |
| Upsert | `upsert` (default: update matches, add new, leave the rest) or `replace` |
| Duplicates | Identical repeats skipped; conflicting records for one employee all rejected, with each one's source row |
| Conflicts and manual correction | Rejected records wait on the run: correct at source and resend, or fix configuration here — a new mapping version, say — and **Retry rejected records**. Only they are resent, read with the mapping in force now (a version pinned on the stream stays pinned), and the retry always **adds**: even after a `replace` run it never makes the retried few the whole version |
| Full or incremental | Incremental sends the last committed watermark as the stream's "modified since" parameter; full fetches everything |
| Deletion | Never inferred from absence. `ignore` (default); `report` — after a full sync, employees stored here but absent from the fetch are listed on the run as `missing_in_source`, nothing removed; `replace` — the fetch becomes the version, only for a stream declared complete. Deactivation is the exit date the source sends |
| Checkpoint | Advanced **in the same transaction** that stores the records and finishes the run (`ingest_records(on_committed=…)`), and only if the run stored something. A crash before that commit leaves the old checkpoint; the replay then reads as `unchanged`, never as duplicates |
| Retries | Connection errors, timeouts, 5xx and 429 retry with backoff (30 s × 2ⁿ) up to the stream's limit; a refusal (bad credentials, host not allowed, 4xx) fails at once with what to do |
| Reconciliation | The run's counts: received → accepted / rejected / skipped → created / updated / unchanged, both identities checked on the run page |

A sync run is a `studio_runs` row like an API import (`kind = "sync"`), in the
same run history, with the connection, stream, mapping version and cursor
recorded on it.

### Mapping (`services/studio/mapping.py`, `profiles.py`)

A mapping version is a **specification — data, never code**. Per product
field: source (a dotted path into nested JSON), aliases tried in order, type
(`text`, `id`, `number`, `currency`, `date`, `boolean`, `attendance_codes`),
required, default, accepted date formats, lookup table with what to do when
nothing matches (reject, keep, blank), a formula, conditional cases with an
`else`, and zero-padding for ids. Fields not in the product's list go to
`extra.<name>` — the client-specific fields — and `keep_unmapped` carries
source fields across unchanged instead of dropping them.

* **Normalisation**: dates in stated formats and ISO; numbers with Indian or
  international grouping, `₹`/`Rs`/`INR` stripped, brackets as negatives;
  yes/no flags; attendance codes mapped to the product's categories. Ids are
  read as text, so `00123` stays `00123`.
* **Absent is not zero.** An empty or missing source produces no field. A
  default applies only where the mapping states one. `"0"` is zero.
* **Nothing is silently discarded.** An unreadable value, an unmatched lookup
  set to reject, or a missing required field is an error naming the target
  and source field and the source row, and the record is rejected, not
  trimmed.
* **Formulas** use the same whitelisted AST evaluator as validation rules —
  arithmetic and a few pure functions over the record's own numbers. No
  `eval`, no `exec`, no attribute access.
* **It transforms; it never judges.** No finding, rate or payroll rule lives
  in a mapping. Whether a basic salary is right is the validation engine's
  question.

**Versions.** A profile (`key`) has numbered versions: draft (editable) →
published (immutable) → retired. Publishing needs an owner or manager and,
where the approval policy turns on *Studio mappings need an independent
publisher*, someone other than the author. The version a run uses is the one
pinned on the stream or the newest published version effective on the run
date, and the run records which — so the runs that used version 3 always used
exactly version 3. **Preview** applies a draft or published version to sample
records (from a file, the connection, or pasted JSON) and returns every
output and every error with its source row. **Compare** lists field-by-field
differences between any two versions.

**Lineage** on each stored record gains the mapping version, beside the
system, object, source record id, batch, run and time recorded since phase 1.

### Events and webhooks (`services/studio/events.py`, `webhooks.py`)

**Outbox.** Business changes write a `studio_events` row in the same
transaction as the change: `import.completed`, `validation.completed`,
`validation.failed` (final failure only, not a retried attempt),
`finding.state_changed`, `period.submitted`, `period.signed_off`,
`period.reopened`, and `webhook.test`. A rolled-back change takes its event
with it; a committed one is never lost to a crash, because the worker fans
events out afterwards. Payloads carry ids, states and counts — never pay
figures or identity data; a subscriber reads detail through the integration
API with a key scoped for it. Payload version `2026-10-01`.

**Outbound.** A subscription names a URL (through the same egress guard), the
events it wants, and a retry limit (default 8). Each event gets a unique
event id; each attempt at each subscription is a delivery with its own id.
Signature: `X-PeopleOpsLab-Signature: t=<unix>,v1=<hex>`, the hex being
HMAC-SHA256 over `"<t>.<raw body>"`. Rotating the secret signs with both old
and new for an overlap of up to 168 hours. Retries back off 1 min, 5 min,
30 min, 2 h, 6 h, 12 h, 24 h; after the last attempt the delivery joins the
failed queue, where it can be replayed singly or all at once. The delivery log
keeps status, attempts, response code and time, and a redacted error.

**Delivery is at least once, and said so.** A delivery whose 2xx answer was
lost is sent again, and a replay re-sends the same event id. Consumers
de-duplicate on `X-PeopleOpsLab-Event-Id`. Exactly once is not offered,
because it cannot honestly be promised over HTTP.

**Inbound.** An endpoint (`POST /api/integration/v1/hooks/{token}`) imports
records of one data type, optionally through a published mapping. It verifies
the same signature scheme with its own secret, refuses timestamps more than
five minutes off, and records each sender's event id once
(`studio_inbound_receipts`, unique): a repeat answers `200 {"duplicate":
true}` and starts nothing. Its runs are ordinary imports with trigger
`webhook`, acting as the endpoint's own machine identity.

### Performance — a sync at 8,000

8,000 synthetic employees fetched from a mock HRMS over HTTP (17 pages of 500),
read through a published five-field mapping (padding, date format, lookup),
checked and stored, against a running API on PostgreSQL 16, same machine as
the phase-1 benchmark:

| Step | Time | Counts |
|---|---|---|
| First sync | 4.1 s | 8,000 received → 8,000 created |
| Same sync again (replay) | 2.1 s | 8,000 received → 8,000 unchanged, none duplicated |

The API process (worker thread included) went from 183 MB to 277 MB during the
first sync and 277 MB during the replay. A sync holds the whole fetch in memory
before storing it, so memory grows with the stream's size; streams far larger
than a month's master should be split, or the worker moved to its own service.
Validation of the month is the expensive step, measured under phase 1.

### What changed from the design

* **Retry backoff for runs.** Phase 1 retried a failed import at once; phase 2
  retries after 30 s × 2ⁿ⁻¹ (claimed by `queued_at <= now`), because a sync
  retried instantly against a provider that is down only fails again.
* **Sampling reads one page**, not the whole source — the first build walked
  every page, which on a large HRMS is a full sync to fill a preview.
* **Extra fields are kept apart.** A mapping's `extra.cost_code` was at first
  folded into the record, where the import's header aliases read it as
  `cost_center`. Extras now travel as their own key and land in
  `record.extra` untouched.
* **Retries add, and use today's mapping.** Found in the browser walk: a retry
  copied its run's options, so retrying the rejected rows of a `replace`
  import would have made those few rows the whole master or attendance
  register — removing everything the first run accepted. The phase-1 API
  import had the same flaw; phase 1 had not reached `main`, so no deployment
  ever ran it. A retry is now always `upsert`. It also pinned the
  first run's mapping version, so "fix the mapping, then retry" did not work;
  it now reads with the version in force and records which. Both are tested
  (`test_retry_uses_the_corrected_mapping_and_never_replaces`).
* **Sync runs show their rejections.** The run page listed rejected records
  only for API imports; sync runs showed the count but not the records.
* **Mapping rejections keep the source record id.** A record the mapping
  rejected lost its `record_id` in `source_ref`; the source's own id now comes
  from the mapping's record-id field.
* **Approval policy** gained one setting,
  `studio_publish_requires_independent_approver`, on the Team page beside the
  others.

## 4. Phase 3 — shipped: workflows, notifications, month-close links

### Workflows (`services/studio/workflows.py`)

A workflow is **trigger → conditions → actions, as data** — a small fixed
vocabulary, not a programming language. It is edited as a working copy and
put in force by publishing (owner or manager; someone other than the last
editor where the approval policy says so). Publishing re-checks every stream,
webhook and person the definition names. A run keeps a copy of the definition
it started with, and the version, so an edit never changes a run under way.

| Triggers | |
|---|---|
| `manual` | Run now, from the builder, optionally for a named month |
| `schedule` | Hour, day or week, at a time, in a named time zone (the stream scheduler's rules) |
| `import.completed` | An import or sync finished |
| `inputs.ready` | *Derived:* after every import or sync, the month is checked; fires when every required input (register, master, attendance, CTC, prior register) is present — once per distinct set of inputs |
| `validation.completed`, `validation.failed` | A month's validation finished, or failed for good |
| `finding.state_changed` | A finding was acknowledged, waived, resolved or reopened |
| `period.submitted`, `period.signed_off`, `period.reopened` | The month's approval moved |
| `inbound.received` | A signed inbound webhook call was accepted |

**Conditions** test the event's data (`data.counts.rejected gt 0`,
`data.object_type eq salary_register`). A value that cannot be compared makes
the condition false, never true by accident.

| Actions | What it calls |
|---|---|
| `sync` — fetch and import | `sync.start` on a stream; the stream's published mapping is applied there. Waits for the run. Rejections make the step a warning, or a failure if the step says so |
| `check_readiness` | The same input counts the validation digests use; fails naming what is missing |
| `start_validation` | `validation_jobs.submit_for_period`, the screens' own queue. Waits for the job; can fail on critical findings |
| `assign_findings` | `issues.assign` on the month's active findings of chosen severities — owner and due date only |
| `notify` | An in-product notification (`studio_notifications`) to roles or named people with access |
| `report` | A notification linking to validation results, Month close, the findings worklist or the run. A link, not an attachment: the page checks each reader's own access |
| `webhook` | A signed `workflow.message` event to one webhook, through the outbox |

**What no workflow can do.** Sign, submit or approve a month; waive or
resolve a finding; publish a rule; approve anything. A definition naming one
of these is refused when saved, with the reason. Sign-off keeps its
approval controls because no path to it exists here.

**"Apply mapping" is not a separate step.** Mapping without storing is only a
preview, and the builder's preview already exists on the mapping page. In a
workflow, mapping happens inside the `sync` step, with the stream's published
(or pinned) version, recorded on the run.

**Execution.** A workflow run is a `studio_runs` row of kind `workflow`,
drained by the same worker. Steps run in order. A step that starts work
records the child and requeues the run five seconds later — a long validation
never holds a worker thread. Each step has a timeout (default 60 min) and
retries (0–3, backing off 30 s × 2ⁿ); the whole run has a timeout (default
120 min). A failed step runs the failure branch (only notify, report or
webhook) and fails the run naming the step. **Cancel** stops the run and the
sync or validation it is waiting on. Statuses: queued, running, completed,
partially completed (a step ended in a warning), failed, cancelled.

**Duplicates and loops.** Every start is written to `studio_workflow_fires`
under a key unique per workflow — `event:<id>`, `schedule:<slot>`,
`ready:<month>:<input digests>`, `manual:<uuid>` — so an event fanned out twice
starts one run. Events carry `causation`: work a workflow starts is stamped
with its id and depth, a workflow never fires on an event its own run caused,
chains stop at depth 3, and a workflow starts at most `max_runs_per_hour` runs
(default 20). Each refusal is kept as the workflow's *last skip*, with its
reason, on the list and the builder.

**Who a run acts as.** Automatic runs act as the person who published the
workflow, and only while that person can still manage the company; otherwise
the start is skipped with the reason, and publishing again fixes it.

**Dry run.** Evaluates the conditions against a sample event, resolves each
step (month, stream, recipients, rendered titles, whether readiness would
pass now) and returns the plan. Nothing is started, stored or sent.

### Notifications

In-product only — nothing leaves the product. A bell in the header shows the
reader's own notifications for the company in view; marking read affects only
the reader's own. Templates fill `{{period}}`, `{{workflow}}`,
`{{counts.rejected}}`, `{{event.data…}}` with values; nothing is evaluated.

### Month close and Validations

There is no page called "Payroll Control Centre"; Month close
(`/reconciliation`) and Validations (`/payroll/validation`, with its results) do its job. Both now
show **Data from your systems** for the month: the latest import or sync per
input with its counts, anything rejected or failed ("these records are not in
the month until they are fixed"), failing connections, and workflows that ran —
each linking to its run, which links to its evidence. For people without Studio
access the panel is not shown.

### What changed from the design

* **No savepoints.** The first build guarded duplicate starts with a
  savepoint; SQLite's driver does not honour savepoints, and a fire record was
  committed without its run, blocking that trigger for good. Now the key is
  checked, then inserted, with the unique constraint as the backstop — a race
  fails the whole fan-out batch, which is retried and then sees the key.
* **"Awaiting approval"** is a run status the product lists, but no workflow
  run enters it: nothing a workflow does needs a person's approval, because
  everything that would is outside its vocabulary.

## 5. Phase 4 — shipped: developer workspace, environments, releases

### Developer workspace (`services/studio/devtools.py`, `/studio/developer`)

Low-code only, with the product's own evaluators — nothing new that could
behave differently in production:

* **Formula:** the whitelisted AST evaluator (`formula_eval`, the one rules,
  KPIs and mappings use) against sample rows, read exactly as a mapping reads
  them (`₹18,000` is 18000; nested fields joined with `_`). Each row gives its
  value or its reason; a blank field is absent and the formula does not run —
  never a zero. **Explain** states what it reads and calls, and says it in
  words ("the smaller of (pf_wage, 15000) times 0.12"). Anything the evaluator
  refuses is refused here with its reason: `__import__`, attribute access,
  strings, lists, lambdas, keyword arguments.
* **Conditions:** the workflow condition test against sample events, with
  what each field actually held. Not comparable is false.
* **Lookup:** the mapping's lookup against sample values, with the chosen
  unmatched policy.
* **Reference:** functions, operators, what is never allowed, the limits.

### Scripting — disabled, and the page says why

§7 is the position; the workspace shows it, with what would have to be true
first. No `eval`, no `exec`, no restricted-Python pretending to be a sandbox.

### Environments (`studio_company_environments`)

**An environment is a company.** Each is marked development, test or
production (the default — a company holding real payroll stays production).
Payroll data, connections, credentials and webhook secrets all belong to a
company, so separation needs no second product, only a rule about what may
cross between companies: configuration, upward, by release.

### Releases (`services/studio/releases.py`, `/studio/releases`)

| Step | Rule |
|---|---|
| Draft | From a development or test company to a higher one in the same organisation, by an owner or manager of both. Items: mapping versions in force (by key) and published workflow definitions (by name). Anything else is refused: *never data, connections or secrets* |
| Impact preview | Per item: create, update or unchanged in the target; the field-level diff (mappings) or trigger/step diff (workflows); whether *this exact version* was run in the source — the synthetic test run — with its status; blocking problems (a mapping the target's configuration rejects, a stream, webhook or person the workflow names that the target lacks) and warnings (never tried in the source; its last run failed; a new workflow arrives disabled) |
| Submit | Only with no blocking problem |
| Approve or reject | An owner or manager of the target **other than the author** — always, not only when a policy says so. Rejection needs a reason |
| Promote | By an owner or manager of the target, re-checked against the target as it is now, in one transaction. A mapping gains a **new** published version; a workflow a **new** version, its stream, webhook and people re-resolved by name in the target; a new workflow arrives **disabled** for a person to enable. What each item replaced is recorded |
| Roll back | A new release, inside the target, restoring what was replaced — again as new versions (or retiring a version / disabling a workflow the release created). Approved by someone other than its author, like any release |

**History is not rewritten.** Promotion and rollback only add versions and
change a workflow's status. Every earlier mapping version stays as it was, and
every run keeps naming exactly the version it used. Every step is in both
companies' audit trails.

**Not carried, by design:** records, registers, runs, findings, sign-offs,
connections, credentials, webhook secrets, inbound endpoints. Set connections
and webhooks up in each environment, under the same names; that is where each
environment's own secrets live.

### What changed from the design

* **Environments are companies, not a flag on each object.** Phase 1 put an
  `environment` label on service accounts, keys, connections and runs; that
  label stays, but separation is enforced by company, because that is where
  data and secrets already live and are already isolated.
* **Independent approval is unconditional for releases.** Mappings and
  workflows follow the organisation's policy; a release — which changes
  production for everyone — always needs a second person. A one-person
  organisation cannot promote; it says so.
* **Connections and webhooks are not promoted.** Promoting them would mean
  either copying secrets between environments or creating half-configured
  objects in production. Both are worse than setting them up twice.

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

### Administrator — pulling from a system (phase 2)

1. **Studio → Connections → Allowed destinations.** Add the other system's
   API host (`api.your-hrms.example`). Nothing else is reachable.
2. **New connection.** Name, kind, environment, base URL, auth method. Enter
   credentials the other system issued for integration — or, for OAuth
   authorisation code, save and press **Connect** to sign in at the provider.
   Press **Test**: it authenticates, reads one page and records health.
3. **Add a stream**: the object's path, where the list sits in the response,
   pagination, the data type it feeds, and a schedule if it should run alone.
4. **Studio → Data mapping → New profile** for that data type. **Sample from
   the connection** (or a file, or pasted JSON), **Suggest from sample**, then
   correct each field — source, type, format, lookup, default. **Preview**:
   every error names the source row and field. Fix until it is clean, then
   **Publish**. (If your policy needs an independent publisher, a second owner
   or manager publishes.)
5. Back on the connection, pick the mapping on the stream and **Sync now**.
6. Open the run from **Recent runs**. Check both identities; read each
   rejected record's row, field and reason. Fix at source, or fix the mapping
   (new version, publish) and press **Retry rejected records**.
7. When a register sync or import carries `validate`, the run links to the
   validation; from there, Issues and Month close as usual. The run page shows
   the system, object, batch and mapping version every stored record carries.
8. **Studio → Webhooks** to tell other systems when things happen: add the
   receiver's host to the allow-list, create the webhook, copy the secret once,
   **Send test**, and watch the delivery log.

### Administrator — automating the month (phase 3)

1. **Studio → Workflows → New workflow.** Start from *Validate when inputs are
   ready*.
2. In the builder, check the trigger's required inputs, then the steps:
   validate the month, assign its critical findings to the person who works
   them, notify the payroll team. Add a failure step that notifies you.
3. **Dry run** with the sample event: it shows each step resolved — the month,
   who would be notified, whether readiness would pass now. Nothing happens.
4. **Publish** (an owner or manager; a second one if your policy requires
   independence). From now on, the first import that completes the month's
   inputs starts it — once per set of inputs.
5. Watch **Runs** on the builder, or the bell in the header. A failed run
   names its step; the step links to the sync or validation it started.
6. On **Month close**, *Data from your systems* shows how each input arrived
   and anything that still needs fixing before you approve.

### Administrator — test, then release (phase 4)

1. Create a company for testing (Companies → add), and in **Studio → Versions
   & releases** mark it **test**. Give it synthetic data only.
2. Build there: the connection (to the provider's test system, with test
   credentials), the mapping, the workflow. Sync and run them. Use the
   **Developer workspace** to check formulas and lookups on sample rows.
3. Set up the production company's own connection and webhooks under the
   **same names**, with production credentials.
4. From the test company, **New release**: tick the mapping and workflow,
   choose the production company. Read the impact: every change, whether each
   version was tried in test, and anything blocking.
5. **Submit.** A second owner or manager approves it, then **Promote**. New
   workflows arrive disabled — enable them in production when ready.
6. If something is wrong, open the release and **Draft a rollback**; it goes
   through the same approval and restores the previous versions as new ones.

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

Receiving PeopleOpsLab webhooks — verify, then de-duplicate:

```python
import hashlib, hmac, time

def verify(secret: str, header: str, raw_body: bytes, tolerance: int = 300) -> bool:
    parts = [p.split("=", 1) for p in header.split(",")]
    t = next(v for k, v in parts if k == "t")
    if abs(time.time() - int(t)) > tolerance:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, v) for k, v in parts if k == "v1")

# then: if the X-PeopleOpsLab-Event-Id was seen before, answer 200 and stop.
```

Sending to an inbound endpoint — the same scheme, your endpoint's secret:

```bash
BODY='{"batch_id":"ATT-2026-06","period_month":"2026-06-01","records":[{"employee_id":"00123","present_days":"22"}]}'
T=$(date +%s)
SIG=$(printf '%s.%s' "$T" "$BODY" | openssl dgst -sha256 -hmac "$INBOUND_SECRET" -hex | cut -d' ' -f2)
curl -sS -X POST "$BASE/hooks/<endpoint token>" \
  -H "Content-Type: application/json" \
  -H "X-PeopleOpsLab-Signature: t=$T,v1=$SIG" \
  -H "X-PeopleOpsLab-Event-Id: $(uuidgen)" -d "$BODY"
# → 202 {"data": {"duplicate": false, "run_id": "…"}}; the same event id again → 200, duplicate: true
```

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

**The blocker, precisely.** Enabling scripting needs a separate execution
service — a sandbox host or a per-run isolated container platform — which is
new, paid infrastructure. It was not created: that needs the owner's
authorisation and a choice of provider. Until then the Developer workspace
shows scripting as disabled, with this reason, rather than a switch that does
nothing.

## 8. Rollback

Every phase-1 schema change is additive: five new tables via `create_all` and
one nullable `lineage` JSON column on three tables (`record_import_lineage`).
Rolling back is redeploying the previous release; the old code ignores the new
tables and the new column. Keys issued under phase 1 simply stop working when
the integration API is absent.

Phase 2 is additive too: ten new tables via `create_all` (`studio_allowed_hosts`,
`studio_connections`, `studio_streams`, `studio_mappings`, `studio_oauth_states`,
`studio_events`, `studio_webhooks`, `studio_deliveries`,
`studio_inbound_endpoints`, `studio_inbound_receipts`), one new key in the
approval policy JSON (unknown keys are ignored by older code), and no change to
an existing column. Two new dependencies, `httpx` and `cryptography`. Rolling
back leaves the tables unread: syncs stop, webhooks stop being sent, inbound
endpoints answer 404. Events written while rolled back are not written at all,
so on roll-forward nothing from that window is delivered — stated, not hidden.
Before rolling forward in production, **set `STUDIO_SECRET_KEY`**; without it
connections and webhooks cannot store their secrets and say so.

Phase 3 adds three tables (`studio_workflows`, `studio_workflow_fires`,
`studio_notifications`) and changes no column. Rolling back stops workflows;
the runs they left stay readable in run history, as rows of a kind the older
code does not claim.

Phase 4 adds two tables (`studio_company_environments`, `studio_releases`) and
changes no column. Rolling back leaves every company production as before and
releases unreadable; everything a release promoted stays as the ordinary
mapping and workflow versions it created.
