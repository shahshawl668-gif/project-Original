# Moving the database

How to move Peopleopslab's PostgreSQL database to a different host, without
losing anything and without a window where the application is pointed at a
database that is not ready.

The script that does it is [`migrate-database.sh`](migrate-database.sh), in this
directory. It has been run end to end against two real PostgreSQL 16 databases
carrying this application's schema — 43 tables, 759 rows — and verified by
booting the API against the result. It is not a sketch.

---

## Why you would do this

**The free Render database has a fixed lifespan.** It is deleted — not
suspended — thirty days after it was created:

```
plan:      free
createdAt: 2026-09-22T20:27:54Z
expiresAt: 2026-10-22T20:27:54Z      # 23 October, 01:57 IST
```

Everything in it goes with it: the platform-admin account, entities, salary
components, statutory configuration, slabs, employee master, registers,
findings and the audit trail. The application keeps running and fails every
request, because the database it is configured to reach no longer exists.

The other reasons are ordinary: outgrowing a plan, moving to a provider you
already pay, or wanting backups the free tier does not offer.

---

## Which host

The application is not tied to any vendor. There is no `JSONB`, no `ARRAY`, no
`ON CONFLICT`, no PostgreSQL-only SQL anywhere in `backend/app` — the ORM uses
generic SQLAlchemy types, and `migrations.py` branches only on SQLite versus
everything else. Changing host is one environment variable.

| Host | Why you would pick it | What it costs you |
|---|---|---|
| **Render, paid plan** | No migration at all — change the plan in place. Daily backups. One vendor. | A few dollars a month |
| **Neon** | Free tier with no thirty-day death | Scales to zero, so the first query after idle is slow |
| **Supabase** | Generous free tier, good dashboard | Free projects pause after about a week idle |
| **Aiven / RDS** | Serious operational guarantees | Priced accordingly |
| **Your own VPS** | You already pay Hostinger; total control | Backups, patching and uptime become your job — for payroll data that is real work, not a checkbox |

If the goal is to avoid the deadline without paying, **Neon**. If the goal is
the least operational risk for a product holding payroll data, **pay Render**:
there is no migration to get wrong, and backups come with it.

### Changing engine — don't

MySQL or anything else would work in principle and buy nothing. Money is
`Numeric`/`Decimal` with `ROUND_HALF_UP` throughout and the rounding semantics
differ; `migrations.py` has no branch for it; and all 810 tests have only ever
run against SQLite and PostgreSQL. You would be revalidating a payroll engine
to change a logo. Stay on PostgreSQL.

---

## The one rule that matters

**Restore before you point the application at the new database.**

The API runs `create_all` and the migrations on boot. If it reaches the new
database first, it creates an empty schema, and the restore then collides with
tables that already exist. The script refuses to restore into a non-empty
target for exactly this reason.

Order: create the database → run the script → *then* change `DATABASE_URL`.

---

## Doing it

### 1. Create the target database, and nothing else

Create it on the new host. Do not point anything at it. Copy its connection
string — most managed hosts need `?sslmode=require` appended, and connections
are refused without it.

### 2. Run the migration

You need the PostgreSQL client tools (`pg_dump`, `pg_restore`, `psql`) — on
Debian or Ubuntu, `apt install postgresql-client`; on macOS, `brew install
libpq`.

```bash
read -rs -p "source URL: " SOURCE_DATABASE_URL; echo
read -rs -p "target URL: " TARGET_DATABASE_URL; echo
export SOURCE_DATABASE_URL TARGET_DATABASE_URL

./docs/migrate-database.sh
```

`read -rs` keeps the credentials out of your shell history, which typing them
on the command line would not.

The script will:

1. **Check before it starts** — the tools exist, both URLs connect, the target
   is not an older major version, and the target is empty.
2. **Dump** the source with `--no-owner --no-acl --format=custom`, because the
   new host's role names are its own.
3. **Restore** inside `--single-transaction`, so a failure leaves the target
   untouched rather than half-populated.
4. **Verify** by comparing row counts table by table, and refuse to declare
   success on any mismatch.

A good run ends:

```
==> Verifying
  every table matches — 43 tables, 759 rows
==> Done
```

Passwords are redacted in everything it prints.

### 3. Cut over

Render dashboard → `payroll-saas-api` → **Environment** → replace
`DATABASE_URL` with the target's connection string → save. The service
redeploys.

### 4. Confirm from the boot log

The API names the database it opened, every time it starts:

```
API ready | env=production | database=postgresql://<new-host>/<db> | anonymous=False
```

- Still the **old host** → the variable did not save.
- `sqlite:...(ephemeral)` → `DATABASE_URL` is unset, and the service is running
  on a disk that does not survive a deploy. Fix that before anyone signs in;
  there will be an ERROR line above it saying so.

Then sign in and open **Companies**. If the companies, periods and finding
counts are what they were, the migration is done.

---

## Rolling back

Put the old `DATABASE_URL` back and save. That is the whole rollback, and it is
why the next rule exists.

**Keep the old database alive until the new one has carried real use for a few
days.** Deleting it the same afternoon converts a thirty-second rollback into a
restore from a backup you have not tested.

---

## What not to do

- **Do not put the connection string in the repository**, in `.env`, or in
  client-side code. It belongs in the host's environment and nowhere else.
- **Do not add `--clean` to the restore.** On a populated database that is how
  a migration becomes an outage.
- **Do not point the application at the target first** — see the rule above.
- **Do not skip the verification** because the restore printed no errors. A
  restore that half-succeeded and one that succeeded look identical until
  someone opens a register and finds three months missing.

---

## If it goes wrong

| What you see | What it means |
|---|---|
| `Cannot connect to the target` | Almost always a missing `?sslmode=require` |
| `The target already has N tables` | Something was pointed at it first. Drop and recreate it, or set `ALLOW_NON_EMPTY_TARGET=1` if you are certain those tables are disposable |
| `Restore failed` | The target was rolled back and is unchanged. Re-run with `KEEP_DUMP=1` to keep the dump for inspection |
| `Row counts differ` | Do not cut over. The diff printed above it names the tables |
| Boot log shows `sqlite:...(ephemeral)` | `DATABASE_URL` is unset on the service |
