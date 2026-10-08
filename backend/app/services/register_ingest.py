"""
Taking in a salary register, from a file on screen or a batch through the API.

Moved out of the upload endpoint unchanged in behaviour, so the integration API
stores a register exactly as the screen does: the same column mapping, the
same required-column check, the same frozen upload a validation job reads, and
the same rule that only a regular run becomes the month's cost register.
"""
from __future__ import annotations

import calendar
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.models import (
    ComponentConfig,
    Entity,
    PayrollRun,
    SalaryRegister,
    SalaryRegisterRow,
    User,
)
from app.services import audit, register_uploads
from app.services.cost_model import capture_net_pay, capture_reported
from app.services.dimensions import snapshot as dimension_snapshot
from app.services.payroll_parse import (
    REGISTER_AMOUNT_FIELDS,
    apply_mapping,
    check_mapping,
    dataframe_to_employees,
    normalize_col,
    suggested_mapping,
    validate_required_columns,
)
from app.services.pf_basis import from_row as pf_flag_from_row
from app.services.validation import _component_key_map, split_row_amounts
from app.services.workforce import master_as_of
from app.services.workforce_parse import parse_decimal


def _to_first_of_month(d: date | None) -> date | None:
    return d.replace(day=1) if d is not None else None


def persist_salary_register(
    db: Session,
    user: User,
    entity: Entity,
    period_month: date,
    filename: str | None,
    employees: list[dict],
    comps: list[ComponentConfig],
    source_columns: list[str] | None = None,
) -> uuid.UUID:
    comp_by_key = _component_key_map(comps)

    # The master as it stood at period end, so each row is stamped with the
    # attributes that applied then rather than whatever they are today.
    period_end = period_month.replace(day=calendar.monthrange(period_month.year, period_month.month)[1])
    master_rows = master_as_of(db, entity.id, period_end)

    existing = (
        db.query(SalaryRegister)
        .filter(SalaryRegister.entity_id == entity.id, SalaryRegister.period_month == period_month)
        .first()
    )
    if existing:
        db.query(SalaryRegisterRow).filter(SalaryRegisterRow.register_id == existing.id).delete()
        existing.filename = filename
        existing.employee_count = len(employees)
        existing.source_columns = list(source_columns or [])
        register = existing
    else:
        register = SalaryRegister(
            user_id=user.id,
            entity_id=entity.id,
            period_month=period_month,
            filename=filename,
            employee_count=len(employees),
            source_columns=list(source_columns or []),
        )
        db.add(register)
        db.flush()

    for row in employees:
        eid = (
            row.get("employee_id")
            or row.get("emp_id")
            or row.get("employee_code")
        )
        if eid is None:
            continue
        if isinstance(eid, float) and eid == int(eid):
            eid = str(int(eid))
        eid = str(eid).strip()
        if not eid:
            continue

        ename = row.get("employee_name") or row.get("name")
        if isinstance(ename, float):
            ename = None

        regular, arrear_by_base, inc_arrear_total = split_row_amounts(row, comp_by_key)
        components_json = {k: float(v) for k, v in regular.items()}
        arrears_json = {k: float(v) for k, v in arrear_by_base.items()}
        dimensions_json = dimension_snapshot(master_rows.get(eid), row)
        # What the payroll system said it deducted and contributed, and its view
        # of this employee's PF basis. Both are captured here rather than
        # recomputed later: they are the register's own testimony about the
        # month, and a cost report built on them is one the client recognises.
        deductions_json = capture_reported(row)
        stated_net = capture_net_pay(row)
        pf_restricted_flag = pf_flag_from_row(row)

        paid_days_raw = row.get("paid_days")
        lop_days_raw = row.get("lop_days") or row.get("lop")
        try:
            paid_days = Decimal(str(paid_days_raw)) if paid_days_raw not in (None, "") else None
        except Exception:
            paid_days = None
        try:
            lop_days = Decimal(str(lop_days_raw)) if lop_days_raw not in (None, "") else None
        except Exception:
            lop_days = None

        db.add(
            SalaryRegisterRow(
                register_id=register.id,
                user_id=user.id,
                entity_id=entity.id,
                period_month=period_month,
                employee_id=eid,
                employee_name=ename if isinstance(ename, str) else None,
                paid_days=paid_days,
                lop_days=lop_days,
                components=components_json,
                dimensions=dimensions_json,
                arrears=arrears_json,
                deductions=deductions_json,
                pf_restricted=pf_restricted_flag,
                increment_arrear_total=inc_arrear_total,
                net_pay=stated_net,
            )
        )

    db.commit()
    return register.id


def amount_keys(comp_names: set[str]) -> set[str]:
    """The register fields that must hold numbers: components, their arrears, and the standard amounts."""
    components = {normalize_col(c) for c in comp_names}
    return components | {f"{c}_arrear" for c in components} | set(REGISTER_AMOUNT_FIELDS)


def read_amounts(rows: list[dict[str, Any]], keys: set[str]) -> list[str]:
    """
    Turn amounts a spreadsheet wrote as text — ``"30,000"``, ``"₹1,800.50"`` —
    into numbers, in place, and say which values are not amounts at all.

    Without this the engines read ``"30,000"`` as zero: a PF deduction of
    ``"1,700"`` against ``"1,800"`` due was compared as nought against nought,
    and passed. A blank stays absent; it is never made zero.
    """
    problems: list[str] = []
    for index, row in enumerate(rows):
        for key in keys & row.keys():
            value = row[key]
            if not isinstance(value, str):
                continue
            if value.strip().lower() in {"", "nan", "none", "-", "na", "n/a"}:
                row[key] = None
                continue
            amount = parse_decimal(value)
            if amount is None:
                problems.append(f"row {index + 2}, {key} “{value}”")   # the header is row 1
            else:
                row[key] = float(amount)
    return problems


def ingest_register(
    db: Session,
    *,
    entity: Entity,
    user: User,
    df: pd.DataFrame,
    filename: str | None,
    content: bytes,
    run_type: str = "regular",
    period_month: date | None = None,
    effective_month_from: date | None = None,
    effective_month_to: date | None = None,
    strict: bool = True,
    column_mapping: dict[str, str] | None = None,
    channel: str = "upload",
) -> dict[str, Any]:
    """
    Map, check, store and freeze one register. Commits.

    Raises ``ValueError`` for a mapping that cannot be applied — the caller
    decides whether that is a 400 or a failed run.
    """
    comps = db.query(ComponentConfig).filter(ComponentConfig.entity_id == entity.id).all()
    comp_names = {c.component_name for c in comps}
    if column_mapping is None:
        column_mapping = suggested_mapping(list(df.columns), comp_names)
    unmapped_sources = sorted(set(df.columns) - set(column_mapping)) if isinstance(column_mapping, dict) else []
    check_mapping(list(df.columns), column_mapping, comp_names)
    df = apply_mapping(df, column_mapping)
    columns, employees = dataframe_to_employees(df)
    unreadable = read_amounts(employees, amount_keys(comp_names))
    if unreadable:
        raise ValueError(
            f"{len(unreadable)} amount(s) in the register are not numbers, so nothing was stored: "
            + "; ".join(unreadable[:10]) + ("; …" if len(unreadable) > 10 else "")
            + ". Correct them and upload again — a value that cannot be read is never taken as zero."
        )
    missing, warnings = validate_required_columns(columns, comp_names, strict=strict)
    if unmapped_sources:
        warnings.append("Unmapped source columns were ignored: " + ", ".join(unmapped_sources[:20]))
    # Where each row sits in the file, so a finding can point at it.
    register_uploads.stamp_source_rows(employees)

    run = PayrollRun(
        user_id=user.id,
        entity_id=entity.id,
        run_type=run_type,
        effective_month_from=effective_month_from,
        effective_month_to=effective_month_to,
        filename=filename,
        employee_count=len(employees),
    )
    db.add(run)
    db.commit()

    persist_period = _to_first_of_month(period_month or effective_month_to)
    register_id: uuid.UUID | None = None
    # Only a regular run is the month's register. An arrears file paid in June
    # used to replace June's register, so June's cost collapsed to the arrears
    # alone in every report. It is kept as a frozen upload and validated.
    if run_type not in (None, "", "regular") and persist_period:
        warnings.append(
            f"This {str(run_type).replace('_', ' ')} run is validated but not added to "
            f"{persist_period:%b %Y}'s cost register; the regular register stays as it was."
        )
    if persist_period and comps and not missing and run_type in (None, "", "regular"):
        register_id = persist_salary_register(db, user, entity, persist_period, filename,
                                              employees, comps, source_columns=columns)
        # Months later, when a figure is challenged, the only useful answer is
        # who uploaded which file, and when.
        audit.record(
            db, entity_id=entity.id, user=user, action="register.uploaded",
            object_type="salary_register", object_id=persist_period.isoformat(),
            summary=(
                f"Uploaded the salary register for {persist_period:%b %Y} — "
                f"{len(employees)} employees from {filename}"
                + (" through the integration API" if channel == "api" else "")
            ),
            detail={"warnings": warnings[:20], "run_type": run_type, "channel": channel},
        )
        db.commit()

    # Every upload is frozen, stored-as-register or not: it is what a
    # validation job reads, and what a run will later be shown to have read.
    upload = register_uploads.record(
        db,
        entity_id=entity.id,
        user_id=user.id,
        period_month=persist_period,
        run_type=run_type,
        filename=filename,
        content=content,
        rows=employees,
        source_columns=columns,
        column_mapping=column_mapping if isinstance(column_mapping, dict) else None,
        missing_required=missing,
        warnings=warnings,
        register_id=register_id,
    )
    db.commit()
    return {
        "columns": columns,
        "employees": employees,
        "missing": missing,
        "warnings": warnings,
        "upload": upload,
        "register_id": register_id,
        "period_month": persist_period,
    }
