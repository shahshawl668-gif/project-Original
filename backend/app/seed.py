"""Seed reference data (PT slabs) on first startup if empty.

These rows are the *month-blind fallback* used by `lookup_pt` when a tenant
has not imported state slabs (Rule Engine → PT/LWF slabs). They must stay
accurate for the common case:

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

from sqlalchemy.orm import Session

from app.models import LwfRate, PtSlab

_TOP = 999999999


def _fix_legacy_reference_rows(db: Session) -> None:
    changed = False

    # Maharashtra: legacy builds seeded ₹300/month above ₹20,000 — actual
    # monthly PT is ₹200 above ₹10,000 (Feb top-up handled by tenant slabs).
    bad_mh = (
        db.query(PtSlab)
        .filter(
            PtSlab.state == "Maharashtra",
            PtSlab.slab_min == Decimal("20000.01"),
            PtSlab.amount == Decimal("300"),
        )
        .all()
    )
    for row in bad_mh:
        row.amount = Decimal("200")
        changed = True

    # Karnataka: exemption threshold moved from ₹15,000 to ₹25,000 (Apr 2025).
    ka_exempt = (
        db.query(PtSlab)
        .filter(
            PtSlab.state == "Karnataka",
            PtSlab.slab_min == Decimal("0"),
            PtSlab.slab_max == Decimal("15000"),
            PtSlab.amount == Decimal("0"),
        )
        .all()
    )
    for row in ka_exempt:
        row.slab_max = Decimal("25000")
        changed = True
    ka_taxed = (
        db.query(PtSlab)
        .filter(
            PtSlab.state == "Karnataka",
            PtSlab.slab_min == Decimal("15000.01"),
            PtSlab.amount == Decimal("200"),
        )
        .all()
    )
    for row in ka_taxed:
        row.slab_min = Decimal("25000.01")
        changed = True

    # LWF: legacy monthly-drip fallback rows (₹10/₹20 MH, ₹3/₹6 KA) produce
    # false mismatches every month — remove them; the tenant catalog is the
    # accurate source.
    legacy_lwf = (
        db.query(LwfRate)
        .filter(
            LwfRate.state.in_(["Maharashtra", "Karnataka"]),
            LwfRate.employee_rate.in_([Decimal("10"), Decimal("3")]),
            LwfRate.employer_rate.in_([Decimal("20"), Decimal("6")]),
        )
        .all()
    )
    for row in legacy_lwf:
        db.delete(row)
        changed = True

    if changed:
        db.commit()


def seed_reference_data(db: Session) -> None:
    _fix_legacy_reference_rows(db)

    if db.query(PtSlab).count() == 0:
        slabs = [
            ("Maharashtra", 0, 7500, 0),
            ("Maharashtra", 7500.01, 10000, 175),
            ("Maharashtra", 10000.01, _TOP, 200),
            ("Karnataka", 0, 25000, 0),
            ("Karnataka", 25000.01, _TOP, 200),
        ]
        for state, lo, hi, amt in slabs:
            db.add(
                PtSlab(
                    state=state,
                    slab_min=Decimal(str(lo)),
                    slab_max=Decimal(str(hi)),
                    amount=Decimal(str(amt)),
                    effective_from=date(2024, 4, 1),
                )
            )

    db.commit()
