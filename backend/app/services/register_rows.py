"""Rebuild the employee records validation reads, from the stored register.

The synchronous endpoint validates whatever the browser posted. A background
worker cannot: the browser is long gone by the time the job runs. It validates
the register that was *stored*, which is the better answer anyway — it closes
the gap where the two could differ, and it makes a retry re-read the same rows
rather than need a payload nobody kept.

Storing a register decomposes each flat row into components, arrears,
deductions and dimensions. This puts it back together. The reconstruction is
deliberately lossy in one direction only: columns the product never reads are
not preserved, because they were never stored. Everything validation *does*
read is, and `test_register_rows.py` proves it by validating the same register
both ways and comparing the findings.

Two details that would be silent bugs if missed:

* ``Unassigned`` is a display value, not data. A dimension the master never
  supplied is stored as ``Unassigned`` so cost breakdowns always sum to the
  whole; handing that back as ``work_state`` would have the PT lookup search
  for a state called Unassigned instead of reporting that it could not tell.
* An absent deduction and a zero one mean different things. A register that
  never mentioned ESI must not come back looking like one that deducted nothing,
  so only the measures actually captured are re-emitted.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.register import SalaryRegister, SalaryRegisterRow
from app.services.cost_model import REPORTED_COLUMNS
from app.services.dimensions import ROW_FALLBACKS, UNASSIGNED
from app.services.rule_engine_v2 import is_unmapped_column

#: The alias each stored measure is written back under. First in the tuple, so
#: the column name a reader sees is the one the product documents.
_REPORTED_ALIAS = {measure: aliases[0] for measure, aliases in REPORTED_COLUMNS.items()}

#: Likewise for dimensions: the canonical register column for each.
_DIMENSION_ALIAS = {key: aliases[0] for key, aliases in ROW_FALLBACKS.items()}

#: The column ``pf_basis.from_row`` reads first.
_PF_RESTRICTED_KEY = "pf_restricted"


def row_to_employee(row: SalaryRegisterRow) -> dict[str, Any]:
    """One stored row, in the shape ``validate_employees`` expects."""
    emp: dict[str, Any] = {"employee_id": row.employee_id}
    if row.employee_name:
        emp["employee_name"] = row.employee_name

    # Earnings, exactly as they were split on the way in.
    for key, value in (row.components or {}).items():
        emp[key] = float(value)
    for base, value in (row.arrears or {}).items():
        emp[f"{base}_arrear"] = float(value)
    if row.increment_arrear_total:
        total = float(row.increment_arrear_total)
        if total:
            emp["increment_arrear"] = total

    # Attendance.
    if row.paid_days is not None:
        emp["paid_days"] = float(row.paid_days)
    if row.lop_days is not None:
        emp["lop_days"] = float(row.lop_days)

    # Reporting attributes. Unassigned is the absence of a value, not a value.
    for key, value in (row.dimensions or {}).items():
        if value in (None, "", UNASSIGNED):
            continue
        emp[_DIMENSION_ALIAS.get(key, key)] = value

    # What the register said it deducted. Only what it actually stated.
    for measure, value in (row.deductions or {}).items():
        alias = _REPORTED_ALIAS.get(measure)
        if alias is not None:
            emp[alias] = float(value)

    if row.pf_restricted is not None:
        emp[_PF_RESTRICTED_KEY] = bool(row.pf_restricted)
    if row.net_pay is not None:
        emp["net_pay"] = float(row.net_pay)

    return emp


def load_employees(
    db: Session,
    register_id: uuid.UUID,
    comp_by_key: dict | None = None,
) -> list[dict[str, Any]]:
    """Every employee on one register, ordered so a retry validates in the same order.

    Ordered by ``employee_id`` rather than insertion: findings are compared
    across runs, and a diff that moves because the database returned rows in a
    different order is a diff nobody can read.

    ``comp_by_key`` lets the caller pass the entity's configured components. With
    it, columns the upload carried but the product ignores are put back as empty
    keys, so COMP-001 still reports them. Without it they stay dropped — which is
    the right default for a caller that only wants the figures.
    """
    rows = (
        db.query(SalaryRegisterRow)
        .filter(SalaryRegisterRow.register_id == register_id)
        .order_by(SalaryRegisterRow.employee_id)
        .all()
    )
    employees = [row_to_employee(row) for row in rows]

    if comp_by_key is not None:
        register = db.get(SalaryRegister, register_id)
        # NULL means the register predates this being recorded, which is not the
        # same as "the file had no extra columns". Adding nothing is the honest
        # response; inventing a clean bill of health is not.
        for name in (getattr(register, "source_columns", None) or []):
            if not is_unmapped_column(name, comp_by_key):
                continue
            key = str(name).strip().lower().replace(" ", "_")
            for employee in employees:
                employee.setdefault(key, None)

    return employees


def count_employees(db: Session, register_id: uuid.UUID) -> int:
    """How many rows the job will work through, for progress before loading them."""
    return (
        db.query(SalaryRegisterRow)
        .filter(SalaryRegisterRow.register_id == register_id)
        .count()
    )
