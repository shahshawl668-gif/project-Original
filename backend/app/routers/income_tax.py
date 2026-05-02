"""Income tax estimation endpoints (FY 2025-26).

These endpoints are *informational* — they let the UI compare old vs new
regime for an employee's projected annual income, without requiring a payroll
upload. All math runs in the request thread (pure functions, no I/O).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.envelope import ok
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


class CompareRequest(BaseModel):
    annual_gross: float = Field(..., ge=0)
    deductions: DeductionsIn | None = None


@router.post("/compute")
def compute_tax(body: TaxRequest):
    deds = OldRegimeDeductions(**body.deductions.model_dump()) if body.deductions else None
    res = compute_income_tax(
        annual_gross=body.annual_gross,
        regime=body.regime,
        deductions=deds,
    )
    return ok(res.__dict__)


@router.post("/compare")
def compare(body: CompareRequest):
    deds = OldRegimeDeductions(**body.deductions.model_dump()) if body.deductions else None
    res = compare_regimes(annual_gross=body.annual_gross, deductions=deds)
    return ok(res)
