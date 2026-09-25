# Peopleopslab

Indian payroll validation, cost intelligence and reconciliation.

**It never runs payroll.** It checks the register another system produced. That
independence is the product's commercial claim, not a limitation — an HRMS
auditing its own output is marking its own homework. Nothing in this repository
should ever pay anyone or alter a payslip.

---

## Keep the documentation current with the code

Every change that alters what the product *is* updates its documentation in the
same commit. Not afterwards, not in a follow-up — the same commit, because a
follow-up that never comes is how documentation rots.

**What counts as such a change, and what it obliges:**

| You changed | Also update |
|---|---|
| A page, route, or who can reach it | `docs/handbook.html` route table |
| An admin or support endpoint | `docs/handbook.html` admin API table |
| A setting in `app/config.py` | `docs/handbook.html` environment table |
| A statutory default or rate | Re-run `backend/tools/statutory_worksheet.py`; the sign-off is void |
| Anything a user sees and a manual shows | The manual, and re-shoot its screenshot |
| The architecture, data flow, or a module's job | `docs/handbook.html` structure and blueprint |
| A design doc's plan, once built | That doc, marked with what shipped and what changed |

`python docs/tools/check_docs_current.py` enforces the mechanical half of this —
routes, admin endpoints, settings, health endpoints and roles. **CI runs it, so
a PR that adds a route without documenting it fails.** It deliberately does not
check prose: whether an explanation is still true is a judgement no script
makes. That half is yours.

When a design document turns out to be wrong during implementation, correct the
document and say what changed. `docs/BACKGROUND_JOBS.md` §6 is the worked
example: the design's chunking would have fabricated tens of thousands of
findings, and the doc now says so rather than quietly describing something the
code does not do.

---

## Documentation map

| File | What it is |
|---|---|
| `docs/handbook.html` | Operations handbook — structure, blueprint, routes, access, testing, links. The file is the source; the published page is a copy of it |
| `docs/CLIENT_USER_MANUAL.md` | For the client's payroll team |
| `docs/IMPLEMENTATION_MANUAL.md` | For whoever sets up a new client |
| `docs/ADMIN_MANUAL.md` | For the team running the platform |
| `docs/GO_LIVE.md` | Internal. Six phases, three gates, and the D6 statutory sign-off |
| `docs/BACKGROUND_JOBS.md` | Design and current state of the validation queue |
| `docs/DATABASE_MIGRATION.md` | Tested procedure for moving to another Postgres host |

Build outputs, all gitignored, all regenerated rather than edited:

```bash
python docs/tools/build_manuals.py         # docs/pdf/ — sendable manuals
python backend/tools/statutory_worksheet.py  # the D6 sign-off workbook
```

---

## Working in this codebase

**Run the tests on both dialects.** SQLite ignores foreign keys by default and
has no `FOR UPDATE SKIP LOCKED`; both differences have hidden real bugs here.

```bash
cd backend
python -m pytest tests/ -q                                   # SQLite
DATABASE_URL=postgresql+psycopg2://… python -m pytest tests/ -q   # PostgreSQL
```

Use `pytest tests/`, not bare `pytest` — the backend root holds live-server
scripts that collection would try to import and fail on.

**Two principles the code already holds to. Keep them.**

*Silence is never a pass.* A month with no bank file is reported unreconciled,
not clean. A missing minimum-wage rate is a finding that says so. Reporting
"nothing disagreed" when nothing was checked is the most dangerous answer a
compliance tool can give.

*Absent and zero are different claims.* A register that never mentioned ESI
must not read like one that deducted nothing.

**Statutory rates are configuration, not code.** No rate is hardcoded in an
engine. A Budget change edits a tenant's config or `tax_year_defaults.py`; it
does not need a release.

**Platform admin grants no access to client payroll.** Break-glass support
grants are the only path: time-boxed, read-only, never unmasking, and written
to the *client's* audit trail. Nothing may widen access as a side effect.

---

## Conventions

- Responses are the envelope `{success, data, error}`.
- Tenant-scoped endpoints resolve the entity from `X-Entity-Id`. An entity the
  caller cannot reach returns **404, not 403** — which entities exist is not
  something to confirm to a stranger.
- Migrations are hand-rolled, idempotent and dialect-aware, in
  `app/migrations.py`. New tables arrive via `create_all`.
- Never commit a credential, a rate table nobody verified, or a screenshot
  showing a name the product no longer uses.
