"""Document base — dataclass ⇆ BSON mapping for the MongoDB data layer.

Why dataclasses instead of an ODM
---------------------------------
The validation engines (`validation.py`, `rule_engine_v2.py`, `pf_engine.py`,
`esic_engine.py`) read plain attributes off model objects — `component.pf_applicable`,
`row.components`, `user.id`. Keeping documents as dataclasses with the same
attribute surface means those engines are untouched by the storage change.

Queries are plain Mongo filter dicts (`{"user_id": user.id}`), not a
re-implemented query DSL. Filter values are encoded on the way in, so callers
pass native Python types (UUID, Decimal, date) and never think about BSON.

Type round-tripping
-------------------
BSON has no UUID-as-string, no exact Decimal, and no date-without-time, so:

  * `uuid.UUID`  ⇆ string        (ids stay readable in the shell and in URLs)
  * `Decimal`    ⇆ Decimal128    (exact — money must never go through a float)
  * `date`       ⇆ datetime      (midnight; BSON only has datetime)
  * `datetime`   ⇆ datetime      (native)

`Decimal128` is BSON's exact decimal type, so money keeps full precision *and*
stays numerically sortable/comparable server-side — a string encoding would
order "10000.01" before "7500.01". Note that equality filters compare the
stored representation, so `Decimal("200")` and `Decimal("200.00")` are distinct
keys; build filters from the same construction path as the writes.

Decoding is driven by each dataclass's declared field types, so a field typed
`Decimal | None` comes back as a `Decimal`, not a string.
"""
from __future__ import annotations

import types
import uuid
from dataclasses import dataclass, fields
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, ClassVar, Union, get_args, get_origin, get_type_hints

from bson.decimal128 import Decimal128
from pymongo.collection import Collection
from pymongo.database import Database


def utcnow() -> datetime:
    """Timezone-aware now() — stored natively by BSON."""
    return datetime.now(timezone.utc)


# ── type helpers ─────────────────────────────────────────────────────────────

def _unwrap_optional(tp: Any) -> Any:
    """`Decimal | None` → `Decimal`; leaves non-union types alone."""
    origin = get_origin(tp)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return tp


def encode(value: Any) -> Any:
    """Python → BSON-safe value (recurses through dicts and lists)."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return Decimal128(value)
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):  # after datetime: datetime is a date subclass
        return datetime(value.year, value.month, value.day)
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    return value


def decode(value: Any, tp: Any) -> Any:
    """BSON → Python, guided by the field's declared type."""
    if value is None:
        return None
    tp = _unwrap_optional(tp)
    if tp is uuid.UUID:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    if tp is Decimal:
        if isinstance(value, Decimal128):
            return value.to_decimal()
        return value if isinstance(value, Decimal) else Decimal(str(value))
    if tp is datetime:
        return value
    if tp is date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))
    return value


def encode_filter(filt: dict[str, Any]) -> dict[str, Any]:
    """Encode leaf values in a Mongo filter, preserving `$` operators."""
    out: dict[str, Any] = {}
    for key, val in filt.items():
        if isinstance(val, dict):
            out[key] = encode_filter(val)
        elif isinstance(val, (list, tuple)) and key in ("$in", "$nin", "$or", "$and"):
            out[key] = [encode_filter(v) if isinstance(v, dict) else encode(v) for v in val]
        else:
            out[key] = encode(val)
    return out


# ── Document base ────────────────────────────────────────────────────────────

@dataclass
class Document:
    """Base for every stored collection.

    Subclasses set `COLLECTION` and declare fields; `id` maps to Mongo's `_id`.
    """

    COLLECTION: ClassVar[str] = ""
    INDEXES: ClassVar[list[tuple[Any, dict[str, Any]]]] = []

    # ── (de)serialisation ────────────────────────────────────────────────────

    @classmethod
    def _hints(cls) -> dict[str, Any]:
        cached = cls.__dict__.get("_TYPE_HINTS")
        if cached is None:
            cached = get_type_hints(cls)
            setattr(cls, "_TYPE_HINTS", cached)
        return cached

    def to_doc(self) -> dict[str, Any]:
        doc: dict[str, Any] = {}
        for f in fields(self):
            key = "_id" if f.name == "id" else f.name
            doc[key] = encode(getattr(self, f.name))
        return doc

    @classmethod
    def from_doc(cls, doc: dict[str, Any] | None):
        if doc is None:
            return None
        hints = cls._hints()
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            key = "_id" if f.name == "id" else f.name
            if key in doc:
                kwargs[f.name] = decode(doc[key], hints.get(f.name, Any))
        return cls(**kwargs)  # type: ignore[arg-type]

    # ── collection access ────────────────────────────────────────────────────

    @classmethod
    def collection(cls, db: Database) -> Collection:
        return db[cls.COLLECTION]

    # ── queries ──────────────────────────────────────────────────────────────

    @classmethod
    def find_one(cls, db: Database, filt: dict[str, Any] | None = None, sort=None):
        kwargs: dict[str, Any] = {}
        if sort:
            kwargs["sort"] = sort
        doc = cls.collection(db).find_one(encode_filter(filt or {}), **kwargs)
        return cls.from_doc(doc)

    @classmethod
    def find_many(
        cls,
        db: Database,
        filt: dict[str, Any] | None = None,
        sort=None,
        limit: int | None = None,
    ) -> list:
        cursor = cls.collection(db).find(encode_filter(filt or {}))
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        return [cls.from_doc(d) for d in cursor]

    @classmethod
    def count(cls, db: Database, filt: dict[str, Any] | None = None) -> int:
        return cls.collection(db).count_documents(encode_filter(filt or {}))

    @classmethod
    def distinct(cls, db: Database, field: str, filt: dict[str, Any] | None = None) -> list:
        return cls.collection(db).distinct(field, encode_filter(filt or {}))

    # ── writes ───────────────────────────────────────────────────────────────

    def insert(self, db: Database):
        self.collection(db).insert_one(self.to_doc())
        return self

    def save(self, db: Database):
        """Upsert this document by `_id` (used for both create and update)."""
        if hasattr(self, "updated_at"):
            setattr(self, "updated_at", utcnow())
        doc = self.to_doc()
        self.collection(db).replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return self

    @classmethod
    def insert_many(cls, db: Database, docs: list) -> int:
        if not docs:
            return 0
        cls.collection(db).insert_many([d.to_doc() for d in docs])
        return len(docs)

    @classmethod
    def delete_many(cls, db: Database, filt: dict[str, Any]) -> int:
        return cls.collection(db).delete_many(encode_filter(filt)).deleted_count

    @classmethod
    def delete_one(cls, db: Database, filt: dict[str, Any]) -> int:
        return cls.collection(db).delete_one(encode_filter(filt)).deleted_count

    @classmethod
    def update_many(cls, db: Database, filt: dict[str, Any], update: dict[str, Any]) -> int:
        payload = {op: encode(vals) for op, vals in update.items()}
        return cls.collection(db).update_many(encode_filter(filt), payload).modified_count
