# Design — validation as a background job

A design, not an implementation. It describes the change, the schema, the
failure modes it has to survive, and the order to build it in.

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

```python
def run_once(db, worker_id) -> bool:
    job = claim(db, worker_id)          # the SQL above
    if job is None:
        return False

    try:
        rows = load_register_rows(db, job.register_id)
        job.employee_total = len(rows)

        results = []
        for i, chunk in enumerate(chunked(rows, 200)):
            results.extend(validate_chunk(db, job, chunk))
            job.employee_done = min((i + 1) * 200, job.employee_total)
            job.heartbeat_at = now()
            db.commit()                 # progress is visible, lease is renewed

        run = finding_store.record_run(db, ...)   # unchanged
        job.run_id, job.state, job.finished_at = run.id, "succeeded", now()
        db.commit()
    except Exception as exc:
        db.rollback()
        job.error = str(exc)[:2000]
        job.state = "failed" if job.attempts >= job.max_attempts else "queued"
        db.commit()
        raise
    return True
```

The chunked commit does three jobs at once: progress the UI can show, a renewed
lease, and a bounded transaction. One transaction spanning 10,000 employees
would hold locks for minutes and bloat WAL.

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

**2. Worker thread behind a flag**, default off. Turn it on in a non-production
environment and watch a real register through it.

**3. Switch the endpoint.** `/validate` enqueues and returns 202; the frontend
polls. The old synchronous path goes in the same PR — leaving both means the
async path is the untested one.

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
