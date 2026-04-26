from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class PayrollUploadMeta(BaseModel):
    run_type: Literal["regular", "arrear", "increment_arrear"] = "regular"
    period_month: date | None = None
    effective_month_from: date | None = None
    effective_month_to: date | None = None
    strict_header_check: bool = True


class UploadParseResponse(BaseModel):
    columns: list[str]
    preview: list[dict[str, Any]]
    employees: list[dict[str, Any]]
    missing_required: list[str] = []
    warnings: list[str] = []


class ValidateRequest(BaseModel):
    employees: list[dict[str, Any]]
    run_type: Literal["regular", "arrear", "increment_arrear"] = "regular"
    period_month: date | None = None
    effective_month_from: date | None = None
    effective_month_to: date | None = None
    as_of_date: date | None = Field(
        default=None,
        description="Reference date for PT/LWF slab lookup (defaults to today).",
    )


class ValidateResponseRow(BaseModel):
    employee_id: str
    employee_name: str | None = None
    pf_wage: float
    pf_type: str
    pf_amount_employee: float
    pf_amount_employer: float
    esic_wage: float
    esic_eligible: bool
    pt_wage_base: float
    pt_applicable_state: str | None
    pt_monthly_slab: str | None
    pt_due: float
    lwf_wage_base: float
    lwf_applicable_state: str | None
    lwf_employee_rate: float
    lwf_employer_rate: float
    lwf_employee: float
    lwf_employer: float
    run_type: str
    arrear_months: int = 0
    arrear_total: float = 0.0
    increment_arrear_total: float = 0.0
    tds_risk_flags: list[str] = []
    errors: list[str] = []
