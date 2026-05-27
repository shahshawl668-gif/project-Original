"""Shared enums for the Phase 2 payroll-validation engine.

Validators reference `ValidationFlag` and `Severity` when building
`ValidationIssue` records, so they live here as plain string enums and stay
JSON-serialisable through the FastAPI envelope.
"""
from __future__ import annotations

from enum import Enum


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ValidationFlag(str, Enum):
    # Proration / FNF / attendance family
    PRORATION_ERROR = "PRORATION_ERROR"
    FNF_LEAVE_ENCASHMENT_ERROR = "FNF_LEAVE_ENCASHMENT_ERROR"
    LOP_MISMATCH = "LOP_MISMATCH"
    NEGATIVE_LOP = "NEGATIVE_LOP"
