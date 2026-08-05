"""MongoDB connection, request-scoped handle, and index management.

Design notes
------------
* **Synchronous driver.** Route handlers are sync (`def`, not `async def`), so
  PyMongo is the right fit — FastAPI runs them in a worker threadpool. Motor
  would force every handler and the validation service to become async for no
  throughput gain at this workload.

* **One client per process.** `MongoClient` owns an internal connection pool and
  is thread-safe; creating one per request would defeat pooling. `get_db()`
  hands the shared database handle to request scope.

* **Indexes, not schemas.** Mongo has no DDL to run, so startup only ensures
  indexes. `create_index` is idempotent, so this is safe on every boot.

* **Test injection.** `set_database()` lets the test suite point the app at a
  `mongomock` database without touching a real server.
"""
from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.config import settings

logger = logging.getLogger("payroll.db")

_client: MongoClient | None = None
_database: Database | None = None


def _make_client() -> MongoClient:
    return MongoClient(
        settings.mongodb_url,
        serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
        uuidRepresentation="standard",
        tz_aware=True,
    )


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = _make_client()
    return _client


def get_database() -> Database:
    """Return the shared database handle, connecting lazily on first use."""
    global _database
    if _database is None:
        _database = get_client()[settings.mongodb_db_name]
    return _database


def set_database(db: Database | None) -> None:
    """Override the database handle (used by tests to inject mongomock)."""
    global _database
    _database = db


def get_db() -> Generator[Database, None, None]:
    """FastAPI dependency — yields the shared database handle.

    There is no per-request session or transaction to close: PyMongo pools
    connections internally and each operation checks one out for its duration.
    """
    yield get_database()


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------
# (collection, keys, options). Unique indexes encode the constraints that were
# UniqueConstraint/unique=True under the relational schema, so the database
# still rejects duplicate tenants' keys rather than trusting callers.

_INDEXES: list[tuple[str, Any, dict[str, Any]]] = [
    ("users", [("email", ASCENDING)], {"unique": True, "name": "uq_user_email"}),
    ("refresh_tokens", [("user_id", ASCENDING), ("token_hash", ASCENDING)], {"name": "ix_refresh_lookup"}),
    ("refresh_tokens", [("expires_at", ASCENDING)], {"name": "ix_refresh_expiry"}),
    ("password_reset_tokens", [("token_hash", ASCENDING)], {"name": "ix_reset_token"}),
    ("components_config", [("user_id", ASCENDING)], {"name": "ix_components_user"}),
    (
        "components_config",
        [("user_id", ASCENDING), ("component_name", ASCENDING)],
        {"unique": True, "name": "uq_component_per_tenant"},
    ),
    ("statutory_settings", [("user_id", ASCENDING)], {"unique": True, "name": "uq_settings_user"}),
    ("statutory_config", [("user_id", ASCENDING)], {"unique": True, "name": "uq_config_user"}),
    ("slab_rules", [("user_id", ASCENDING), ("state", ASCENDING), ("rule_type", ASCENDING)], {"name": "ix_slab_lookup"}),
    ("pt_slabs", [("state", ASCENDING)], {"name": "ix_pt_state"}),
    ("lwf_rates", [("state", ASCENDING)], {"name": "ix_lwf_state"}),
    ("ctc_uploads", [("user_id", ASCENDING), ("created_at", DESCENDING)], {"name": "ix_ctc_upload_user"}),
    ("ctc_records", [("user_id", ASCENDING), ("employee_id", ASCENDING)], {"name": "ix_ctc_employee"}),
    (
        "ctc_records",
        [("user_id", ASCENDING), ("employee_id", ASCENDING), ("effective_from", ASCENDING)],
        {"unique": True, "name": "uq_ctc_employee_effective"},
    ),
    ("payroll_runs", [("user_id", ASCENDING), ("created_at", DESCENDING)], {"name": "ix_runs_user"}),
    (
        "salary_registers",
        [("user_id", ASCENDING), ("period_month", ASCENDING)],
        {"unique": True, "name": "uq_register_period"},
    ),
    ("salary_register_rows", [("register_id", ASCENDING)], {"name": "ix_rows_register"}),
    (
        "salary_register_rows",
        [("user_id", ASCENDING), ("period_month", ASCENDING), ("employee_id", ASCENDING)],
        {"name": "ix_rows_lookup"},
    ),
    ("rule_formulas", [("user_id", ASCENDING), ("rule_type", ASCENDING)], {"name": "ix_formula_lookup"}),
    (
        "tenant_rule_preferences",
        [("user_id", ASCENDING), ("rule_id", ASCENDING)],
        {"unique": True, "name": "uq_tenant_rule"},
    ),
]


def init_indexes(db: Database | None = None) -> None:
    """Ensure all indexes exist. Idempotent; safe to call on every startup."""
    target = db if db is not None else get_database()
    for collection, keys, options in _INDEXES:
        try:
            target[collection].create_index(keys, **options)
        except PyMongoError as exc:
            # A pre-existing index with the same name but different options, or
            # duplicate data blocking a unique index, must not stop the API from
            # booting — surface it and continue.
            logger.warning("Index %s on %s not created: %s", options.get("name"), collection, exc)


def ping() -> bool:
    """Cheap liveness probe for the health endpoint.

    Pings through the *active* database handle so the probe reflects whatever
    the app is actually querying.
    """
    try:
        get_database().client.admin.command("ping")
        return True
    except PyMongoError:
        return False
