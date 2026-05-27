"""Base classes for the Phase 2 validator framework.

Each concrete validator subclasses `BaseValidator`, implements `validate(...)`,
and emits zero or more `ValidationIssue` records through the
`ValidationResult.add_issue` helper. The framework deliberately stays small —
validators receive raw pandas frames and a tolerance config, and are otherwise
free to compose their own logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

import pandas as pd

from app.utils.constants import Severity, ValidationFlag


@dataclass
class ValidatorConfig:
    """Runtime knobs every validator inherits."""

    tolerance_rupees: float = 1.0


@dataclass
class ValidationIssue:
    employee_id: str
    employee_name: str
    flag: ValidationFlag
    severity: Severity
    description: str
    expected_value: Optional[float] = None
    actual_value: Optional[float] = None
    difference: Optional[float] = None
    component: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "employee_name": self.employee_name,
            "flag": self.flag.value if isinstance(self.flag, ValidationFlag) else self.flag,
            "severity": (
                self.severity.value if isinstance(self.severity, Severity) else self.severity
            ),
            "description": self.description,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "difference": self.difference,
            "component": self.component,
        }


@dataclass
class ValidationResult:
    validator_name: str
    records_processed: int = 0
    issues: List[ValidationIssue] = field(default_factory=list)

    def add_issue(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    def by_severity(self, severity: Severity) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == severity]


class BaseValidator:
    """Abstract validator. Subclasses override `validate(...)`."""

    def __init__(self, config: Optional[ValidatorConfig] = None) -> None:
        self.config = config or ValidatorConfig()

    def validate(self, payroll: pd.DataFrame, **kwargs: Any) -> ValidationResult:  # pragma: no cover
        raise NotImplementedError("Subclasses must implement validate().")
