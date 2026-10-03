"""
The internal model every input is read into, whatever the HRMS called its columns.

Absent and blank are kept apart from zero and "no": a field the source did not
carry is ``None`` and the set of columns an input *had* is recorded, so a check
can say "the register has no status column" instead of reading silence as
"nobody is on hold".
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass
class Note:
    """Something about an input the approver should know: a value that could not be read, a default."""

    source: str
    message: str
    row: int | None = None
    employee_id: str | None = None


@dataclass
class RegisterRow:
    row: int
    employee_id: str
    key: str
    employee_name: str | None = None
    net_pay: Decimal | None = None
    net_raw: str | None = None
    status: str | None = None
    date_of_joining: date | None = None
    date_of_exit: date | None = None
    ff_processed: bool | None = None
    on_hold: bool | None = None
    arrears: Decimal | None = None
    increment: bool | None = None


@dataclass
class MasterRow:
    row: int
    employee_id: str
    key: str
    account_number: str | None = None
    ifsc: str | None = None
    beneficiary_name: str | None = None
    verification_status: str | None = None
    last_changed: date | None = None


@dataclass
class ChangeRow:
    row: int
    employee_id: str
    key: str
    field_changed: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    changed_on: date | None = None
    verification_status: str | None = None


@dataclass
class PreviousRow:
    row: int
    employee_id: str
    key: str
    net_pay: Decimal | None = None
    account_number: str | None = None
    ifsc: str | None = None


@dataclass
class HoldRow:
    row: int
    employee_id: str
    key: str
    category: str | None = None
    reason: str | None = None
    effective_date: date | None = None


@dataclass
class OffCycleRow:
    row: int
    employee_id: str
    key: str
    amount: Decimal | None = None
    payment_date: date | None = None
    reference: str | None = None


@dataclass
class BankRow:
    """One payment line. ``line`` is its position in the file, for the clean copy."""

    row: int
    line: int
    employee_id: str | None
    key: str | None
    beneficiary_name: str | None = None
    account_number: str | None = None
    ifsc: str | None = None
    amount: Decimal | None = None
    amount_raw: str | None = None
    reference: str | None = None


@dataclass
class BankFile:
    rows: list[BankRow]
    columns: set[str]
    #: Values read from the header record and footer record, when the format has them.
    header: dict[str, Any] | None = None
    footer: dict[str, Any] | None = None
    has_header_record: bool = False
    filename: str | None = None


@dataclass
class Table:
    """A tabular input that was supplied: its rows and the columns it actually carried."""

    rows: list[Any]
    columns: set[str]
    filename: str | None = None


@dataclass
class Inputs:
    bank_file: BankFile | None = None
    register: Table | None = None
    bank_master: Table | None = None
    change_log: Table | None = None
    previous: Table | None = None
    hold_list: Table | None = None
    offcycle: Table | None = None
    notes: list[Note] = _field(default_factory=list)


@dataclass
class Finding:
    rule_id: str
    severity: str
    reason: str
    employee_id: str | None = None
    employee_name: str | None = None
    field: str | None = None
    expected: str | None = None
    actual: str | None = None
    rows: list[int] = _field(default_factory=list)
    amount: Decimal | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id, "severity": self.severity, "employee_id": self.employee_id or "",
            "employee_name": self.employee_name or "", "field": self.field or "",
            "expected": self.expected or "", "actual": self.actual or "", "reason": self.reason,
            "rows": self.rows, "amount": str(self.amount) if self.amount is not None else "",
        }


@dataclass
class RuleResult:
    rule_id: str
    title: str
    severity: str
    status: str
    reason: str = ""
    findings: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"rule_id": self.rule_id, "title": self.title, "severity": self.severity,
                "status": self.status, "reason": self.reason, "findings": self.findings}
