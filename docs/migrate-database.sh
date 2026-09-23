#!/usr/bin/env bash
#
# Move PayrollCheck's PostgreSQL database from one host to another.
#
# Dumps the source, restores into the target, and then *checks that it
# worked* by comparing row counts table by table. The check is the point: a
# restore that half-succeeded and a restore that succeeded look identical
# until someone opens a register and finds three months missing.
#
#   Usage:
#     export SOURCE_DATABASE_URL='postgresql://...'   # the database you have
#     export TARGET_DATABASE_URL='postgresql://...'   # the database you want
#     ./docs/migrate-database.sh
#
#   Options (environment):
#     ALLOW_NON_EMPTY_TARGET=1   restore into a target that already has tables
#     KEEP_DUMP=1                keep the dump file instead of deleting it
#     DUMP_FILE=/path/to.dump    where to write it (default: a temp file)
#
# Credentials are never printed, never written to the dump's directory listing
# in a readable form, and never committed. Pass them through the environment,
# and prefer `read -rs` over typing them on a command line that lands in your
# shell history.
#
# See docs/DATABASE_MIGRATION.md for the surrounding procedure — in particular
# the ordering rule: restore BEFORE pointing the application at the new
# database, or the app will create an empty schema and the restore will collide
# with it.

set -euo pipefail

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
die()   { red "ERROR: $*" >&2; exit 1; }

# A URL with its password removed, safe to print.
redact() {
  printf '%s' "$1" | sed -E 's#(://[^:]+):[^@]*@#\1:****@#'
}

# ---------------------------------------------------------------------------
# Preflight — every one of these is a failure that is cheaper before the dump
# ---------------------------------------------------------------------------
bold "==> Preflight"

for tool in pg_dump pg_restore psql; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool not found. Install the PostgreSQL client tools (e.g. 'brew install libpq' or 'apt install postgresql-client')."
done

: "${SOURCE_DATABASE_URL:?set SOURCE_DATABASE_URL}"
: "${TARGET_DATABASE_URL:?set TARGET_DATABASE_URL}"

[ "$SOURCE_DATABASE_URL" != "$TARGET_DATABASE_URL" ] || die "Source and target are the same database."

echo "  source: $(redact "$SOURCE_DATABASE_URL")"
echo "  target: $(redact "$TARGET_DATABASE_URL")"

psql "$SOURCE_DATABASE_URL" -tAc 'select 1' >/dev/null 2>&1 \
  || die "Cannot connect to the source. Most managed hosts need '?sslmode=require' on the URL."
psql "$TARGET_DATABASE_URL" -tAc 'select 1' >/dev/null 2>&1 \
  || die "Cannot connect to the target. Most managed hosts need '?sslmode=require' on the URL."

source_version=$(psql "$SOURCE_DATABASE_URL" -tAc 'show server_version')
target_version=$(psql "$TARGET_DATABASE_URL" -tAc 'show server_version')
echo "  source server: PostgreSQL $source_version"
echo "  target server: PostgreSQL $target_version"

if [ "${source_version%%.*}" -gt "${target_version%%.*}" ]; then
  die "The target runs an older major version than the source. A dump does not restore backwards."
fi

target_tables=$(psql "$TARGET_DATABASE_URL" -tAc \
  "select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE'")
if [ "$target_tables" -ne 0 ]; then
  if [ "${ALLOW_NON_EMPTY_TARGET:-0}" = "1" ]; then
    red "  target already has $target_tables tables — continuing because ALLOW_NON_EMPTY_TARGET=1"
  else
    die "The target already has $target_tables tables.

This usually means the application has already been pointed at it and created
an empty schema on boot. Restore into an empty database instead: either drop
and recreate it, or point the application back at the old database until the
migration is done.

Set ALLOW_NON_EMPTY_TARGET=1 only if you know the existing tables are
disposable."
  fi
fi

green "  preflight OK"

# ---------------------------------------------------------------------------
# Dump
# ---------------------------------------------------------------------------
bold "==> Dumping the source"

dump_file="${DUMP_FILE:-$(mktemp -t payrollcheck-XXXXXX.dump)}"
cleanup() {
  if [ "${KEEP_DUMP:-0}" != "1" ] && [ -f "$dump_file" ]; then
    rm -f "$dump_file"
  fi
}
trap cleanup EXIT

# --no-owner and --no-acl because the new host's role names are its own; the
# application connects as whatever user its URL names and does not care who
# owned the tables on the old host.
pg_dump "$SOURCE_DATABASE_URL" --no-owner --no-acl --format=custom --file="$dump_file"
echo "  wrote $(du -h "$dump_file" | cut -f1) to $dump_file"
green "  dump OK"

# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
bold "==> Restoring into the target"

# Not --clean: the target is empty (or you asserted the contents are
# disposable), and --clean on a populated database is how a migration becomes
# an outage.
if ! pg_restore --dbname="$TARGET_DATABASE_URL" --no-owner --no-acl --single-transaction "$dump_file"; then
  die "Restore failed. The target has been rolled back (--single-transaction), so it is unchanged.
The dump is intact at: $dump_file
Re-run with KEEP_DUMP=1 if you want to keep it after a failure."
fi
green "  restore OK"

# ---------------------------------------------------------------------------
# Verify — the part that makes this a migration rather than a hope
# ---------------------------------------------------------------------------
bold "==> Verifying"

counts_sql="
select table_name || ':' || (xpath('/row/cnt/text()', xml_count))[1]::text
from (
  select table_name, table_schema,
         query_to_xml(format('select count(*) as cnt from %I.%I', table_schema, table_name),
                      false, true, '') as xml_count
  from information_schema.tables
  where table_schema = 'public' and table_type = 'BASE TABLE'
) t
order by table_name;
"

source_counts=$(psql "$SOURCE_DATABASE_URL" -tAc "$counts_sql")
target_counts=$(psql "$TARGET_DATABASE_URL" -tAc "$counts_sql")

if [ "$source_counts" = "$target_counts" ]; then
  table_count=$(printf '%s\n' "$source_counts" | grep -c . || true)
  row_total=$(printf '%s\n' "$source_counts" | awk -F: '{s+=$2} END {print s+0}')
  green "  every table matches — $table_count tables, $row_total rows"
else
  red "  MISMATCH between source and target:"
  diff <(printf '%s\n' "$source_counts") <(printf '%s\n' "$target_counts") || true
  die "Row counts differ. Do NOT point the application at the target yet."
fi

# ---------------------------------------------------------------------------
bold "==> Done"
cat <<'NEXT'

The target now holds the same data as the source. Nothing is using it yet.

To cut over:

  1. Render dashboard -> payroll-saas-api -> Environment
  2. Replace DATABASE_URL with the target's connection string
  3. Save; the service redeploys

Then confirm from the boot log, which names the database it opened:

  API ready | env=production | database=postgresql://<new-host>/<db> | ...

If that line still shows the old host, the variable did not save. If it shows
'sqlite:...(ephemeral)', DATABASE_URL is unset and the service is running on a
disk that does not survive a deploy — fix that before anyone signs in.

Keep the old database alive until you have seen the new one working under real
use. Rolling back is just putting the old URL back.

NEXT
