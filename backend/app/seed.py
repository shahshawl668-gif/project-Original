"""Seed reference data (PT slabs) on first startup if empty.

These rows are the *month-blind fallback* used by `lookup_pt` when a tenant has
not imported state slabs (Rule Engine → PT/LWF slabs). They must stay accurate
for the common case:

  * Maharashtra PT — ₹200/month above ₹10,000 (the February ₹300 top-up is a
    month-specific rule the tenant catalog encodes; a month-blind fallback
    must use the regular ₹200).
  * Karnataka PT — exemption raised to ₹25,000 by the April 2025 Amendment.

LWF is deliberately NOT seeded here: every state's LWF is half-yearly or
yearly, which a month-blind monthly fallback cannot represent without
producing false mismatches. Tenants get accurate LWF by importing the state
catalog (lwf_defaults) which carries frequency and employer amounts.

`_fix_legacy_reference_rows` repairs databases created by older builds that
seeded incorrect values (Maharashtra ₹300/month band, ₹15,000 Karnataka
threshold, monthly-drip LWF rates). It only touches rows that exactly match
the known-bad legacy values, so operator-edited data is never clobbered.
"""
from datetime import date
from decimal import Decimal

from pymongo.database import Database

from app.models import LwfRate, PtSlab

_TOP = 999999999


def _fix_legacy_reference_rows(db: Database) -> None:
    # Maharashtra: legacy builds seeded ₹300/month above ₹20,000 — actual
    # monthly PT is ₹200 above ₹10,000 (Feb top-up handled by tenant slabs).
    PtSlab.update_many(
        db,
        {"state": "Maharashtra", "slab_min": Decimal("20000.01"), "amount": Decimal("300")},
        {"$set": {"amount": Decimal("200")}},
    )

    # Karnataka: exemption threshold moved from ₹15,000 to ₹25,000 (Apr 2025).
    PtSlab.update_many(
        db,
        {
            "state": "Karnataka",
            "slab_min": Decimal("0"),
            "slab_max": Decimal("15000"),
            "amount": Decimal("0"),
        },
        {"$set": {"slab_max": Decimal("25000")}},
    )
    PtSlab.update_many(
        db,
        {"state": "Karnataka", "slab_min": Decimal("15000.01"), "amount": Decimal("200")},
        {"$set": {"slab_min": Decimal("25000.01")}},
    )

    # LWF: legacy monthly-drip fallback rows (₹10/₹20 MH, ₹3/₹6 KA) produce
    # false mismatches every month — remove them; the tenant catalog is the
    # accurate source.
    LwfRate.delete_many(
        db,
        {
            "state": {"$in": ["Maharashtra", "Karnataka"]},
            "employee_rate": {"$in": [Decimal("10"), Decimal("3")]},
            "employer_rate": {"$in": [Decimal("20"), Decimal("6")]},
        },
    )


def seed_reference_data(db: Database) -> None:
    _fix_legacy_reference_rows(db)

    if PtSlab.count(db) == 0:
        slabs = [
            ("Maharashtra", 0, 7500, 0),
            ("Maharashtra", 7500.01, 10000, 175),
            ("Maharashtra", 10000.01, _TOP, 200),
            ("Karnataka", 0, 25000, 0),
            ("Karnataka", 25000.01, _TOP, 200),
        ]
        PtSlab.insert_many(
            db,
            [
                PtSlab(
                    state=state,
                    slab_min=Decimal(str(lo)),
                    slab_max=Decimal(str(hi)),
                    amount=Decimal(str(amt)),
                    effective_from=date(2024, 4, 1),
                )
                for state, lo, hi, amt in slabs
            ],
        )
