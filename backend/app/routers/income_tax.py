"""Income tax estimation endpoints.

These endpoints are *informational* — they let the UI compare old vs new
regime for an employee's projected annual income, without requiring a payroll
upload. All statutory parameters come from the tenant's FY-versioned
income-tax config (see /api/config/income-tax); `financial_year` in the
request selects a year, otherwise the tenant's default FY applies.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write
from app.envelope import ok
from app.models import Entity, User
from app.services.config_service import ConfigService
from app.services.income_tax_engine import (
    OldRegimeDeductions,
    compare_regimes,
    compute_income_tax,
)

router = APIRouter()


class DeductionsIn(BaseModel):
    section_80c: float = 0.0
    section_80d: float = 0.0
    section_80ccd_1b: float = 0.0
    home_loan_interest: float = 0.0
    hra_exempt: float = 0.0
    other_chapter_via: float = 0.0


class TaxRequest(BaseModel):
    annual_gross: float = Field(..., ge=0)
    regime: Literal["old", "new"]
    deductions: DeductionsIn | None = None
    financial_year: str | None = Field(None, description="e.g. '2026-27'; defaults to tenant's default FY")


class CompareRequest(BaseModel):
    annual_gross: float = Field(..., ge=0)
    deductions: DeductionsIn | None = None
    financial_year: str | None = Field(None, description="e.g. '2026-27'; defaults to tenant's default FY")


def _year_cfg(db: Session, user: User, financial_year: str | None):
    year_cfg = ConfigService(db).get_tax_year(entity.id, financial_year)
    if year_cfg is None:
        raise HTTPException(
            status_code=422,
            detail="No income-tax configuration found. Configure financial years via /api/config/income-tax.",
        )
    return year_cfg


@router.post("/compute")
def compute_tax(
    body: TaxRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from dataclasses import asdict

    deds = OldRegimeDeductions(**body.deductions.model_dump()) if body.deductions else None
    res = compute_income_tax(
        annual_gross=body.annual_gross,
        regime=body.regime,
        deductions=deds,
        year_cfg=_year_cfg(db, user, body.financial_year),
    )
    return ok(asdict(res))


@router.post("/compare")
def compare(
    body: CompareRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deds = OldRegimeDeductions(**body.deductions.model_dump()) if body.deductions else None
    res = compare_regimes(
        annual_gross=body.annual_gross,
        deductions=deds,
        year_cfg=_year_cfg(db, user, body.financial_year),
    )
    return ok(res)


@router.get("/years")
def list_years(
    entity: Entity = Depends(get_current_entity),
    db: Session = Depends(get_db),
):
    cfg = ConfigService(db).get_income_tax_config(entity.id)
    return ok(
        {
            "default_year": cfg.default_year,
            "years": sorted(cfg.years.keys()),
        }
    )
