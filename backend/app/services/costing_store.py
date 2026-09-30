"""
Costed register rows, stored per register and reused while their basis holds.

Costing a row (services/cost_model.py) reads the row, the company's component,
PF, ESI and PT/LWF configuration, the employee's PF flag from the master, and
the code that does the arithmetic. At 8,000 employees that was seconds of CPU
on every cost page, month close and Control Centre view, for figures that only
change when one of those inputs does.

So each register's costing is stored with a digest of exactly that basis:

* the configuration the costing context loaded — components, PF and ESI
  configuration, statutory settings, the company's slab rules and the shared
  PT/LWF schedules;
* the PF flag of every employee in the master as at the month;
* the source of every module that takes part in the arithmetic;
* the revision of the company's register rows, which every write to a row
  moves (services/input_revisions.py), and the rows themselves by id.

A stored costing is used only when all of these match; otherwise the register
is costed afresh and the result stored for next time. The figures are the ones
``CostContext.cost_row`` returns, to the paisa — tests/test_scale_queries.py
compares every measure of every row, stored and recomputed.
"""
from __future__ import annotations

import json
import uuid
import zlib
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    EmployeeRecord,
    LwfRate,
    PtSlab,
    RegisterCosting,
    SalaryRegisterRow,
    SlabRule,
    StatutoryConfig,
)

#: Every module whose code decides a costed figure.
COST_SOURCES = (
    "services/cost_model.py",
    "services/costing_store.py",
    "services/pf_engine.py",
    "services/esic_engine.py",
    "services/pf_basis.py",
    "services/payroll_parse.py",
    "services/validation.py",
    "services/config_service.py",
    "schemas/statutory_config.py",
    "migrations.py",
    "database.py",
)
PAYLOAD_VERSION = 1


def configuration_basis(db: Session, context: Any) -> str:
    """Digest of the configuration a ``CostContext`` costs with."""
    from app.services.input_revisions import source_digest
    from app.services.run_inputs import _rows, digest, row_as_data

    from app.services.input_revisions import revision

    eid = context.entity_id
    statutory = db.get(StatutoryConfig, eid)
    return digest({
        "code": source_digest(*COST_SOURCES),
        # Read first: the rows costed later are never older than this.
        "register_rows": revision(db, eid, "register_rows"),
        "components": _rows(list(context.components)),
        "pf": context.pf_cfg.model_dump(mode="json"),
        "esic": context.esic_cfg.model_dump(mode="json"),
        "pt_states": sorted(context.pt_states),
        "lwf_states": sorted(context.lwf_states),
        "default_pt_state": context.default_pt_state,
        "default_lwf_state": context.default_lwf_state,
        "statutory_config": row_as_data(statutory) if statutory else None,
        "slab_rules": _rows(db.query(SlabRule).filter(SlabRule.entity_id == eid).all()),
        "reference_pt": _rows(db.query(PtSlab).all()),
        "reference_lwf": _rows(db.query(LwfRate).all()),
    })


def pf_flags_as_of(db: Session, entity_id: uuid.UUID, as_of: date) -> dict[str, bool | None]:
    """Each employee's PF flag in the master as at ``as_of``.

    The same resolution as ``workforce.master_as_of`` — the newest version
    effective on or before the date — reading two columns instead of whole rows.
    """
    flags: dict[str, bool | None] = {}
    for employee_id, flag in (
        db.query(EmployeeRecord.employee_id, EmployeeRecord.pf_restricted)
        .filter(EmployeeRecord.entity_id == entity_id, EmployeeRecord.effective_from <= as_of)
        .order_by(EmployeeRecord.employee_id, EmployeeRecord.effective_from)
    ):
        flags[employee_id] = flag
    return flags


def register_basis(config_basis: str, flags: dict[str, bool | None]) -> str:
    from app.services.run_inputs import digest

    return digest({"configuration": config_basis, "pf_flags": flags})


def encode(costs: dict[uuid.UUID, Any], keys: list[str]) -> bytes:
    rows = {
        row_id.hex: [[str(cost.measures[k]) for k in keys], sorted(cost.reported_keys)]
        for row_id, cost in costs.items()
    }
    text = json.dumps({"v": PAYLOAD_VERSION, "keys": keys, "rows": rows}, separators=(",", ":"))
    return zlib.compress(text.encode("utf-8"), 6)


def decode(payload: bytes) -> dict[str, Any] | None:
    from app.services.cost_model import RowCost

    data = json.loads(zlib.decompress(payload).decode("utf-8"))
    if data.get("v") != PAYLOAD_VERSION:
        return None
    keys = data["keys"]
    return {
        row_hex: RowCost(
            measures={k: Decimal(v) for k, v in zip(keys, values)},
            reported_keys=set(reported),
        )
        for row_hex, (values, reported) in data["rows"].items()
    }


def load(db: Session, register_id: uuid.UUID, basis: str) -> dict[str, Any] | None:
    stored = (
        db.query(RegisterCosting.basis_digest, RegisterCosting.payload)
        .filter(RegisterCosting.register_id == register_id)
        .first()
    )
    if stored is None or stored.basis_digest != basis:
        return None
    return decode(stored.payload)


def cost_register(
    db: Session, context: Any, register_id: uuid.UUID, flags: dict[str, bool | None]
) -> dict[uuid.UUID, Any]:
    """Cost every row of one register, exactly as ``cost_row`` does."""
    rows = db.query(SalaryRegisterRow).filter(SalaryRegisterRow.register_id == register_id).all()
    return {row.id: context.cost_row(row, pf_restricted=flags.get(row.employee_id)) for row in rows}


def store(db: Session, register_id: uuid.UUID, basis: str, costs: dict[uuid.UUID, Any]) -> None:
    from app.services.cost_model import ALL_MEASURE_KEYS
    from app.database import write_aside

    keys = [k for k in ALL_MEASURE_KEYS if costs and k in next(iter(costs.values())).measures]
    payload = encode(costs, keys)

    def _write(side: Session) -> None:
        side.query(RegisterCosting).filter(RegisterCosting.register_id == register_id).delete(
            synchronize_session=False
        )
        side.add(RegisterCosting(
            register_id=register_id, basis_digest=basis, row_count=len(costs), payload=payload,
        ))

    write_aside(db, _write)
