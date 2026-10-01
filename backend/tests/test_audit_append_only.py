"""
The audit trail and the security log cannot be edited or deleted through the
application's database connection — on either dialect.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from tests.test_run_history import _company


@pytest.mark.parametrize("table", ["audit_events", "security_events"])
def test_the_trail_refuses_to_be_rewritten(client, table):
    _company(client, "append")                       # writes audit rows
    client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "not-it"})  # a security event
    with SessionLocal() as db:
        assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() > 0  # nosec B608
        for statement in (f"UPDATE {table} SET created_at = created_at",
                          f"DELETE FROM {table}"):
            with pytest.raises(DBAPIError, match="append-only"):
                db.execute(text(statement))
            db.rollback()
        # Adding to it is, of course, still how it works.
        assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() > 0  # nosec B608
