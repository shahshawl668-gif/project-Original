# 07 — Backup and recovery

> **TEMPLATE — NOT APPROVED.** Drafted from the codebase on 30 September 2026. It is not a policy until the named approver signs it, and it is not evidence of an operating ISMS until the records it names exist. Text in _italics_ is for the business to decide.

**Current state:** the production database is on a free plan with **no
backups** and an expiry date (`../../SECURITY.md` R1). This procedure cannot
operate until that changes.

**Targets to decide:** RPO _(e.g. 24 hours; point-in-time recovery gives minutes)_ ·
RTO _(e.g. 4 hours)_.

**Procedure (tested on synthetic data — `../../evidence/restore-drill-2026-09-30.md`):**
1. Restore the backup under test into a **separate** database instance.
2. Run `backend/tools/restore_drill.py` (or its checks) against it: every
   table's row count and content digest against the source, then boot the
   application on the copy and sign in.
3. File the generated record in `docs/evidence/`. A backup job that reports
   success is not a record; a checked restore is.
4. _Quarterly_, and after any change to the database platform.

Keys are part of recovery: a database restored without `STUDIO_SECRET_KEY`
cannot open connection secrets or two-step secrets, and one restored without
`JWT_SECRET` signs everyone out. Keep both in a place that survives losing
the hosting account.
