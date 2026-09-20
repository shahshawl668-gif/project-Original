from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ParsePreview(BaseModel):
    """What the client sees before committing an upload."""

    row_count: int
    # Which incoming column was read as which field, so a mis-mapped header is
    # visible before anything is stored rather than discovered months later.
    header_map: dict[str, str]
    unmapped_columns: list[str]
    warnings: list[str]
    sample: list[dict]


class EmployeeMasterUploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    effective_from: date
    filename: str | None
    employee_count: int | None
    created_at: datetime | None


class EmployeeRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: str
    employee_name: str | None
    effective_from: date
    date_of_joining: date | None
    date_of_exit: date | None
    date_of_birth: date | None
    gender: str | None
    work_state: str | None
    work_location: str | None
    department: str | None
    designation: str | None
    grade: str | None
    employment_type: str | None
    skill_category: str | None
    pan: str | None
    uan: str | None
    esic_ip_number: str | None


class AttendanceRegisterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    period_month: date
    filename: str | None
    employee_count: int | None
    created_at: datetime | None


class AttendanceRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: str
    employee_name: str | None
    calendar_days: Decimal | None
    present_days: Decimal | None
    paid_days: Decimal | None
    lop_days: Decimal | None
    paid_leave_days: Decimal | None
    weekly_off_days: Decimal | None
    holiday_days: Decimal | None
    overtime_hours: Decimal | None
