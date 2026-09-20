"""
Budget upload, approval, variance and forecast.

Upload is deliberately two steps — parse and preview, then commit. A budget is a
decision, and a decision taken by dragging a file onto a page without seeing what
it said is not one. The preview is where a finance team finds the duplicate
department line and the month that read as 2025 instead of 2026.
"""
from __future__ import annotations

import io
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write, require_org_admin
from app.envelope import ok
from app.models import BudgetLine, BudgetVersion, ENTITY_SCOPE, Entity, User
from app.services import audit, budgeting
from app.services.dimensions import DIMENSION_KEYS, DIMENSION_LABELS
from app.services.payroll_parse import dataframe_to_employees, parse_payroll_file

router = APIRouter()

BUDGET_TEMPLATE = (
    "period,scope,amount,headcount,note\n"
    "2026-04,Engineering,4200000,42,Approved FY27 plan\n"
    "2026-04,Sales,2100000,24,\n"
    "2026-05,Engineering,4250000,43,Two open roles\n"
    "2026-05,Sales,2100000,24,\n"
)


def _period(value: str | None, field: str) -> date | None:
    if not value:
        return None
    parsed = budgeting.parse_period(value)
    if parsed is None:
        raise HTTPException(status_code=400, detail=f"'{field}' is not a readable month")
    return parsed


@router.get("/template.csv")
def template():
    """A budget file in the shape this product reads, for a finance team to fill in."""
    return StreamingResponse(
        io.BytesIO(BUDGET_TEMPLATE.encode()),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="payroll-budget-template.csv"'},
    )


@router.get("/scopes")
def scopes():
    """The levels a budget can be approved at."""
    return ok({
        "scopes": [{"key": ENTITY_SCOPE, "label": "Whole entity"}]
        + [{"key": k, "label": DIMENSION_LABELS[k]} for k in DIMENSION_KEYS],
        "measures": [
            {"key": "ctc", "label": "Total CTC"},
            {"key": "gross", "label": "Gross pay"},
            {"key": "employer_cost", "label": "Employer contributions"},
        ],
    })


@router.post("/preview")
async def preview(
    file: UploadFile = File(...),
    scope_key: str = Form(default=ENTITY_SCOPE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """Read an uploaded budget and show what it says before anything is stored."""
    if scope_key != ENTITY_SCOPE and scope_key not in DIMENSION_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown budget scope: {scope_key}")

    content = await file.read()
    try:
        frame = parse_payroll_file(content, file.filename or "budget.csv")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _, records = dataframe_to_employees(frame)
    lines, problems = budgeting.parse_budget_rows(records, scope_key)

    total = sum((line["amount"] for line in lines), Decimal("0"))
    return ok({
        "filename": file.filename,
        "scope_key": scope_key,
        "line_count": len(lines),
        "total": float(total),
        "periods": sorted({line["period_month"].isoformat() for line in lines}),
        "scopes": sorted({line["scope_value"] for line in lines}),
        "problems": problems,
        "lines": [
            {
                "period": line["period_month"].isoformat(),
                "scope_value": line["scope_value"],
                "amount": float(line["amount"]),
                "headcount": line["headcount"],
            }
            for line in lines[:200]
        ],
        "truncated": len(lines) > 200,
    })


@router.post("/versions")
async def create_version(
    file: UploadFile = File(...),
    name: str = Form(...),
    scope_key: str = Form(default=ENTITY_SCOPE),
    measure: str = Form(default="ctc"),
    financial_year: str | None = Form(default=None),
    note: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """Store a budget as a draft. It is not a comparison until someone approves it."""
    if scope_key != ENTITY_SCOPE and scope_key not in DIMENSION_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown budget scope: {scope_key}")
    if measure not in ("ctc", "gross", "employer_cost"):
        raise HTTPException(status_code=400, detail=f"Unknown budget measure: {measure}")

    content = await file.read()
    try:
        frame = parse_payroll_file(content, file.filename or "budget.csv")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _, records = dataframe_to_employees(frame)
    lines, problems = budgeting.parse_budget_rows(records, scope_key)
    if not lines:
        raise HTTPException(
            status_code=400,
            detail="No budget lines could be read. " + (problems[0] if problems else ""),
        )

    try:
        version = budgeting.save_version(
            db, entity.id,
            name=name.strip(), scope_key=scope_key, measure=measure, lines=lines,
            financial_year=financial_year, note=note,
            source_filename=file.filename, created_by=user,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    audit.record(
        db, entity_id=entity.id, user=user, action="budget.uploaded",
        object_type="budget_version", object_id=str(version.id),
        summary=f"Uploaded budget {name!r} — {len(lines)} lines from {file.filename}",
        detail={"scope_key": scope_key, "measure": measure, "problems": problems},
    )
    db.commit()
    db.refresh(version)

    return ok({
        "id": str(version.id), "name": version.name, "state": version.state,
        "line_count": len(lines), "problems": problems,
    })


@router.get("/versions")
def list_versions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    versions = (
        db.query(BudgetVersion)
        .filter(BudgetVersion.entity_id == entity.id)
        .order_by(BudgetVersion.created_at.desc())
        .all()
    )
    counts = dict(
        db.query(BudgetLine.version_id, func.count(BudgetLine.id))
        .filter(BudgetLine.entity_id == entity.id)
        .group_by(BudgetLine.version_id)
        .all()
    )
    return ok({
        "versions": [
            {
                "id": str(v.id), "name": v.name, "state": v.state,
                "financial_year": v.financial_year, "scope_key": v.scope_key,
                "scope_label": DIMENSION_LABELS.get(v.scope_key, "Whole entity"),
                "measure": v.measure, "is_current": v.is_current,
                "line_count": counts.get(v.id, 0),
                "source_filename": v.source_filename, "note": v.note,
                "approved_by": v.approved_by_email,
                "approved_at": v.approved_at.isoformat() if v.approved_at else None,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ]
    })


@router.post("/versions/{version_id}/approve")
def approve_version(
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
    entity: Entity = Depends(get_current_entity),
):
    """
    Approve a budget.

    Restricted to owners and managers: approving a budget is the act that makes
    a number the one a board is shown, and it is not an analyst's to take.
    """
    version = db.get(BudgetVersion, version_id)
    if version is None or version.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Budget version not found")
    if version.state == "approved":
        return ok({"id": str(version.id), "state": version.state, "already": True})

    budgeting.approve(db, version, user)
    audit.record(
        db, entity_id=entity.id, user=user, action="budget.approved",
        object_type="budget_version", object_id=str(version.id),
        summary=f"Approved budget {version.name!r} as the current comparison",
    )
    db.commit()
    return ok({"id": str(version.id), "state": version.state, "already": False})


@router.delete("/versions/{version_id}")
def delete_version(
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
    entity: Entity = Depends(get_current_entity),
):
    """Remove a draft. An approved budget is never deleted — history depends on it."""
    version = db.get(BudgetVersion, version_id)
    if version is None or version.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Budget version not found")
    if version.state == "approved":
        raise HTTPException(
            status_code=409,
            detail="An approved budget cannot be deleted. Approve a newer version to "
                   "supersede it — the variance reported at the time stays reconstructable.",
        )
    audit.record(
        db, entity_id=entity.id, user=user, action="budget.deleted",
        object_type="budget_version", object_id=str(version.id),
        summary=f"Deleted draft budget {version.name!r}",
    )
    db.delete(version)
    db.commit()
    return ok({"deleted": True})


@router.get("/variance")
def variance(
    version_id: uuid.UUID | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    business_unit: list[str] | None = Query(default=None),
    department: list[str] | None = Query(default=None),
    cost_center: list[str] | None = Query(default=None),
    work_location: list[str] | None = Query(default=None),
    work_state: list[str] | None = Query(default=None),
    grade: list[str] | None = Query(default=None),
    designation: list[str] | None = Query(default=None),
    employment_type: list[str] | None = Query(default=None),
    skill_category: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """Actual payroll cost against the approved budget."""
    filters = {
        "business_unit": business_unit, "department": department, "cost_center": cost_center,
        "work_location": work_location, "work_state": work_state, "grade": grade,
        "designation": designation, "employment_type": employment_type,
        "skill_category": skill_category,
    }
    return ok(budgeting.budget_variance(
        db, entity.id,
        version_id=version_id,
        date_from=_period(date_from, "date_from"),
        date_to=_period(date_to, "date_to"),
        filters={k: v for k, v in filters.items() if v},
    ))


@router.get("/forecast")
def forecast(
    months: int = Query(default=6, ge=1, le=24),
    increment_pct: float = Query(default=0, ge=-100, le=200),
    increment_from: str | None = Query(default=None),
    new_hires_per_month: int = Query(default=0, ge=0, le=10000),
    average_hire_cost: float = Query(default=0, ge=0),
    exits_per_month: int = Query(default=0, ge=0, le=10000),
    bonus_month: str | None = Query(default=None),
    bonus_amount: float = Query(default=0, ge=0),
    measure: str = Query(default="ctc"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """
    Project cost forward from stated assumptions.

    A projection, never a result: every figure comes back under a ``forecast``
    key with the assumptions attached, and the response carries its own
    disclaimer so an API consumer cannot strip the label off by accident.
    """
    return ok(budgeting.forecast(
        db, entity.id,
        months=months,
        increment_pct=increment_pct,
        increment_from=_period(increment_from, "increment_from"),
        new_hires_per_month=new_hires_per_month,
        average_hire_cost=average_hire_cost,
        exits_per_month=exits_per_month,
        bonus_month=_period(bonus_month, "bonus_month"),
        bonus_amount=bonus_amount,
        measure=measure,
    ))
