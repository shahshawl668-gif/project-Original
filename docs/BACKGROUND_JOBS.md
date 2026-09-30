# Design — validation as a background job

A design that has now been built. The sections below are the original design;
this first section says what shipped and where it differs. Where the two
disagree, this section is right.

---

## 0. What shipped (October 2026) — and what changed from the design

The product's own journey now runs through the queue: the upload page enqueues,
`/payroll/validation` shows progress, `/payroll/results?run=` reads the result
from the server. Nothing is kept in browser storage any more.

**Four deliberate departures from the design below:**

1. **The worker validates the frozen upload, not `salary_register_rows`.** §2
   says the worker reads the stored register. Building it showed the stored
   register is *lossy by design*: it keeps what the cost model reads and drops
   PAN, UAN, ESI number, dates of joining/leaving, payment mode and the other
   identity fields validation checks. A worker reading it would have silently
   skipped those checks. So every upload is also written, unchanged, to
   `register_uploads` — file SHA-256, mapping, revision, and the parsed rows
   gzip-compressed — and the job validates that. It is also what makes a run
   reproducible after the month is re-uploaded.

2. **Runs are kept, not replaced.** The design did not cover history; the code
   it was built on deleted the previous run when a month was re-validated. Now
   the previous run is marked `superseded` and points at its replacement, a
   partial unique index allows one `current` run per period, and runs can be
   compared (`/api/validation/runs/compare`). Each run records per-input digests
   and the effective configuration, so staleness names the input that changed.

3. **Endpoints live under `/api/validation/…`**, not `/api/payroll/validation-jobs`
   (§8): `POST /jobs`, `GET /jobs[/{id}]`, `POST /jobs/{id}/cancel`,
   `POST /jobs/{id}/retry`, `GET /runs[/{id}]`, `/runs/{id}/employees`,
   `/runs/{id}/findings`, `/runs/{id}/export.xlsx`, `/runs/compare`,
   `/periods/{period}/status`, `/uploads`. A duplicate enqueue returns the live
   job with `already_queued: true` rather than an error, so a second tab joins it.

4. **The synchronous `/api/payroll/validate` was kept for API callers**
   (§12.3 said remove it). The release-gate runner and integrations post rows
   directly. It records runs through the same `record_run`, so it preserves
   history too; the product's pages no longer call it. **Since 30 September
   2026 it no longer validates a large register inline:** above
   `SYNC_VALIDATE_MAX_EMPLOYEES` (1,000) a request with a payroll month is
   stored as an upload and queued — `202` with the job to follow — and one
   without a month is refused with `413`. §1's table is why: past a few
   thousand rows the request outlives the gateway and the work is discarded.
   `test_validate_endpoint.py` proves the queued run finds exactly what the
   inline one does.

**Also added:** stages (`queued → loading → validating → recording`), cancel of
a running job (the worker checks at each progress point and rolls back — a
cancelled attempt writes nothing), permanent failures that do not retry
(no components, missing columns, no upload) with a message written for the
person, and transient failures that retry up to `max_attempts` with the raw
exception kept only for operators.

**`VALIDATION_WORKER_ENABLED` now defaults to `true`** (§7 said off). With the
journey on the queue, a server with no worker would leave every validation
waiting, which is a silent failure. The progress page warns when it is off.

**Measured** — see §15.

---

## 1. The problem, measured

`POST /api/payroll/validate` runs the whole validation inside the HTTP request.
There is no job queue anywhere in the backend — no Celery, no RQ, no
`BackgroundTasks`.

```python
@router.post("/validate")
def validate_payroll(body: ValidateRequest, ...):
    rows, findings_summary = validate_employees(db, entity, comps, body.employees, ...)
    ...
    return ok(payload)
```

For ten employees that is instant. For ten thousand it evaluates roughly ninety
rules per employee, in Python, while a browser and at least one proxy wait.

**What breaks, in the order it breaks:**

| Employees | What happens |
|---|---|
| ~500 | Slow but fine |
| ~2,000 | Users think it has hung; some retry, doubling the load |
| ~5,000 | Gateway timeout. The work continues server-side and the result is discarded |
| ~10,000 | Request body alone is tens of MB before any work starts |

The last row matters most: the client currently posts `body.employees` — the
entire parsed register — back to the server. The register **is already stored**
by `/api/payroll/upload`. We are paying to move the same data twice and
validating whatever the client sent rather than what was recorded.

**A bigger server does not fix any of this.** The request still times out.

---

## 2. The shape of the fix

Three decisions, each with a reason.

### The job references the register; it does not carry it

```
POST /api/payroll/validate
    { register_id, period_month, run_type, ... }     ← small, always
```

The worker reads the rows from `salary_register_rows`. This removes the large
payload, makes the job row tiny, makes retry trivial — a retry re-reads the same
rows rather than needing a payload nobody kept — and closes the gap where
validation ran against something other than the stored register.

### The queue is PostgreSQL, not Redis

`SELECT … FOR UPDATE SKIP LOCKED` is a correct queue primitive and has been for
a decade. Using it means:

- **No new service, no new bill, no new thing to secure.** Redis would be a
  third piece of infrastructure holding payroll-adjacent data.
- **No dual-write problem.** The job's state and the findings it writes commit
  in the same transaction. With Redis they cannot, so a crash between the two
  leaves a job marked done with nothing written.

Redis earns its place at thousands of jobs per minute. This is tens per day,
concentrated in one week a month.

### One path, not two

No "small registers stay synchronous, large ones go async". Branching on size
means two code paths, and the rarely-taken one is the one nobody tests — which
is exactly the path a 10,000-employee client takes on their first day.

Validation always enqueues. Small jobs simply finish before the first poll.

---

## 3. Schema

```sql
CREATE TABLE validation_jobs (
    id              UUID PRIMARY KEY,
    entity_id       UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    register_id     UUID          REFERENCES salary_registers(id) ON DELETE CASCADE,

    period_month    DATE NOT NULL,
    run_type        VARCHAR(32) NOT NULL,
    params          JSON NOT NULL,          -- effective_month_from/to, as_of_date

    state           VARCHAR(16) NOT NULL,   -- queued running succeeded failed cancelled
    employee_total  INTEGER NOT NULL DEFAULT 0,
    employee_done   INTEGER NOT NULL DEFAULT 0,

    run_id          UUID REFERENCES validation_runs(id) ON DELETE SET NULL,
    error           TEXT,

    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,

    queued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    heartbeat_at    TIMESTAMPTZ,            -- lease; a dead worker's job is reclaimed
    locked_by       VARCHAR(64)             -- which worker holds it
);

CREATE INDEX ix_validation_jobs_claimable ON validation_jobs (state, queued_at)
    WHERE state IN ('queued', 'running');

-- A double-click must not run the month twice.
CREATE UNIQUE INDEX ux_validation_jobs_active ON validation_jobs (entity_id, period_month)
    WHERE state IN ('queued', 'running');
```

`run_id` is the handover: when the job succeeds it points at the `ValidationRun`
the existing code already writes. **Results are not stored on the job.** The
findings register is already the system of record; duplicating it would create
two truths.

---

## 4. States

```
   queued ──claim──> running ──┬──> succeeded
      ▲                        ├──> failed      (attempts exhausted)
      └────requeue─────────────┘
                               └──> cancelled   (user asked)

   lease expired (heartbeat older than 2 min) ──> back to queued, attempts += 1
```

Terminal states are final. A job that failed is never silently retried later —
someone decides.

---

## 5. Claiming work

```sql
UPDATE validation_jobs
SET state = 'running',
    locked_by = :worker_id,
    started_at = COALESCE(started_at, now()),
    heartbeat_at = now(),
    attempts = attempts + 1
WHERE id = (
    SELECT id FROM validation_jobs
    WHERE state = 'queued'
       OR (state = 'running' AND heartbeat_at < now() - INTERVAL '2 minutes')
    ORDER BY queued_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING *;
```

`SKIP LOCKED` is what lets several workers share one table without blocking each
other. The second clause is crash recovery: a worker killed mid-job stops
heartbeating, and its job returns to the pool.

**Fairness, when it matters:** during close week one large client could occupy
every worker. The `ORDER BY` becomes round-robin over `entity_id` at that point
— a change to one clause, not to the design. Not worth building yet.

---

## 6. The worker loop

> **Corrected during implementation.** This section originally chunked the
> validation *call* — 200 employees at a time, committing between chunks. That
> is wrong for this codebase, and building it would have shipped a serious bug.
>
> `validate_employees` compares the register against the whole set: findings
> such as "this person is on the attendance register but on no payslip" come
> from `unmatched_findings`, computed by asking who the register does *not*
> contain. Validating 200 at a time would report the other 9,800 as missing from
> the register — on a 10,000-employee month, tens of thousands of fabricated
> findings.
>
> What shipped instead: `validate_employees` takes an `on_progress` callback and
> the worker renews its lease from inside the single call. Same progress, same
> live lease, and what gets reported does not change.

```python
def run_once(db, worker) -> bool:
    job = claim(db, worker)             # the SQL above
    if job is None:
        return False
    db.commit()

    try:
        run_id = execute(db, job)       # validates, records the run
    except Exception as exc:
        db.rollback()
        job = db.get(ValidationJob, job_id)   # the rollback detached it
        jobs.fail(db, job, error=f"{type(exc).__name__}: {exc}")
        db.commit()
        return True

    jobs.succeed(db, job, run_id=run_id)
    db.commit()
    return True
```

and inside `execute`:

```python
def progress(done: int) -> None:
    # Renewing the lease is the point; the number is the bonus. Its own
    # transaction, so a later failure does not roll progress back.
    jobs.heartbeat(db, job, done=done)
    db.commit()

rows, summary = validate_employees(..., on_progress=progress)
```

`PROGRESS_EVERY = 100`: small enough that a lease renewed on each call never
expires mid-register, large enough that the callback is not what makes
validation slow.

### The claim had to become atomic on both dialects

`FOR UPDATE SKIP LOCKED` protects the claim on PostgreSQL. SQLite has no such
clause, and the original code assumed that was fine because SQLite has one
writer. It is not fine: two threads can `SELECT` the same id and both proceed to
run the job. A concurrency test caught it immediately.

The claim now does a guarded `UPDATE ... WHERE id = :id AND (still claimable)`
and checks `rowcount`. Whichever update lands second matches no rows and that
worker backs off. On PostgreSQL the row lock already made this safe, so the
guard costs nothing — and the queue is now correct on the dialect the tests
actually run on, which was the whole argument for testing on both.

---

## 7. Where the worker runs

**Phase 1 — a thread in the API container.** Started at app boot, guarded by an
env var:

```
VALIDATION_WORKER_ENABLED=true
VALIDATION_WORKER_CONCURRENCY=1
```

No new service, no new cost, works on the current plan. Good to a few hundred
employees per minute.

**Phase 2 — a separate Render Worker service.** Same code, different entrypoint
(`python -m app.worker`), `VALIDATION_WORKER_ENABLED=false` on the API. Scale
workers during close week and back down after.

The design makes that a configuration change, not a rewrite, which is the whole
point of putting the queue in the database rather than in the web process.

---

## 8. API

| Method | Path | Returns |
|---|---|---|
| `POST` | `/api/payroll/validate` | `202` · `{ job_id, state: "queued" }` |
| `GET` | `/api/payroll/validation-jobs/{id}` | state, `employee_done`/`employee_total`, `run_id`, `error` |
| `GET` | `/api/payroll/validation-jobs` | recent jobs for the entity |
| `POST` | `/api/payroll/validation-jobs/{id}/cancel` | cancels if not terminal |

Results keep coming from the existing findings endpoints, keyed by `run_id`.
Nothing new to learn and nothing duplicated.

Every job endpoint is entity-scoped through the existing dependencies. A job id
from another organisation returns **404, not 403** — which entities exist is not
something this endpoint should confirm.

---

## 9. Frontend

The upload page's step 3 becomes a progress step:

```
POST /validate → { job_id }
  ↓ poll GET /validation-jobs/{job_id} every 2s, backing off to 5s after 30s
  ↓ show "Validated 4,200 of 10,000 employees"
  ↓ on succeeded → navigate to results for run_id
  ↓ on failed    → show error, offer retry
```

Polling, not WebSockets. One connection per active job for a few minutes, a few
times a month, is not worth a second transport.

**The banner already exists.** `SlowRequestNotice` handles "this is taking a
while"; here it is replaced by a real number, which is strictly better.

---

## 10. Failure modes this must survive

| Failure | Behaviour |
|---|---|
| Worker killed mid-job (deploy, OOM) | Lease expires after 2 min; another worker reclaims; `attempts += 1` |
| Deploy during close week | Same. This is why `BackgroundTasks` is unusable — a deploy kills it silently |
| Same register submitted twice | Unique partial index refuses the second while one is active |
| Register deleted mid-job | `ON DELETE CASCADE` removes the job; worker's next commit finds it gone and stops |
| Rule engine raises on one employee | Whole job fails with the error recorded. Findings are all-or-nothing per run — a half-validated month must never look complete |
| Job queued, no worker running | Stays `queued`. An alert on queue depth is Phase 2 |
| Database connection lost | Transaction rolls back; job returns to `queued` on lease expiry |

---

## 11. Deliberately not doing

- **`BackgroundTasks`** — dies with the process, no retry, no visibility, and a
  Render deploy kills it mid-run with no record it ever started.
- **Celery / Redis** — a third piece of infrastructure for tens of jobs a day.
- **WebSockets** — polling is adequate and has no reconnection semantics to get
  wrong.
- **Storing results on the job row** — the findings register is the record.
- **Per-entity worker pools** — premature. The `ORDER BY` handles it when it
  becomes real.

---

## 12. Rollout

Four changes, each shippable and reversible.

**1. Schema and service, no behaviour change.** `validation_jobs`, the claim
query, `run_once`. Tested directly: enqueue, claim, complete, expire a lease,
reclaim, exhaust attempts. Nothing calls it yet.

**2. Worker thread behind a flag**, default off. ✅ **Shipped.**
`VALIDATION_WORKER_ENABLED` (default `false`) and
`VALIDATION_WORKER_CONCURRENCY` (default 1); `python -m app.worker` runs the
same loop as its own process for step 4.

Watched through with a real register before merging: 5,000 employees, validated
in 25s with progress visible throughout, the HTTP request never waiting. Then a
job was abandoned mid-run the way a deploy abandons one — a live worker
reclaimed it after the lease expired, `attempts` went to 2, and it finished.

**3. Switch the endpoint.** ✅ **Shipped, differently** — see §0. The product
enqueues through `POST /api/validation/jobs` and polls; the synchronous
`/api/payroll/validate` stays for API callers and records history the same way,
and queues any register above `SYNC_VALIDATE_MAX_EMPLOYEES` (§0 item 4).
Both paths are under test.

**4. Separate worker service**, when close-week load justifies it. Configuration
only.

---

## 13. Tests

The suite currently calls `/validate` and asserts on findings. Those tests
should keep asserting the same things — a helper that enqueues, runs the worker
inline, and returns the run keeps them honest without rewriting them.

New tests worth having:

- Two workers, one job → exactly one runs it (`SKIP LOCKED`)
- A job whose lease expired is reclaimed and `attempts` increments
- `attempts >= max_attempts` → `failed`, not an endless loop
- A second submission for the same entity and period while one is active → refused
- A job id from another organisation → 404
- Progress: `employee_done` increases and never exceeds `employee_total`

---

## 14. What this buys

Rough, and worth measuring rather than trusting:

| | Today | After |
|---|---|---|
| Largest register | ~2,000 before timeouts | Limited by patience, not HTTP |
| Concurrent validations | As many as the web pool allows, each blocking a worker | Queued; workers set the rate |
| Deploy during a run | Run lost, silently | Reclaimed and finished |
| User sees | A spinner | "4,200 of 10,000" |

It also unblocks the same pattern for the two other jobs that will grow: Excel
report generation and bank reconciliation over large files.

**This is the change that decides whether a 20,000-employee client is a sale or
an incident.** It is a few days of work, and it is much cheaper to do before
there are clients than after.

---

## 15. Measured (October 2026)

`backend/tools/benchmark_validation.py` drives synthetic registers
(`backend/tools/synthetic_payroll.py`) through the real API and worker on
PostgreSQL 16, in-process, on a 4-vCPU Xeon container with 16 GB RAM — **much
larger than a Render free instance (0.1 CPU, 512 MB)**, so treat these as the
application's cost, not production latency. Each run is checked against planted
defects whose expected findings are computed independently of the engine
(PF under-deducted, ESIC over-deducted, paid days that do not add up): all
found exactly, no misses, no false positives, at every size.

| Step | 8,000 before | 8,000 after | 20,000 after | 8,000 coverage release | 20,000 coverage release |
|---|---|---|---|---|---|
| Register upload (parse, store, freeze) | 4.0 s | 4.5 s | 10.5 s | 4.1 s | 9.8 s |
| Worker: validate + record run | 87.4 s | 35.4 s | 106.3 s | 37.3 s | 110.6 s |
| Worker: re-run of the same month | 86.3 s | 35.6 s | 101.4 s | 36.7 s | 109.2 s |
| Process RSS during validation (start → peak) | 265 → 410 MB | 265 → 393 MB | 457 → 753 MB | 259 → 389 MB | 463 → 762 MB |
| Run summary (incl. staleness check) | 2.40 s | 0.71 s | 1.73 s | 0.86 s | 1.70 s |
| Page of 50 employees / findings | 0.07 s | 0.07 s | 0.08 s | 0.05 s | 0.06 s |
| Employee detail | 0.08 s | 0.09 s | 0.13 s | 0.08 s | 0.13 s |
| Excel export of the run | 3.7 s | 3.9 s | 8.3 s | 3.7 s | 8.5 s |
| Compare two runs | 1.0 s | 0.9 s | 2.6 s | 1.1 s | 2.4 s |
| Findings in the run | 11,384 | 11,384 | 28,444 | 11,384 | 28,444 |

The **coverage release** adds, inside every validation, minimum wage and a
verdict on all 97 registered checks for every employee (handbook blueprint,
stage 5). Its first build held those verdicts as 97 small dicts
per employee and measured **40.5 s and 265 → 512 MB at 8,000** — enough to put
an 8,000-employee client at risk on a 512 MB instance. Verdicts are now stored
compactly (passes as a list of ids, reasons shared) and expanded only when one
employee is read; the columns above are that build. Validation costs about 5%
more time than before and no more memory.

**Memory is the constraint, not time.** Validating 20,000 employees adds about
300 MB to the process (the whole register, its results and its findings are held
until the run is written in one transaction — which is what keeps a failed run
from ever being half-written). A Render free or Starter instance has 512 MB, so
**a 20,000-employee register is at real risk of an out-of-memory kill there**;
the job would be retried and fail the same way. 8,000 employees (+130 MB) fits.
For clients above roughly 10,000 employees, run the API (or a separate
`python -m app.worker`) on an instance with at least 2 GB.

"Before" is the first working version, which made about four database round
trips per employee (a CTC lookup, and three queries for the full-month pay
baseline). Batching those into three queries per run cut validation time by
about 60% with identical answers — `tests/test_full_month_references.py`
proves the batched loader equal to the per-employee one on every branch.

Storage per run: frozen upload ≈ 0.4 MB at 8,000 and 1.0 MB at 20,000;
per-employee results ≈ 14.7 MB and 36.7 MB since the coverage release (about
1.8 KB per employee, compressed — it was 1 KB before per-check verdicts were
kept), plus the finding rows above. Runs are never deleted, so budget roughly 2 MB per 1,000
employees per validation. A free 1 GB database holds on the order of fifty
8,000-employee validations; a paid plan is needed before onboarding several
large clients.

The figures are regenerated by running the benchmark; do not edit them by
hand. The 20,000 re-run shared the CPU with a frontend build for part of its
duration.

