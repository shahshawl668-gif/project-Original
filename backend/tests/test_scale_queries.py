"""
Work that must not grow with the number of employees.

At 8,000 employees two request paths were found doing per-employee work that
belongs once per request: costing looked up PT and LWF slabs from the database
for every employee (about 30,000 queries and 30 s for cost analysis), and the
month's status hashed every input row twice. These tests pin both: the answer
is unchanged, and the repeated work is gone.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import event

from app.database import SessionLocal, engine
from app.services import analytics, run_inputs
from app.services import validation as validation_service
from app.services.validation import lookup_lwf, lookup_pt
from tests.test_cost_analysis import _dims, _register, workspace  # noqa: F401
from tests.test_coverage import BASE_ROWS, _register as _coverage_register, _run
from tests.test_run_history import PERIOD, _company, _data

MONTH = date(2026, 6, 1)
STATES = ("Karnataka", "Maharashtra")


def _import_slabs(client, headers) -> None:
    for rule_type in ("PT", "LWF"):
        r = client.post(f"/api/rule-engine/slabs/import-defaults/all?rule_type={rule_type}&overwrite=true",
                        headers=headers)
        assert r.status_code == 200, r.text


def _staff(n: int) -> list[dict]:
    # Distinct wages, crossing slab boundaries, in two states.
    return [{"employee_id": f"E{i:04d}", "basic": 6000.0 + i * 137.0,
             "dimensions": _dims(department=f"D{i % 4}", work_state=STATES[i % 2])}
            for i in range(n)]


class _SlabQueries:
    """Counts statements that read slab tables while it is open."""

    TABLES = ("slab_rules", "pt_slabs", "lwf_rates")

    def __enter__(self):
        self.count = 0
        event.listen(engine, "before_cursor_execute", self._seen)
        return self

    def _seen(self, conn, cursor, statement, *args):
        text = statement.lower()
        if text.lstrip().startswith("select") and any(f"from {t}" in text for t in self.TABLES):
            self.count += 1

    def __exit__(self, *exc):
        event.remove(engine, "before_cursor_execute", self._seen)


def test_a_shared_slab_cache_gives_the_same_answer_as_looking_up_each_time(client, workspace):
    entity, _, headers = workspace
    _import_slabs(client, headers)
    db = SessionLocal()
    try:
        cache: dict = {}
        wages = [Decimal(w) for w in ("0", "4999", "5000", "7499", "7500", "9999", "10000",
                                      "14999", "15000", "25000", "25001", "120000")]
        for state in (*STATES, "Tamil Nadu", None):
            for month in (MONTH, date(2026, 2, 1), date(2026, 12, 1)):
                for wage in wages:
                    assert lookup_pt(db, state, wage, month, entity_id=entity.id, rows_cache=cache) == \
                        lookup_pt(db, state, wage, month, entity_id=entity.id), (state, wage, month)
                    assert lookup_lwf(db, state, wage, month, entity_id=entity.id, rows_cache=cache) == \
                        lookup_lwf(db, state, wage, month, entity_id=entity.id), (state, wage, month)
    finally:
        db.close()


def test_costing_reads_the_slab_tables_a_bounded_number_of_times(client, workspace, monkeypatch):
    entity, user, headers = workspace
    _import_slabs(client, headers)
    # Basic is PT- and LWF-applicable, so every employee needs a slab lookup.
    assert client.post("/api/components", headers=headers, json={
        "component_name": "Basic", "pf_applicable": True, "esic_applicable": True,
        "pt_applicable": True, "lwf_applicable": True, "included_in_wages": True, "taxable": True,
    }).status_code == 201
    _register(entity, user, MONTH, _staff(120))

    db = SessionLocal()
    try:
        with _SlabQueries() as q:
            cached = analytics.cost_analysis(db, entity.id, group_by="department")
        # One load per (table, state) — and per month for the seeded tables —
        # however many employees there are. It was two per employee.
        assert q.count <= 8, q.count
    finally:
        db.close()

    # And the figures are exactly those of the per-employee lookups.
    monkeypatch.setattr(validation_service, "_slab_rows", lambda cache, key, load: load())
    db = SessionLocal()
    try:
        with _SlabQueries() as q:
            uncached = analytics.cost_analysis(db, entity.id, group_by="department")
        assert q.count >= 120  # the patch really did turn the cache off: per-employee again
    finally:
        db.close()
    assert cached["totals"] == uncached["totals"]
    assert cached["matrix"] == uncached["matrix"]
    assert cached["totals"]["headcount"] == 120
    assert cached["totals"]["employer_cost"] > 0


def test_the_month_status_hashes_its_inputs_once(client, monkeypatch):
    company = _company(client, "scale")
    _run(client, company, _coverage_register(BASE_ROWS))
    calls = []
    real = run_inputs.run_freshness

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(run_inputs, "run_freshness", counted)
    status = _data(client.get(f"/api/validation/periods/{PERIOD}/status", headers=company))
    assert len(calls) == 1
    # Readiness still reflects that freshness: nothing changed, so it is not a blocker.
    assert "revalidation_required" not in {b["code"] for b in status["readiness"]["blockers"]}

    # A real change still reaches both answers from the one computation.
    comps = _data(client.get("/api/components", headers=company))
    hra = next(c for c in comps if c["component_name"] == "HRA")
    assert client.patch(f"/api/components/{hra['id']}", headers=company,
                        json={"pf_applicable": True}).status_code == 200
    calls.clear()
    status = _data(client.get(f"/api/validation/periods/{PERIOD}/status", headers=company))
    assert len(calls) == 1
    assert status["stage"] == "revalidation_required"
    assert "revalidation_required" in {b["code"] for b in status["readiness"]["blockers"]}


def test_the_caller_supplied_freshness_is_ignored_for_a_different_run(client):
    from app.models import Entity
    from app.services import approvals

    company = _company(client, "scale2")
    _run(client, company, _coverage_register(BASE_ROWS))
    db = SessionLocal()
    try:
        entity = db.get(Entity, uuid.UUID(company["X-Entity-Id"]))
        wrong = (uuid.uuid4(), {"revalidation_required": True, "changes": [{"label": "planted"}]})
        out = approvals.readiness(db, entity, MONTH, known_freshness=wrong)
        assert "planted" not in str(out)
    finally:
        db.close()
