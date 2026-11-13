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


def _correct_odisha_pt(db: Session) -> None:
    """Bring companies that loaded Odisha PT before November 2026 up to the law.

    Two things the earlier bundled schedule lacked:

    * the ₹300 March row (above ₹3 lakh: ₹200 for eleven months, ₹300 in March),
      so a correct March deduction read as an error. Added only where the
      schedule still holds exactly the bundled ₹2,400 row and no March row;
    * the repeal. Odisha levies no professional tax from 1 April 2026, so a
      nil row dated from then is added where the company has no row of its own
      dated on or after it.

    A change to a client's schedule that nobody at the client made is written
    to the client's own audit trail. Idempotent; anything an operator dated or
    edited themselves is left alone.
    """
    from app.models import SlabRule
    from app.services import audit
    from app.services.pt_defaults import ODISHA_PT_RATE_CHART, ODISHA_PT_REPEAL_SOURCE, ODISHA_PT_REPEALED_FROM

    rows = db.query(SlabRule).filter(SlabRule.rule_type == "PT", SlabRule.state == "Odisha").all()
    by_entity: dict = {}
    for row in rows:
        by_entity.setdefault(row.entity_id, []).append(row)
    changed = False
    for entity_id, schedule in by_entity.items():
        order = max((r.sort_order or 0) for r in schedule)
        for top in schedule:
            if (top.min_salary == Decimal("300001") and top.deduction_amount == Decimal("2400")
                    and top.frequency == "yearly" and not top.applicable_months
                    and not any(r.applicable_months and 3 in r.applicable_months
                                and r.effective_from == top.effective_from for r in schedule)):
                order += 1
                db.add(SlabRule(
                    user_id=top.user_id, entity_id=entity_id, state="Odisha", rule_type="PT",
                    min_salary=top.min_salary, max_salary=top.max_salary, deduction_amount=Decimal("3600"),
                    employer_amount=top.employer_amount, frequency="yearly", gender=top.gender or "ALL",
                    applicable_months=[3], effective_from=top.effective_from, effective_to=top.effective_to,
                    source_reference=ODISHA_PT_RATE_CHART, sort_order=order,
                ))
                audit.record(
                    db, entity_id=entity_id, user=None,
                    action="slab_rule.platform_correction", object_type="slab_rule", object_id=str(top.id),
                    summary="Odisha PT: added the March row (₹300) the bundled schedule was missing",
                    detail={"state": "Odisha", "rule_type": "PT", "applicable_months": [3],
                            "deduction_amount_yearly": "3600", "source": ODISHA_PT_RATE_CHART},
                )
                changed = True
        if not any(r.effective_from and r.effective_from >= ODISHA_PT_REPEALED_FROM for r in schedule):
            first = schedule[0]
            db.add(SlabRule(
                user_id=first.user_id, entity_id=entity_id, state="Odisha", rule_type="PT",
                min_salary=Decimal("0"), max_salary=Decimal("99999999"), deduction_amount=Decimal("0"),
                frequency="yearly", gender="ALL", effective_from=ODISHA_PT_REPEALED_FROM,
                source_reference=ODISHA_PT_REPEAL_SOURCE, sort_order=order + 1,
            ))
            audit.record(
                db, entity_id=entity_id, user=None,
                action="slab_rule.platform_correction", object_type="slab_rule", object_id=str(first.id),
                summary="Odisha PT: nil from 1 April 2026 (professional tax repealed)",
                detail={"state": "Odisha", "rule_type": "PT", "effective_from": str(ODISHA_PT_REPEALED_FROM),
                        "source": ODISHA_PT_REPEAL_SOURCE},
            )
            changed = True
    if changed:
        db.commit()


def seed_reference_data(db: Session) -> None:
    _fix_legacy_reference_rows(db)
    _correct_odisha_pt(db)

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
