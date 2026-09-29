"""Recording a run the way the product does, for tests that build findings by hand.

A run recorded without its input fingerprints is, correctly, never current:
approval refuses it as "predates input tracking". Tests that simulate a
validation must therefore record what a real one records.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from app.models import Entity
from app.services import finding_store, run_inputs


def record_fresh_run(db, *, entity_id: uuid.UUID, user_id: uuid.UUID, period: date,
                     findings: list[dict[str, Any]], employee_count: int):
    entity = db.get(Entity, entity_id)
    config = run_inputs.configuration_snapshot(db, entity, period)
    digests = run_inputs.input_digests(db, entity, period, rows_sha256=None, config=config)
    return finding_store.record_run(
        db, entity_id=entity_id, user_id=user_id, period_month=period,
        findings=findings, employee_count=employee_count,
        input_digests=digests, config_snapshot=config,
    )
