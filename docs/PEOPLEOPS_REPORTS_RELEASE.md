# PeopleOps Reports Builder: release and rollback

The module name is **PeopleOps Reports**. **Report Centre** is the catalogue screen; **Report Builder** is the guided configuration screen.

This increment creates `report_definitions` and `report_definition_versions` through the application's existing `Base.metadata.create_all` startup path. Both tables are scoped to an organisation and company. Existing salary registers and reports are unchanged. The migration is additive and does not backfill or rewrite payroll data.

## Release checks

1. Run backend and frontend CI.
2. Confirm the new tables exist and that existing companies still open standard reports.
3. For a test company, preview payroll cost by department and reconcile the returned CTC control total to BI with the same period and filters.
4. Save a personal draft, update it, inspect versions, clone it, and verify another company receives a 404 for the report ID.
5. Confirm an analyst cannot publish or share, and a manager can.
6. Check mobile and desktop layout with synthetic payroll data before calling the new screen accepted.

## Rollback

Deploy the preceding application commit to hide the new route. The two additive tables can remain safely in place; keeping them preserves user drafts for a later retry. If permanent removal is required, export and securely retain their contents first, then drop `report_definition_versions` followed by `report_definitions` in a maintenance window. This removes saved definitions but does not alter payroll registers. Do not remove either table while a version of the application that imports its ORM models is running.

## Known limits

The first approved builder dataset is aggregate payroll cost at period × dimension grain. Its preview returns up to 200 rows and the full matched count, and the screen says when it is showing only the first 200. The screen exports only a saved version, and only when there are no unsaved changes, so a file always matches a definition that can be reopened. Definitions evaluate current data and are not immutable report outputs. A generated workbook contains all matched rows with provenance, a summary and the data basis; it is produced by a queued job (below) from the saved version. No CSV or external delivery is included. PDF output and schedules arrived on 30 September 2026 (below).

## Generated report jobs

Aggregate report generation now queues a job with a fixed definition version.
The output is retained for 30 days by default and is limited to 10 MB in the
database; an oversized output fails explicitly. The job records the source
register IDs, control totals, row count, checksum, requester and timestamps.
Downloads check current company and report access again. A changed or revoked
permission can remove access to a generated output. Expired output bytes are
cleared while history metadata remains. This is a first bounded storage
implementation; detail-scale exports require object storage and a separate
worker capacity benchmark before their release.

Rollback: deploy the previous application commit. Keep the additive
`report_jobs` table so completed outputs and history remain intact. To remove
it permanently, export and securely retain its contents first; dropping it
deletes generated artifacts. The worker can be disabled with
`REPORT_WORKER_ENABLED=false` while troubleshooting, but queued jobs then
remain pending until a worker resumes.

## Datasets, layouts, PDF and schedules (30 September 2026)

**What shipped.** Two more approved datasets beside payroll cost —
*workforce movement* (opening, joiners, moved in, exits, moved out, closing,
monthly attrition, at month × company dimension, from who was paid on each
register) and *validation findings* (findings, critical, people affected,
priced exposure, unpriced findings, at month × severity, check or component,
from each month's current run). Each field declares its unit and whether it
adds up across months and across groups; a pivot of one value by group and
month totals only where it does, and says so where it does not. Calculated
columns declare a unit (₹, number, %), and may name only their dataset's
metrics. A bar or line chart of the pivot value is optional. Output is Excel
(pivot sheet, native chart) or PDF.

**PDF** uses `fpdf2` (pure Python, added to `requirements.txt`) with the DejaVu
font, which `docker/Dockerfile.backend` now installs (`fonts-dejavu-core`) for
₹ and non-Latin names. Without the font a PDF job fails with that reason rather
than substituting characters. A PDF holds up to 3,000 rows; beyond that it asks
for Excel.

**Schedules** (`report_schedules`, one per report per person) run monthly on
day 1–28 or weekly, at an hour in India time, over a rolling window of complete
months ending the month before the run. The report worker queues due schedules
when idle (`report_jobs.schedule_due`), as a job requested by the schedule's
owner and marked `origin = schedule`. Delivery is to that person's Generated
files; the platform sends no email. A schedule whose owner has lost access, or
whose report is no longer available to them, is disabled with the reason.

**Additive schema.** New table `report_schedules`; new columns
`report_jobs.format` (default `xlsx`) and `report_jobs.origin` (default
`person`), added by the startup column patcher. Saved definitions from before
remain valid: a missing dataset means payroll cost, a missing unit means a plain
number, and a missing layout means a table.

**Rollback.** Deploy the previous commit. The new table and columns can stay.
Existing jobs with `format = pdf` would then download with the Excel content
type from the old code; clear or expire them first if that matters.
