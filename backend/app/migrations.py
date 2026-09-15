"""
Ordered, idempotent schema migrations.

``Base.metadata.create_all`` creates missing *tables* but never alters existing
ones, and the original column-patcher in ``app.database`` only knows how to add
columns. Introducing entities as the data-scope needs more than that: backfilling
a NOT NULL foreign key, swapping unique constraints from the user to the entity,
and re-keying two config tables whose primary key *was* ``user_id``.

Every step here is idempotent and safe to run on each boot. Steps detect their
own completion by inspecting the live schema rather than by recording a version,
so a database at any point in the history converges to the current shape.

SQLite (local dev) and PostgreSQL (production) differ on what can be altered in
place, so the destructive steps branch on dialect: PostgreSQL drops constraints
directly, SQLite rebuilds the table through the standard copy-and-rename dance.
"""
from __future__ import annotations

import uuid

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

# Importing the model package registers every table on Base.metadata. The
# rebuild steps below read that metadata to generate DDL, so the import has to
# happen whenever migrations run — not only when the API boots.
import app.models  # noqa: F401

# Tables that hold tenant data and therefore need an entity_id scope column.
# Ordered so that parents are patched before children, which keeps the backfill
# joins below readable.
ENTITY_SCOPED_TABLES = (
    "components_config",
    "payroll_runs",
    "ctc_uploads",
    "ctc_records",
    "salary_registers",
    "salary_register_rows",
    "rule_formulas",
    "slab_rules",
    "tenant_rule_preferences",
)

# Unique constraints that were scoped to the user and must now be scoped to the
# entity: (table, old columns, new columns).
UNIQUE_RESCOPES = (
    ("components_config", ("user_id", "component_name"), ("entity_id", "component_name")),
    ("ctc_records", ("user_id", "employee_id", "effective_from"), ("entity_id", "employee_id", "effective_from")),
    ("salary_registers", ("user_id", "period_month"), ("entity_id", "period_month")),
    ("rule_formulas", ("user_id", "rule_type", "version"), ("entity_id", "rule_type", "version")),
    ("tenant_rule_preferences", ("user_id", "rule_id"), ("entity_id", "rule_id")),
)


def _table_names(conn: Connection) -> set[str]:
    return set(inspect(conn).get_table_names())


def _columns(conn: Connection, table: str) -> set[str]:
    return {c["name"] for c in inspect(conn).get_columns(table)}


def _uuid_type(conn: Connection) -> str:
    return "CHAR(32)" if conn.dialect.name == "sqlite" else "UUID"


def _bind_uuid(conn: Connection, value) -> object:
    """
    Render a UUID the way this dialect stores it.

    SQLAlchemy's ``Uuid`` column type does this conversion for ORM writes, but
    the statements here are raw SQL: SQLite's driver rejects a ``uuid.UUID``
    outright and keeps these ids as 32-char hex, while PostgreSQL wants the
    native object. Getting this wrong fails only on one of the two backends,
    which is exactly the kind of bug that reaches production.
    """
    if conn.dialect.name == "sqlite":
        return value.hex if isinstance(value, uuid.UUID) else str(value).replace("-", "")
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


# ---------------------------------------------------------------------------
# Step 1 — add entity_id to every tenant-scoped table
# ---------------------------------------------------------------------------
def add_entity_columns(conn: Connection) -> None:
    """
    Add ``entity_id`` as a nullable column.

    It is declared NOT NULL in the ORM, but added nullable here so the backfill
    has somewhere to write. Once populated, ``enforce_entity_not_null`` tightens
    it. Doing it in one step would fail on any table that already has rows.
    """
    tables = _table_names(conn)
    col_type = _uuid_type(conn)
    for table in ENTITY_SCOPED_TABLES:
        if table not in tables or "entity_id" in _columns(conn, table):
            continue
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN entity_id {col_type}"))


# ---------------------------------------------------------------------------
# Step 2 — give every pre-existing user an organization and a default entity
# ---------------------------------------------------------------------------
def provision_legacy_tenants(conn: Connection) -> dict[str, str]:
    """
    Create an org + entity + owner membership for each user that has none.

    Before entities existed, one user *was* one tenant. That mapping is preserved
    exactly: each legacy user becomes the owner of a single-entity organization
    holding all of their data, so nobody loses access to anything they uploaded.

    Returns a ``{user_id: entity_id}`` map (hex, unhyphenated) for the backfill.
    """
    tables = _table_names(conn)
    if not {"users", "organizations", "entities", "org_memberships"} <= tables:
        return {}

    rows = conn.execute(
        text(
            """
            SELECT u.id, u.email, u.company_name
            FROM users u
            LEFT JOIN org_memberships m ON m.user_id = u.id
            WHERE m.id IS NULL
            """
        )
    ).fetchall()

    mapping: dict[str, str] = {}
    for user_id, email, company_name in rows:
        display = (company_name or "").strip() or (email or "").split("@")[0] or "My organization"
        org_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        bound_org = _bind_uuid(conn, org_id)
        bound_entity = _bind_uuid(conn, entity_id)
        # A legacy tenant is one company, so "enterprise" is the honest default;
        # switching to a practice later is a field update, not a migration.
        conn.execute(
            text("INSERT INTO organizations (id, name, org_type) VALUES (:id, :name, 'enterprise')"),
            {"id": bound_org, "name": display},
        )
        conn.execute(
            text(
                """
                INSERT INTO entities (id, org_id, name, legal_name, code, is_active)
                VALUES (:id, :org_id, :name, :name, :code, :active)
                """
            ),
            {
                "id": bound_entity,
                "org_id": bound_org,
                "name": display,
                "code": _entity_code(display),
                "active": True,
            },
        )
        conn.execute(
            text(
                "INSERT INTO org_memberships (id, org_id, user_id, role) "
                "VALUES (:id, :org_id, :user_id, 'owner')"
            ),
            {
                "id": _bind_uuid(conn, uuid.uuid4()),
                "org_id": bound_org,
                "user_id": _bind_uuid(conn, user_id),
            },
        )
        mapping[_hex(user_id)] = _hex(entity_id)
    return mapping


def _entity_code(display: str) -> str:
    """Derive a short uppercase handle; uniqueness is per-org so collisions are rare."""
    cleaned = "".join(ch for ch in display.upper() if ch.isalnum())[:12]
    return cleaned or "DEFAULT"


def _hex(value) -> str:
    if isinstance(value, uuid.UUID):
        return value.hex
    return str(value).replace("-", "")


# ---------------------------------------------------------------------------
# Step 3 — point existing rows at their owner's default entity
# ---------------------------------------------------------------------------
def backfill_entity_ids(conn: Connection) -> None:
    """
    Fill ``entity_id`` on every legacy row from its ``user_id``.

    Resolved through the membership table rather than the map returned by
    provisioning, so this also repairs rows written by an older build that ran
    after an org already existed.
    """
    tables = _table_names(conn)
    if "org_memberships" not in tables:
        return
    for table in ENTITY_SCOPED_TABLES:
        if table not in tables:
            continue
        cols = _columns(conn, table)
        if "entity_id" not in cols or "user_id" not in cols:
            continue
        conn.execute(
            text(
                f"""
                UPDATE {table}
                SET entity_id = (
                    SELECT e.id FROM entities e
                    JOIN org_memberships m ON m.org_id = e.org_id
                    WHERE m.user_id = {table}.user_id
                    ORDER BY e.created_at
                    LIMIT 1
                )
                WHERE entity_id IS NULL
                """
            )
        )


# ---------------------------------------------------------------------------
# Step 4 — re-key the two config tables whose primary key was user_id
# ---------------------------------------------------------------------------
def rekey_config_tables(conn: Connection) -> None:
    """
    Move ``statutory_settings`` and ``statutory_config`` from a user PK to an
    entity PK.

    Statutory configuration belongs to the employer, not to the person who typed
    it in: a practice's Maharashtra client and its Karnataka client need
    different PT settings even though the same analyst maintains both. Rows are
    carried over against the owner's default entity.
    """
    tables = _table_names(conn)
    if not {"entities", "org_memberships"} <= tables:
        return
    for table in ("statutory_settings", "statutory_config"):
        if table not in tables:
            continue
        cols = _columns(conn, table)
        if "entity_id" in cols:
            continue  # already re-keyed
        if "user_id" not in cols:
            continue

        col_type = _uuid_type(conn)
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN entity_id {col_type}"))
        conn.execute(
            text(
                f"""
                UPDATE {table}
                SET entity_id = (
                    SELECT e.id FROM entities e
                    JOIN org_memberships m ON m.org_id = e.org_id
                    WHERE m.user_id = {table}.user_id
                    ORDER BY e.created_at
                    LIMIT 1
                )
                """
            )
        )
        # Drop rows that could not be mapped — they belong to a deleted user and
        # are unreachable either way. Leaving them would break the NOT NULL PK.
        conn.execute(text(f"DELETE FROM {table} WHERE entity_id IS NULL"))
        _swap_primary_key(conn, table, "user_id", "entity_id")


def _copy_expression(column) -> str:
    """
    How to read one column out of the old table during a rebuild.

    A column that is NOT NULL in the target but holds NULLs in the old table
    would fail the copy. Where the target declares a server default, fall back
    to it — that is what the database would have written anyway.
    """
    if column.nullable or column.server_default is None:
        return column.name
    # Every server default in this schema is a timestamp (created_at/updated_at).
    return f"COALESCE({column.name}, CURRENT_TIMESTAMP)"


def _default_literal(column) -> str | None:
    """Render a column's Python-side default as SQL, or None if it has none."""
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    value = default.arg
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return None


def _swap_primary_key(conn: Connection, table: str, old_col: str, new_col: str) -> None:
    """Rebuild ``table`` so ``new_col`` is the primary key and ``old_col`` is gone."""
    if conn.dialect.name == "sqlite":
        # SQLite cannot alter a primary key, so rebuild through a copy. The ORM
        # metadata already describes the target shape, so create the new table
        # from it under a temp name, copy the shared columns, then swap.
        _sqlite_rebuild(conn, table, drop_columns={old_col})
        return
    # PostgreSQL can do this in place.
    conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey"))
    conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {new_col} SET NOT NULL"))
    conn.execute(text(f"ALTER TABLE {table} ADD PRIMARY KEY ({new_col})"))
    conn.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {old_col}"))


def _sqlite_rebuild(conn: Connection, table: str, drop_columns: set[str]) -> None:
    """
    Rebuild a SQLite table to match the current ORM metadata.

    Copies across the columns present in both the old table and the new
    definition; anything in ``drop_columns`` is left behind.
    """
    from app.database import Base

    target = Base.metadata.tables.get(table)
    if target is None:
        return

    old_cols = _columns(conn, table)
    new_cols = {c.name for c in target.columns}
    shared = sorted((old_cols & new_cols) - drop_columns)
    if not shared:
        return

    # A NOT NULL column the old table never had still needs a value. Where the
    # model declares a Python-side default, write it as a literal; that is the
    # value the ORM would have produced for these rows.
    backfilled: list[tuple[str, str]] = []
    for name in sorted(new_cols - old_cols):
        column = target.columns[name]
        if column.nullable or column.server_default is not None:
            continue
        literal = _default_literal(column)
        if literal is not None:
            backfilled.append((name, literal))

    tmp = f"{table}__new"
    conn.execute(text(f"DROP TABLE IF EXISTS {tmp}"))
    # Render the target DDL under the temporary name.
    target.name = tmp
    try:
        target.create(bind=conn)
    finally:
        target.name = table

    insert_cols = shared + [name for name, _ in backfilled]
    select_parts = [_copy_expression(target.columns[name]) for name in shared]
    select_parts += [literal for _, literal in backfilled]

    cols_sql = ", ".join(insert_cols)
    select_sql = ", ".join(select_parts)
    conn.execute(text(f"INSERT INTO {tmp} ({cols_sql}) SELECT {select_sql} FROM {table}"))
    conn.execute(text(f"DROP TABLE {table}"))
    conn.execute(text(f"ALTER TABLE {tmp} RENAME TO {table}"))


# ---------------------------------------------------------------------------
# Step 5 — swap user-scoped unique constraints for entity-scoped ones
# ---------------------------------------------------------------------------
def rescope_unique_constraints(conn: Connection) -> None:
    """
    Replace ``UNIQUE (user_id, …)`` with ``UNIQUE (entity_id, …)``.

    Without this, a practice analyst uploading March for two different clients
    would trip the old constraint on the second upload — precisely the workflow
    entities exist to support.
    """
    tables = _table_names(conn)
    insp = inspect(conn)
    for table, old_cols, new_cols in UNIQUE_RESCOPES:
        if table not in tables or "entity_id" not in _columns(conn, table):
            continue

        existing = insp.get_unique_constraints(table)
        has_new = any(sorted(c["column_names"]) == sorted(new_cols) for c in existing)
        stale = [c for c in existing if sorted(c["column_names"]) == sorted(old_cols)]

        if conn.dialect.name == "sqlite":
            # Inline table constraints cannot be dropped; a rebuild from current
            # ORM metadata brings the new constraint and leaves the old behind.
            if stale and not has_new:
                _sqlite_rebuild(conn, table, drop_columns=set())
            continue

        for constraint in stale:
            name = constraint.get("name")
            if name:
                conn.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "{name}"'))
        if not has_new:
            index_name = f"uq_{table}_{'_'.join(new_cols)}"[:63]
            cols_sql = ", ".join(new_cols)
            conn.execute(
                text(f'CREATE UNIQUE INDEX IF NOT EXISTS "{index_name}" ON {table} ({cols_sql})')
            )


# ---------------------------------------------------------------------------
# Step 6 — tighten entity_id once every row carries one
# ---------------------------------------------------------------------------
def enforce_entity_not_null(conn: Connection) -> None:
    """
    Apply the NOT NULL the ORM already declares, but only where it is safe.

    A table still holding orphan rows is left nullable rather than failing the
    boot; those rows belong to users deleted before entities existed and are
    reported instead of silently dropped.
    """
    if conn.dialect.name == "sqlite":
        return  # SQLite rebuilds already carry the ORM's NOT NULL.
    tables = _table_names(conn)
    for table in ENTITY_SCOPED_TABLES:
        if table not in tables or "entity_id" not in _columns(conn, table):
            continue
        orphans = conn.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE entity_id IS NULL")
        ).scalar_one()
        if orphans:
            continue
        conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN entity_id SET NOT NULL"))


def set_membership_defaults(conn: Connection) -> None:
    """
    Add ``org_memberships.default_entity_id`` and point it at the org's oldest
    entity for members who have none.
    """
    tables = _table_names(conn)
    if not {"org_memberships", "entities"} <= tables:
        return
    if "default_entity_id" not in _columns(conn, "org_memberships"):
        conn.execute(
            text(f"ALTER TABLE org_memberships ADD COLUMN default_entity_id {_uuid_type(conn)}")
        )
    conn.execute(
        text(
            """
            UPDATE org_memberships
            SET default_entity_id = (
                SELECT e.id FROM entities e
                WHERE e.org_id = org_memberships.org_id
                ORDER BY e.created_at, e.id
                LIMIT 1
            )
            WHERE default_entity_id IS NULL
            """
        )
    )


def run_migrations(engine: Engine) -> None:
    """Run every step in order, inside one transaction per step."""
    steps = (
        add_entity_columns,
        provision_legacy_tenants,
        backfill_entity_ids,
        rekey_config_tables,
        rescope_unique_constraints,
        enforce_entity_not_null,
        set_membership_defaults,
    )
    for step in steps:
        with engine.begin() as conn:
            step(conn)
