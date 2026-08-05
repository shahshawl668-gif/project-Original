"""Test fixtures — back the app with an in-memory MongoDB.

`mongomock` implements the PyMongo client API, so the application code under
test runs completely unmodified: same `find`/`insert_one`/`update_many` calls,
same filter documents. Tests that need a real server (change streams,
transactions, `$expr` edge cases) are not in this suite.

Every test gets a fresh, empty database, so ordering never leaks state.
"""
from __future__ import annotations

import mongomock
import pytest

from app import database as db_module


@pytest.fixture()
def mongo_db():
    """A clean in-memory database, injected as the app's database handle."""
    client = mongomock.MongoClient()
    database = client["payroll_test"]
    db_module.set_database(database)
    db_module.init_indexes(database)
    try:
        yield database
    finally:
        db_module.set_database(None)
        client.close()
