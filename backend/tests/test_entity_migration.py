"""
Migration coverage for the move from user-scoped to entity-scoped data.

These build a database in the *old* shape — the one shipped before entities
existed — and assert that a boot converges it without losing rows or access.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, inspect, text

from app.database import Base
from app.migrations import run_migrations

# The pre-entity schema, trimmed to the tables the migration touches.
LEGACY_DDL = [
    """
    CREATE TABLE users (
        id CHAR(32) PRIMARY KEY,
        email VARCHAR(255) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        company_name VARCHAR(255),
        role VARCHAR(32) NOT NULL DEFAULT 'user',
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE components_config (
        id CHAR(32) PRIMARY KEY,
        user_id CHAR(32) NOT NULL,
        component_name VARCHAR(100) NOT NULL,
        pf_applicable BOOLEAN NOT NULL DEFAULT 0,
        esic_applicable BOOLEAN NOT NULL DEFAULT 0,
        pt_applicable BOOLEAN NOT NULL DEFAULT 0,
        lwf_applicable BOOLEAN NOT NULL DEFAULT 0,
        bonus_applicable BOOLEAN NOT NULL DEFAULT 0,
        included_in_wages BOOLEAN NOT NULL DEFAULT 0,
        taxable BOOLEAN NOT NULL DEFAULT 0,
        tax_exemption_type VARCHAR(20) NOT NULL DEFAULT 'none',
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        UNIQUE (user_id, component_name)
    )
    """,
    """
    CREATE TABLE salary_registers (
        id CHAR(32) PRIMARY KEY,
        user_id CHAR(32) NOT NULL,
        period_month DATE NOT NULL,
        filename VARCHAR(512),
        employee_count INTEGER,
        created_at TIMESTAMP,
        UNIQUE (user_id, period_month)
    )
    """,
    """
    CREATE TABLE statutory_config (
        user_id CHAR(32) PRIMARY KEY,
        pf_config JSON NOT NULL,
        esic_config JSON NOT NULL,
        component_mapping_config JSON NOT NULL,
        income_tax_config JSON,
        rule_thresholds_config JSON,
        updated_at TIMESTAMP
    )
    """,
]


@pytest.fixture()
def legacy_engine(tmp_path):
    """A database populated in the old shape, before any migration runs."""
    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    user_id = uuid.uuid4().hex
    with engine.begin() as conn:
        for ddl in LEGACY_DDL:
            conn.execute(text(ddl))
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, company_name, role) "
                "VALUES (:id, 'legacy@example.com', 'x', 'Legacy Textiles', 'admin')"
            ),
            {"id": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO components_config (id, user_id, component_name, pf_applicable) "
                "VALUES (:id, :uid, 'Basic', 1)"
            ),
            {"id": uuid.uuid4().hex, "uid": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO salary_registers (id, user_id, period_month, employee_count) "
                "VALUES (:id, :uid, '2025-04-01', 42)"
            ),
            {"id": uuid.uuid4().hex, "uid": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO statutory_config (user_id, pf_config, esic_config, component_mapping_config) "
                "VALUES (:uid, '{}', '{}', '{}')"
            ),
            {"uid": user_id},
        )
    engine.user_id = user_id  # carried to the tests for convenience
    return engine


def _migrate(engine):
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)


def test_legacy_user_gets_org_entity_and_owner_seat(legacy_engine):
    _migrate(legacy_engine)
    with legacy_engine.connect() as conn:
        org = conn.execute(text("SELECT name, org_type FROM organizations")).fetchone()
        assert org.name == "Legacy Textiles"
        # A pre-entity tenant was one company; "enterprise" preserves that.
        assert org.org_type == "enterprise"

        entity = conn.execute(text("SELECT name, code FROM entities")).fetchone()
        assert entity.name == "Legacy Textiles"
        assert entity.code == "LEGACYTEXTIL"  # 12-char handle from "Legacy Textiles"

        role = conn.execute(
            text("SELECT role FROM org_memberships WHERE user_id = :uid"),
            {"uid": legacy_engine.user_id},
        ).scalar_one()
        assert role == "owner"


def test_existing_rows_are_backfilled_to_that_entity(legacy_engine):
    _migrate(legacy_engine)
    with legacy_engine.connect() as conn:
        entity_id = conn.execute(text("SELECT id FROM entities")).scalar_one()

        for table in ("components_config", "salary_registers"):
            rows = conn.execute(text(f"SELECT entity_id FROM {table}")).fetchall()
            assert rows, f"{table} lost its rows"
            assert all(r.entity_id == entity_id for r in rows), f"{table} not backfilled"


def test_statutory_config_is_rekeyed_to_the_entity(legacy_engine):
    _migrate(legacy_engine)
    with legacy_engine.connect() as conn:
        cols = {c["name"] for c in inspect(conn).get_columns("statutory_config")}
        assert "entity_id" in cols
        assert "user_id" not in cols, "the old user key should be gone after re-keying"

        entity_id = conn.execute(text("SELECT id FROM entities")).scalar_one()
        assert conn.execute(text("SELECT entity_id FROM statutory_config")).scalar_one() == entity_id


def test_unique_constraint_moves_from_user_to_entity(legacy_engine):
    """Two entities must be able to hold the same period — the practice case."""
    _migrate(legacy_engine)
    with legacy_engine.begin() as conn:
        org_id = conn.execute(text("SELECT id FROM organizations")).scalar_one()
        second = uuid.uuid4().hex
        conn.execute(
            text(
                "INSERT INTO entities (id, org_id, name, code, is_active) "
                "VALUES (:id, :org, 'Second Client', 'SECOND', 1)"
            ),
            {"id": second, "org": org_id},
        )
        user_id = legacy_engine.user_id
        # Same user, same month, different entity — legal now, was not before.
        conn.execute(
            text(
                "INSERT INTO salary_registers (id, user_id, entity_id, period_month, employee_count) "
                "VALUES (:id, :uid, :eid, '2025-04-01', 7)"
            ),
            {"id": uuid.uuid4().hex, "uid": user_id, "eid": second},
        )
        count = conn.execute(
            text("SELECT COUNT(*) FROM salary_registers WHERE period_month = '2025-04-01'")
        ).scalar_one()
        assert count == 2


def test_migration_is_idempotent(legacy_engine):
    """Every boot runs the steps; a second pass must change nothing."""
    _migrate(legacy_engine)
    with legacy_engine.connect() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM organizations")).scalar_one()

    run_migrations(legacy_engine)
    run_migrations(legacy_engine)

    with legacy_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM organizations")).scalar_one() == before
        assert conn.execute(text("SELECT COUNT(*) FROM entities")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM components_config")).scalar_one() == 1
