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

The first approved builder dataset is aggregate payroll cost at period × dimension grain. Its preview returns up to 200 rows and the full matched count. Definitions evaluate current data and are not immutable report outputs. The saved aggregate workbook exports all matched rows with provenance, a summary and the data basis. Generation is synchronous and uses current data. No CSV, PDF, scheduled job, immutable artifact retention, external delivery or 8,000/20,000 employee benchmark is included in this increment.

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
