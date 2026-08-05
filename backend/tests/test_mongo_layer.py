"""Document layer: BSON round-tripping, queries, and seeding on MongoDB."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.models import (
    ComponentConfig,
    CtcRecord,
    PtSlab,
    SalaryRegister,
    SalaryRegisterRow,
    SlabRule,
    StatutoryConfig,
    User,
)
from app.seed import seed_reference_data
from app.services.config_service import ConfigService


# ── type round-tripping ──────────────────────────────────────────────────────

def test_uuid_decimal_date_round_trip(mongo_db):
    """Money must survive as Decimal, ids as UUID, and dates as date."""
    row = SlabRule(
        user_id=uuid.uuid4(),
        state="Maharashtra",
        rule_type="PT",
        min_salary=Decimal("10000.01"),
        max_salary=Decimal("999999999"),
        deduction_amount=Decimal("200.50"),
        employer_amount=None,
        applicable_months=[2],
    )
    row.insert(mongo_db)

    loaded = SlabRule.find_one(mongo_db, {"_id": row.id})
    assert isinstance(loaded.id, uuid.UUID) and loaded.id == row.id
    assert isinstance(loaded.user_id, uuid.UUID) and loaded.user_id == row.user_id
    assert isinstance(loaded.deduction_amount, Decimal)
    # Exactness matters: 200.50 must not become 200.49999999999997
    assert loaded.deduction_amount == Decimal("200.50")
    assert loaded.min_salary == Decimal("10000.01")
    assert loaded.employer_amount is None
    assert loaded.applicable_months == [2]


def test_date_fields_round_trip_as_date(mongo_db):
    reg = SalaryRegister(user_id=uuid.uuid4(), period_month=date(2026, 4, 1), employee_count=3)
    reg.insert(mongo_db)
    loaded = SalaryRegister.find_one(mongo_db, {"_id": reg.id})
    assert loaded.period_month == date(2026, 4, 1)
    assert isinstance(loaded.period_month, date)


def test_nested_dicts_preserved(mongo_db):
    row = SalaryRegisterRow(
        register_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        period_month=date(2026, 4, 1),
        employee_id="E1",
        components={"basic": 20000.0, "hra": 8000.0},
        arrears={"basic": 500.0},
        paid_days=Decimal("30"),
        increment_arrear_total=Decimal("500"),
    )
    row.insert(mongo_db)
    loaded = SalaryRegisterRow.find_one(mongo_db, {"employee_id": "E1"})
    assert loaded.components == {"basic": 20000.0, "hra": 8000.0}
    assert loaded.arrears == {"basic": 500.0}
    assert loaded.paid_days == Decimal("30")


# ── queries ──────────────────────────────────────────────────────────────────

def test_filters_encode_native_types(mongo_db):
    uid = uuid.uuid4()
    for name in ("basic", "hra"):
        ComponentConfig(user_id=uid, component_name=name, included_in_wages=True).insert(mongo_db)
    ComponentConfig(user_id=uuid.uuid4(), component_name="other").insert(mongo_db)

    # A UUID in the filter must match the stored (string-encoded) value.
    mine = ComponentConfig.find_many(mongo_db, {"user_id": uid}, sort=[("component_name", 1)])
    assert [c.component_name for c in mine] == ["basic", "hra"]
    assert ComponentConfig.count(mongo_db, {"user_id": uid}) == 2


def test_date_range_and_or_filter(mongo_db):
    PtSlab(
        state="Maharashtra",
        slab_min=Decimal("0"),
        slab_max=Decimal("10000"),
        amount=Decimal("0"),
        effective_from=date(2024, 4, 1),
    ).insert(mongo_db)
    PtSlab(
        state="Maharashtra",
        slab_min=Decimal("10000.01"),
        slab_max=Decimal("999999999"),
        amount=Decimal("200"),
        effective_from=date(2024, 4, 1),
        effective_to=date(2025, 3, 31),
    ).insert(mongo_db)

    as_of = date(2026, 4, 1)
    live = PtSlab.find_many(
        mongo_db,
        {
            "state": "Maharashtra",
            "effective_from": {"$lte": as_of},
            "$or": [{"effective_to": None}, {"effective_to": {"$gte": as_of}}],
        },
    )
    # Only the open-ended row is still effective in Apr 2026.
    assert len(live) == 1
    assert live[0].amount == Decimal("0")


def test_sort_limit_and_delete(mongo_db):
    uid = uuid.uuid4()
    for i, eff in enumerate([date(2025, 4, 1), date(2026, 4, 1), date(2024, 4, 1)]):
        CtcRecord(
            user_id=uid,
            employee_id="E1",
            effective_from=eff,
            annual_components={"basic": 100 + i},
        ).insert(mongo_db)

    latest = CtcRecord.find_many(
        mongo_db, {"user_id": uid, "employee_id": "E1"}, sort=[("effective_from", -1)], limit=2
    )
    assert [r.effective_from for r in latest] == [date(2026, 4, 1), date(2025, 4, 1)]

    assert CtcRecord.delete_many(mongo_db, {"user_id": uid}) == 3
    assert CtcRecord.count(mongo_db, {"user_id": uid}) == 0


def test_save_upserts_and_updates(mongo_db):
    user = User(email="a@example.com", password_hash="x", role="user")
    user.insert(mongo_db)
    user.role = "admin"
    user.save(mongo_db)

    assert User.count(mongo_db, {}) == 1
    assert User.find_one(mongo_db, {"email": "a@example.com"}).role == "admin"


def test_distinct_states(mongo_db):
    uid = uuid.uuid4()
    for state in ("Maharashtra", "Karnataka", "Maharashtra"):
        SlabRule(user_id=uid, state=state, rule_type="PT").insert(mongo_db)
    states = SlabRule.distinct(mongo_db, "state", {"user_id": uid, "rule_type": "PT"})
    assert sorted(states) == ["Karnataka", "Maharashtra"]


# ── seeding + config service ─────────────────────────────────────────────────

def test_seed_is_idempotent_and_accurate(mongo_db):
    seed_reference_data(mongo_db)
    first = PtSlab.count(mongo_db, {})
    seed_reference_data(mongo_db)
    assert PtSlab.count(mongo_db, {}) == first

    # Money fields are sorted in Python (see lookup_pt) — numerically, not
    # lexicographically, which is the bug this ordering guards against.
    mh = sorted(PtSlab.find_many(mongo_db, {"state": "Maharashtra"}), key=lambda r: r.slab_min)
    assert [float(r.slab_min) for r in mh] == [0.0, 7500.01, 10000.01]
    assert [float(r.amount) for r in mh] == [0.0, 175.0, 200.0]
    ka = sorted(PtSlab.find_many(mongo_db, {"state": "Karnataka"}), key=lambda r: r.slab_min)
    assert float(ka[0].slab_max) == 25000.0  # post-Apr-2025 exemption


def test_money_ordering_is_numeric_not_lexicographic(mongo_db):
    """Regression: string-encoded decimals ordered "10000.01" before "7500.01"."""
    for lo in ("0", "7500.01", "10000.01", "999999"):
        PtSlab(
            state="Test",
            slab_min=Decimal(lo),
            slab_max=Decimal("999999999"),
            amount=Decimal("0"),
            effective_from=date(2024, 4, 1),
        ).insert(mongo_db)

    rows = sorted(PtSlab.find_many(mongo_db, {"state": "Test"}), key=lambda r: r.slab_min)
    assert [float(r.slab_min) for r in rows] == [0.0, 7500.01, 10000.01, 999999.0]


def test_seed_repairs_legacy_rows(mongo_db):
    """A database seeded by an older build is corrected in place."""
    PtSlab(
        state="Maharashtra",
        slab_min=Decimal("20000.01"),
        slab_max=Decimal("999999999"),
        amount=Decimal("300"),
        effective_from=date(2024, 4, 1),
    ).insert(mongo_db)
    seed_reference_data(mongo_db)
    fixed = PtSlab.find_one(mongo_db, {"state": "Maharashtra", "slab_min": Decimal("20000.01")})
    assert fixed.amount == Decimal("200")


def test_config_service_persists_nested_config(mongo_db):
    tenant = uuid.uuid4()
    svc = ConfigService(mongo_db)

    pf = svc.get_pf_config(tenant)
    assert pf.wage.wage_ceiling == Decimal("15000")

    pf.wage.wage_ceiling = Decimal("25000")
    svc.save_pf_config(tenant, pf)

    # A fresh service instance (no memoised cache) must read the stored value.
    assert ConfigService(mongo_db).get_pf_config(tenant).wage.wage_ceiling == Decimal("25000")
    assert StatutoryConfig.count(mongo_db, {"user_id": tenant}) == 1


def test_income_tax_and_thresholds_survive_round_trip(mongo_db):
    tenant = uuid.uuid4()
    svc = ConfigService(mongo_db)

    cfg = svc.get_income_tax_config(tenant)
    assert "2026-27" in cfg.years
    cfg.years["2026-27"].cess_rate = Decimal("0.05")
    svc.save_income_tax_config(tenant, cfg)

    reloaded = ConfigService(mongo_db).get_tax_year(tenant, "2026-27")
    assert reloaded.cess_rate == Decimal("0.05")

    thr = svc.get_rule_thresholds(tenant)
    thr.tolerances.gross_mismatch = Decimal("50")
    svc.save_rule_thresholds(tenant, thr)
    assert ConfigService(mongo_db).get_rule_thresholds(tenant).tolerances.gross_mismatch == Decimal("50")
