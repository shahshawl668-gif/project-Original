"""
Shared test configuration.

The app builds its engine at import time from the environment, so the database
has to be pointed at a scratch file *before* anything under ``app`` is imported.
Doing it here — in conftest, which pytest loads first — avoids the module-reload
gymnastics that would otherwise be needed, and which quietly break the ORM
registry by rebinding ``Base``.
"""
from __future__ import annotations

import os
import tempfile

_TEST_DB = os.path.join(tempfile.mkdtemp(prefix="payroll-tests-"), "test.db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("JWT_SECRET", "test-secret-not-used-outside-tests")
os.environ["ALLOW_ANONYMOUS_API"] = "false"
os.environ["ENV"] = "dev"

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """
    One booted app for the whole session.

    Startup runs create_all, the migrations and the seeders, so this exercises
    the same path production takes. Tests share the database and keep
    themselves apart by using distinct signup emails — which also means each
    test gets its own organization, the isolation being tested.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
