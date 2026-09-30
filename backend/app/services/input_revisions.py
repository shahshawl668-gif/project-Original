"""
Revisions for the inputs a validation run is fingerprinted on.

Whether a run is still current is decided by digesting the master, CTC,
attendance and previous register it read (services/run_inputs.py). Digesting
8,000 rows of each on every page load cost more than a second, so a digest is
cached against the input's *revision* — a token that every write to the input
replaces, in the same transaction as the write.

The token moves on any change the ORM sees: a row added, changed or deleted, or
the upload or register that owns it, for the company it belongs to. A bulk
``UPDATE``/``DELETE`` statement or a deleted user cannot always be tied to one
company, so those move a shared ``*`` revision that invalidates every company's
cached digest for that input. Being wrong in the safe direction costs a
recompute; being wrong the other way would call a stale run current, which is
the one answer this product must never give.

Raw SQL that bypasses the ORM does not move a token. The only such writes are
schema migrations, and the cache key includes the migration code's own digest,
so a release that adds one recomputes everything.
"""
from __future__ import annotations

import hashlib
import uuid
from functools import lru_cache
from itertools import chain
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import event, func
from sqlalchemy.orm import Session

from app.models import (
    AttendanceRegister,
    AttendanceRow,
    CtcRecord,
    CtcUpload,
    EmployeeMasterUpload,
    EmployeeRecord,
    InputRevision,
    SalaryRegister,
    SalaryRegisterRow,
    User,
)

#: Which input each mapped class belongs to. Owners are listed with their rows:
#: deleting an upload deletes its rows by cascade, possibly in the database.
TRACKED: dict[type, str] = {
    EmployeeRecord: "master",
    EmployeeMasterUpload: "master",
    CtcRecord: "ctc",
    CtcUpload: "ctc",
    AttendanceRow: "attendance",
    AttendanceRegister: "attendance",
    SalaryRegisterRow: "register_rows",
    SalaryRegister: "register_rows",
}
INPUT_KEYS = tuple(sorted(set(TRACKED.values())))
ANY_COMPANY = "*"


@lru_cache(maxsize=None)
def source_digest(*relative_paths: str) -> str:
    """Digest of source files under ``app/``, so a release that changes how a
    cached value is computed invalidates what the old code stored."""
    root = Path(__file__).resolve().parent.parent
    h = hashlib.sha256()
    for rel in relative_paths:
        h.update(rel.encode())
        h.update((root / rel).read_bytes())
    return h.hexdigest()


def _upsert(connection: Any, pairs: Iterable[tuple[str, str]]) -> None:
    table = InputRevision.__table__
    dialect = connection.dialect.name
    for scope, key in sorted(set(pairs)):
        token = uuid.uuid4().hex
        if dialect in ("postgresql", "sqlite"):
            if dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            else:
                from sqlalchemy.dialects.sqlite import insert
            stmt = insert(table).values(scope=scope, input_key=key, token=token)
            stmt = stmt.on_conflict_do_update(
                index_elements=["scope", "input_key"],
                set_={"token": token, "updated_at": func.now()},
            )
            connection.execute(stmt)
            continue
        updated = connection.execute(
            table.update()
            .where(table.c.scope == scope, table.c.input_key == key)
            .values(token=token, updated_at=func.now())
        ).rowcount
        if not updated:
            connection.execute(table.insert().values(scope=scope, input_key=key, token=token))


def touched_by(session: Session) -> set[tuple[str, str]]:
    touched: set[tuple[str, str]] = set()
    for obj in chain(session.new, session.dirty, session.deleted):
        key = TRACKED.get(type(obj))
        if key is not None:
            entity_id = getattr(obj, "entity_id", None)
            touched.add((str(entity_id) if entity_id else ANY_COMPANY, key))
        elif isinstance(obj, User) and obj in session.deleted:
            # Every input row carries user_id ON DELETE CASCADE.
            touched.update((ANY_COMPANY, k) for k in INPUT_KEYS)
    return touched


@event.listens_for(Session, "after_flush")
def _after_flush(session: Session, flush_context: Any) -> None:
    # The pre-flush new/dirty/deleted sets are still readable here.
    touched = touched_by(session)
    if touched:
        _upsert(session.connection(), touched)


@event.listens_for(Session, "do_orm_execute")
def _bulk_statement(state: Any) -> None:
    if not (state.is_update or state.is_delete):
        return
    mapper = state.bind_mapper
    key = TRACKED.get(mapper.class_) if mapper is not None else None
    if key is not None:
        _upsert(state.session.connection(), [(ANY_COMPANY, key)])


def revision(db: Session, entity_id: uuid.UUID, input_key: str) -> str:
    """The revision a digest of this company's input is valid for."""
    scope = str(entity_id)
    tokens = dict(
        db.query(InputRevision.scope, InputRevision.token)
        .filter(InputRevision.input_key == input_key, InputRevision.scope.in_([scope, ANY_COMPANY]))
        .all()
    )
    return f"{tokens.get(scope, '-')}:{tokens.get(ANY_COMPANY, '-')}"

