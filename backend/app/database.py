from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = settings.database_url
    if url.startswith("sqlite"):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
    # Postgres / other servers — production pool tuning.
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
        pool_recycle=1800,
        pool_timeout=30,
        future=True,
    )


engine = _make_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Lightweight schema patcher
# ---------------------------------------------------------------------------
# `Base.metadata.create_all` only creates *missing tables*; it does NOT add
# new columns to an existing table. For the SQLite-based local-dev workflow
# we don't want to force users to delete `payroll_dev.db` every time we add a
# column, so we run a tiny "ALTER TABLE ADD COLUMN IF MISSING" pass on
# startup. Only additive changes are supported here — anything destructive
# still requires a real migration.

_COLUMN_PATCHES: list[tuple[str, str, str]] = [
    # (table, column, DDL fragment after `ADD COLUMN`)
    ("users", "role", "VARCHAR(32) NOT NULL DEFAULT 'user'"),
    ("slab_rules", "gender", "VARCHAR(8) NOT NULL DEFAULT 'ALL'"),
    ("slab_rules", "applicable_months", "TEXT"),
    ("slab_rules", "employer_amount", "NUMERIC(14, 2)"),
]


def apply_column_patches() -> None:
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, column, ddl in _COLUMN_PATCHES:
            if table not in existing_tables:
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            if column in cols:
                continue
            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))
