"""
Restore drill: back up a database, restore it somewhere else, and prove the
restored copy is the same data and a working product.

    python tools/restore_drill.py --source "$SOURCE_URL" --admin "$ADMIN_URL" \
        --login someone@example.com --report ../docs/evidence/restore-drill-YYYY-MM-DD.md

A backup job that reports success is not recovery evidence; a restore that
was checked is. This does the whole path and writes down what it found:

1. ``pg_dump`` the source (custom format), recording size, SHA-256 and time.
2. Create an empty database and ``pg_restore`` into it, recording time.
3. Compare every table: row count, and a digest of every row's content.
4. Boot the application against the restored copy — startup runs the schema
   checks and migrations — and sign in as ``--login`` through the real API
   (the password is read from ``DRILL_PASSWORD``, never an argument, so it is
   not in shell history or the report).
5. Drop the restored copy unless ``--keep``.

Run it against a copy or a synthetic database, never pointed at production
with ``--admin`` rights there: step 2 creates databases. Against production,
restore into a separate instance instead and point ``--source`` at the backup
you are testing. Any mismatch is a failed drill, and the exit code says so.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def _libpq(url: str) -> str:
    """postgresql+psycopg2://… → postgresql://… for the command-line tools."""
    u = make_url(url)
    return u.set(drivername="postgresql").render_as_string(hide_password=False)


def _redact(url: str) -> str:
    return make_url(url).render_as_string(hide_password=True)


def _tables(url: str) -> dict[str, tuple[int, str]]:
    """Every public table: (rows, md5 of all rows' text in a stable order)."""
    engine = create_engine(url)
    out: dict[str, tuple[int, str]] = {}
    with engine.connect() as conn:
        names = [r[0] for r in conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"))]
        for name in names:
            q = f'SELECT count(*), md5(coalesce(string_agg(t::text, E\'\\n\' ORDER BY t::text), \'\')) FROM "{name}" t'
            count, digest = conn.execute(text(q)).one()  # nosec B608 — names come from the catalogue
            out[name] = (int(count), digest)
    engine.dispose()
    return out


def _boot_and_sign_in(url: str, email: str | None) -> dict:
    """Start the real application on the restored copy, in a clean process."""
    probe = r"""
import json, os, sys
from fastapi.testclient import TestClient
from app.main import app
result = {}
with TestClient(app) as c:
    result["health"] = c.get("/api/health").status_code
    email = os.environ.get("DRILL_LOGIN")
    if email:
        r = c.post("/api/auth/platform-login", json={"email": email, "password": os.environ["DRILL_PASSWORD"]})
        result["platform_login"] = r.status_code
        if r.status_code == 200 and "access_token" in r.json()["data"]:
            h = {"Authorization": "Bearer " + r.json()["data"]["access_token"]}
            orgs = c.get("/api/admin/organizations", headers=h)
            result["organizations_status"] = orgs.status_code
            if orgs.status_code == 200:
                result["organizations_returned"] = len(orgs.json()["data"])
print("DRILL-RESULT " + json.dumps(result))
"""
    env = {**os.environ, "DATABASE_URL": url, "ENV": "dev", "ALLOW_ANONYMOUS_API": "false",
           "VALIDATION_WORKER_ENABLED": "false", "REPORT_WORKER_ENABLED": "false"}
    if email:
        env["DRILL_LOGIN"] = email
    done = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True,
                          cwd=Path(__file__).resolve().parent.parent, timeout=600)
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("DRILL-RESULT ")), None)
    if line is None:
        return {"error": (done.stderr or done.stdout)[-2000:]}
    return json.loads(line[len("DRILL-RESULT "):])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", required=True, help="SQLAlchemy URL of the database to back up")
    ap.add_argument("--admin", required=True, help="URL with rights to CREATE/DROP DATABASE on the target server")
    ap.add_argument("--login", help="a platform account to sign in as on the restored copy (password in DRILL_PASSWORD)")
    ap.add_argument("--report", help="write a Markdown record here")
    ap.add_argument("--keep", action="store_true", help="keep the restored database afterwards")
    args = ap.parse_args()
    if args.login and not os.environ.get("DRILL_PASSWORD"):
        ap.error("--login needs DRILL_PASSWORD in the environment")

    started = datetime.now(UTC)
    target_name = f"restore_drill_{started:%Y%m%d%H%M%S}"
    admin = make_url(args.admin)
    target = make_url(args.source).set(database=target_name).render_as_string(hide_password=False)
    record: dict = {"started": started.isoformat(timespec="seconds"), "source": _redact(args.source),
                    "restored_into": _redact(target)}

    with tempfile.TemporaryDirectory() as tmp:
        dump = Path(tmp) / "backup.dump"
        t0 = time.monotonic()
        subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--file", str(dump), _libpq(args.source)],
                       check=True)
        record["backup_seconds"] = round(time.monotonic() - t0, 2)
        record["backup_bytes"] = dump.stat().st_size
        record["backup_sha256"] = hashlib.sha256(dump.read_bytes()).hexdigest()
        record["pg_dump"] = subprocess.run(["pg_dump", "--version"], capture_output=True, text=True).stdout.strip()

        engine = create_engine(admin.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            owner = make_url(args.source).username
            conn.execute(text(f'CREATE DATABASE "{target_name}" OWNER "{owner}"'))  # nosec B608 — generated name
        t0 = time.monotonic()
        restored = subprocess.run(["pg_restore", "--no-owner", "--exit-on-error", "--dbname", _libpq(target), str(dump)],
                                  capture_output=True, text=True)
        record["restore_seconds"] = round(time.monotonic() - t0, 2)
        record["restore_exit_code"] = restored.returncode

    try:
        before, after = _tables(args.source), _tables(target)
        mismatched = sorted(n for n in before.keys() | after.keys() if before.get(n) != after.get(n))
        record["tables"] = len(before)
        record["rows"] = sum(c for c, _ in before.values())
        record["tables_mismatched"] = mismatched
        record["application"] = _boot_and_sign_in(target, args.login)
    finally:
        if not args.keep:
            with engine.connect() as conn:
                conn.execute(text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :d"), {"d": target_name})
                conn.execute(text(f'DROP DATABASE IF EXISTS "{target_name}"'))  # nosec B608
            record["restored_copy"] = "dropped after the checks"
        engine.dispose()

    app = record["application"]
    passed = (record["restore_exit_code"] == 0 and not record["tables_mismatched"] and app.get("health") == 200
              and (not args.login or (app.get("platform_login") == 200 and app.get("organizations_status") == 200)))
    record["result"] = "PASS" if passed else "FAIL"
    record["finished"] = datetime.now(UTC).isoformat(timespec="seconds")
    print(json.dumps(record, indent=2))
    if args.report:
        Path(args.report).write_text(_markdown(record, before if record.get("tables") else {}))
    return 0 if passed else 1


def _markdown(r: dict, tables: dict) -> str:
    app = r["application"]
    rows = "\n".join(f"| `{n}` | {c:,} |" for n, (c, _) in sorted(tables.items(), key=lambda x: -x[1][0])[:15])
    return f"""# Restore drill — {r['started'][:10]}

**Result: {r['result']}.** Written by `backend/tools/restore_drill.py`; nothing here is typed by hand.

| | |
|---|---|
| Source | `{r['source']}` |
| Restored into | `{r['restored_into']}` ({r.get('restored_copy', 'kept')}) |
| Tool | {r['pg_dump']} |
| Backup | {r['backup_bytes']:,} bytes in {r['backup_seconds']} s, SHA-256 `{r['backup_sha256']}` |
| Restore | exit code {r['restore_exit_code']}, {r['restore_seconds']} s |
| Tables compared | {r['tables']} — row count **and** a digest of every row's content |
| Rows compared | {r['rows']:,} |
| Tables that differ | {', '.join(r['tables_mismatched']) or 'none'} |
| Application on the restored copy | health {app.get('health')}; platform sign-in HTTP {app.get('platform_login', 'not attempted')}; organisation list HTTP {app.get('organizations_status', '—')} returning {app.get('organizations_returned', '—')} rows (the endpoint's page size caps this) |
| Started / finished | {r['started']} / {r['finished']} |

Largest tables:

| Table | Rows |
|---|---|
{rows}

## What this proves, and what it does not

It proves the backup format, the restore procedure and the application's
startup against a restored database work, and that the restore is complete to
the row. It does not prove that **production's** backups exist, are recent, or
restore: that needs the same drill run against a backup taken from production,
restored into a separate instance, by someone authorised to do so.
"""


if __name__ == "__main__":
    sys.exit(main())
