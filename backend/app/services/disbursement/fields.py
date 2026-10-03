"""
The fields each disbursement input maps to.

These extend the Studio mapping engine (``app.services.studio.mapping``): a
mapping for any of these inputs is an ordinary mapping specification — source
column, aliases, lookups, recorded defaults — checked by the same
``check_spec``. Adding an HRMS is writing a specification, not code.
"""
from __future__ import annotations

#: object type → (field, kind). ``id`` fields are read as text with spaces trimmed.
TARGETS: dict[str, tuple[tuple[str, str], ...]] = {
    "disbursement_register": (
        ("employee_id", "id"), ("employee_name", "text"), ("net_pay", "text"), ("status", "text"),
        ("date_of_joining", "text"), ("date_of_exit", "text"), ("ff_processed", "text"),
        ("on_hold", "text"), ("arrears", "text"), ("increment", "text"),
        ("total_payable", "text"), ("reimbursement", "text"), ("salary_hold", "text"), ("hold_release", "text"),
    ),
    "bank_master": (
        ("employee_id", "id"), ("account_number", "text"), ("ifsc", "text"), ("beneficiary_name", "text"),
        ("verification_status", "text"), ("last_changed", "text"),
    ),
    "bank_change_log": (
        ("employee_id", "id"), ("field_changed", "text"), ("old_value", "text"), ("new_value", "text"),
        ("changed_on", "text"), ("verification_status", "text"),
    ),
    "previous_period": (
        ("employee_id", "id"), ("net_pay", "text"), ("account_number", "text"), ("ifsc", "text"),
        ("total_payable", "text"),
    ),
    "hold_list": (
        ("employee_id", "id"), ("category", "text"), ("reason", "text"), ("effective_date", "text"),
    ),
    "offcycle_payments": (
        ("employee_id", "id"), ("amount", "text"), ("payment_date", "text"), ("reference", "text"),
    ),
}

#: The input slot each object type fills.
SLOT = {
    "disbursement_register": "register", "bank_master": "bank_master", "bank_change_log": "change_log",
    "previous_period": "previous", "hold_list": "hold_list", "offcycle_payments": "offcycle",
}
OBJECT_FOR_SLOT = {v: k for k, v in SLOT.items()}

#: Fields a payment line can carry, read by the bank file template.
BANK_COLUMNS = ("employee_id", "beneficiary_name", "account_number", "ifsc", "amount", "reference")
#: Values a header or footer record can state.
RECORD_FIELDS = ("record_type", "debit_account", "value_date", "record_count", "total_amount", "batch_reference")


def targets(object_type: str) -> list[dict[str, str]]:
    return [{"target": f, "type": kind} for f, kind in TARGETS[object_type]]
