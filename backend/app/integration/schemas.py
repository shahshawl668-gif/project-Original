"""Request bodies of the integration API, with the synthetic examples the contract publishes.

Every example uses invented people and numbers. No example carries a real key:
where one is shown it is ``pol_live_1a2b3c4d_<your key>``.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_MASTER_EXAMPLE = {
    "batch_id": "HRMS-MASTER-2026-06-01",
    "source_system": "Example HRMS",
    "source_object": "employees",
    "mode": "upsert",
    "effective_from": "2026-06-01",
    "records": [
        {"employee_id": "00123", "employee_name": "Asha Rao (synthetic)", "date_of_joining": "2024-04-15",
         "work_state": "Karnataka", "department": "Engineering", "employment_type": "Permanent",
         "_source_record_id": "hrms-7781"},
        {"employee_id": "00124", "employee_name": "Vikram Shah (synthetic)", "date_of_joining": "2025-01-06",
         "work_state": "Maharashtra", "department": "Sales", "_source_record_id": "hrms-7782"},
    ],
}

_CTC_EXAMPLE = {
    "batch_id": "HRMS-CTC-REV-2026",
    "source_system": "Example HRMS",
    "records": [
        {"employee_id": "00123", "effective_from": "2025-04-01", "basic": 480000, "hra": 192000,
         "special_allowance": 228000, "annual_ctc": 900000},
        {"employee_id": "00123", "effective_from": "2026-04-01", "basic": 528000, "hra": 211200,
         "special_allowance": 250800, "annual_ctc": 990000},
    ],
}

_ATTENDANCE_EXAMPLE = {
    "batch_id": "TIME-2026-06",
    "source_system": "Example Time & Attendance",
    "period_month": "2026-06-01",
    "mode": "upsert",
    "records": [
        {"employee_id": "00123", "paid_days": 30, "lop_days": 0, "present_days": 22},
        {"employee_id": "00124", "paid_days": 28, "lop_days": 2, "present_days": 20},
    ],
}

_REGISTER_EXAMPLE = {
    "batch_id": "PAYROLL-2026-06",
    "source_system": "Example Payroll",
    "period_month": "2026-06-01",
    "run_type": "regular",
    "validate": True,
    "records": [
        {"employee_id": "00123", "employee_name": "Asha Rao (synthetic)", "basic": 44000, "hra": 17600,
         "special_allowance": 20900, "pf_employee": 5280, "paid_days": 30},
        {"employee_id": "00124", "employee_name": "Vikram Shah (synthetic)", "basic": 30000, "hra": 12000,
         "special_allowance": 14000, "pf_employee": 1800, "paid_days": 28, "lop_days": 2},
    ],
}

IMPORT_EXAMPLES = {
    "employee_master": {"summary": "Employee master (upsert)", "value": _MASTER_EXAMPLE},
    "ctc": {"summary": "CTC history — two effective dates for one person", "value": _CTC_EXAMPLE},
    "attendance": {"summary": "Attendance for June 2026", "value": _ATTENDANCE_EXAMPLE},
    "salary_register": {"summary": "Salary register, validated on arrival", "value": _REGISTER_EXAMPLE},
}


class ImportRequest(BaseModel):
    """One batch of records. Which fields apply depends on the import type in the path."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [_MASTER_EXAMPLE]})

    records: list[Any] = Field(
        ..., description="The records, each an object. Field names may use any alias the upload screens "
                         "accept (employee_id, emp_code, …). `_source_record_id` is kept as lineage. A "
                         "record that is not an object is rejected on its own, with its row number — "
                         "it does not fail the batch.")
    batch_id: str | None = Field(default=None, max_length=100,
                                 description="Your identifier for this batch; shown in run history.")
    source_system: str | None = Field(default=None, max_length=100)
    source_object: str | None = Field(default=None, max_length=255)
    mode: Literal["upsert", "replace"] | None = Field(
        default=None, description="Master and attendance: upsert (default) or replace. CTC is always "
                                  "upsert; a salary register always replace.")
    effective_from: date | None = Field(default=None, description="Employee master: the month this version applies from.")
    period_month: date | None = Field(default=None, description="Attendance and salary register: the payroll month.")
    default_effective_from: date | None = Field(default=None, description="CTC: date for records that give none.")
    run_type: Literal["regular", "arrears", "increment_arrears", "full_and_final", "bonus"] | None = None
    column_mapping: dict[str, str] | None = Field(
        default=None, description="Salary register: source column → field. Suggested automatically when omitted.")
    validate_register: bool | None = Field(default=None, alias="validate",
                                           description="Salary register: start validation once stored.")
    allow_missing_components: bool | None = Field(
        default=None, description="Salary register: treat a configured component with no column as zero. "
                                  "Off by default — absent is not zero.")

    def as_options_body(self) -> dict[str, Any]:
        body = self.model_dump(exclude_none=True, by_alias=True)
        return body


class ValidationJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"period_month": "2026-06-01"}, {"period_month": "2026-06-01", "upload_id": "3f0c…"}]})

    period_month: date
    upload_id: str | None = Field(default=None, description="A specific stored register; the month's latest when omitted.")
    run_type: Literal["regular", "arrears", "increment_arrears", "full_and_final", "bonus"] | None = None


class AssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"owner_user_id": "7d4e…", "due_date": "2026-07-05"}]})

    owner_user_id: str | None = Field(default=None, description="A person with a write role; null clears.")
    due_date: date | None = None


class CommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"body": "Corrected in HRMS on 2 July; will re-send the register."}]})

    body: str = Field(..., min_length=1, max_length=4000)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "examples": [{"state": "acknowledged", "note": "Seen by the payroll bureau's system."}]})

    state: Literal["open", "acknowledged", "waived", "resolved"] = Field(
        ..., description="A key may acknowledge or reopen. Waiving and resolving need a person.")
    note: str | None = Field(default=None, max_length=2000)


#: A proposed validation rule is the same body the matrix screen sends.
RULE_PROPOSAL_EXAMPLE = {
    "rule_key": "CUST-BASIC-FLOOR", "name": "Basic at least 40% of gross", "category": "custom",
    "severity": "WARNING", "effective_from": "2026-07-01",
    "assertion": {"left": {"source": "component", "key": "basic"}, "operator": "gte",
                  "right": {"source": "expr", "value": "gross * 0.4"}},
    "change_reason": "Policy from the July compensation memo (synthetic example)",
}


class BiQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"dataset": "payroll_cost", "metric": "ctc", "breakdown": "department", "period": {"preset": "last_6"}},
    ]})

    dataset: str
    metric: str
    breakdown: str = "period"
    granularity: Literal["month", "quarter", "year"] = "month"
    filters: dict[str, list[str]] = Field(default_factory=dict)
    period: dict[str, Any] | None = Field(default=None, description='{"preset": "last_6"} or {"preset": "custom", "from": "2026-01-01", "to": "2026-06-01"}')
