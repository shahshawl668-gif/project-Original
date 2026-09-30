# Restore drill — 2026-09-30

**Result: PASS.** Written by `backend/tools/restore_drill.py`; nothing here is typed by hand.

| | |
|---|---|
| Source | `postgresql+psycopg2://pr36:***@127.0.0.1:5432/payroll_ui_test` |
| Restored into | `postgresql+psycopg2://pr36:***@127.0.0.1:5432/restore_drill_20260930212401` (dropped after the checks) |
| Tool | pg_dump (PostgreSQL) 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1) |
| Backup | 3,553,852 bytes in 0.55 s, SHA-256 `f74eab83191f224c80847bf42f476fc61ce6b62f1d3ee1538fab1ba24cea6451` |
| Restore | exit code 0, 1.45 s |
| Tables compared | 85 — row count **and** a digest of every row's content |
| Rows compared | 39,411 |
| Tables that differ | none |
| Application on the restored copy | health 200; platform sign-in HTTP 200; organisation list HTTP 200 returning 200 rows (the endpoint's page size caps this) |
| Started / finished | 2026-09-30T21:24:01+00:00 / 2026-09-30T21:24:09+00:00 |

Largest tables:

| Table | Rows |
|---|---|
| `slab_rules` | 23,325 |
| `finding_records` | 2,041 |
| `finding_states` | 1,806 |
| `audit_events` | 1,411 |
| `entities` | 1,281 |
| `salary_register_rows` | 1,178 |
| `users` | 793 |
| `refresh_tokens` | 773 |
| `components_config` | 736 |
| `org_memberships` | 730 |
| `organizations` | 715 |
| `input_digest_cache` | 568 |
| `input_revisions` | 412 |
| `validation_run_employees` | 398 |
| `salary_registers` | 372 |

## What this proves, and what it does not

It proves the backup format, the restore procedure and the application's
startup against a restored database work, and that the restore is complete to
the row. It does not prove that **production's** backups exist, are recent, or
restore: that needs the same drill run against a backup taken from production,
restored into a separate instance, by someone authorised to do so.
