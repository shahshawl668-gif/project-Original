import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class CtcParsedRecord(BaseModel):
    employee_id: str
    employee_name: str | None = None
    effective_from: date
    annual_components: dict[str, float] = {}
    annual_ctc: float = 0.0


class CtcParseResponse(BaseModel):
    columns: list[str]
    records: list[CtcParsedRecord]
    unknown_columns: list[str] = []
    warnings: list[str] = []


class CtcCommitRequest(BaseModel):
    filename: str | None = None
    default_effective_from: date | None = None
    records: list[CtcParsedRecord]


class CtcUploadOut(BaseModel):
    id: uuid.UUID
    effective_from: date
    filename: str | None
    employee_count: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CtcRecordOut(BaseModel):
    id: uuid.UUID
    employee_id: str
    employee_name: str | None
    effective_from: date
    annual_components: dict[str, Any]
    annual_ctc: float | None
    created_at: datetime

    model_config = {"from_attributes": True}
