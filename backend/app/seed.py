"""Seed reference data (PT slabs, LWF rates) on first startup if empty."""
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import LwfRate, PtSlab


def seed_reference_data(db: Session) -> None:
    if db.query(PtSlab).count() == 0:
        slabs = [
            ("Maharashtra", 0, 7500, 0),
            ("Maharashtra", 7500.01, 10000, 175),
            ("Maharashtra", 10000.01, 15000, 200),
            ("Maharashtra", 15000.01, 20000, 200),
            ("Maharashtra", 20000.01, 999999999, 300),
            ("Karnataka", 0, 15000, 0),
            ("Karnataka", 15000.01, 999999999, 200),
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

    if db.query(LwfRate).count() == 0:
        rates = [
            ("Maharashtra", 0, 999999999, 10, 20),
            ("Karnataka", 0, 999999999, 3, 6),
        ]
        for state, lo, hi, emp, empr in rates:
            db.add(
                LwfRate(
                    state=state,
                    wage_band_min=Decimal(str(lo)),
                    wage_band_max=Decimal(str(hi)),
                    employee_rate=Decimal(str(emp)),
                    employer_rate=Decimal(str(empr)),
                    effective_from=date(2024, 4, 1),
                )
            )

    db.commit()
