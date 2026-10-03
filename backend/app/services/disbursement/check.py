"""
One disbursement check, end to end: read the files, run the checks, write the
clean file, and freeze everything into the report that is stored and drawn
from. No database here — the router stores what this returns.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import PurePath
from typing import Any

from app.services.disbursement import engine, inputs, outputs
from app.services.disbursement import template as templates
from app.services.disbursement.config import DO_NOT_RELEASE, Settings
from app.services.bank_file import match_key
from app.services.disbursement.engine import Result
from app.services.disbursement.model import Note, PreviousRow, Table

INPUT_ORDER = ("bank_file", "register", "bank_master", "change_log", "previous", "hold_list", "offcycle")


@dataclass
class Checked:
    result: Result
    report: dict[str, Any]
    clean: bytes | None
    clean_filename: str | None
    # Each payment in the clean file: what next month's check compares against.
    paid: list[dict[str, Any]]


def clean_name(filename: str) -> str:
    path = PurePath(filename or "bank_file.csv")
    return f"{path.stem}_clean{path.suffix}"


def run_check(files: dict[str, tuple[str, bytes]], profile: dict[str, Any], template: dict[str, Any],
              settings: Settings, meta: dict[str, Any], previous: Table | None = None,
              previous_source: dict[str, Any] | None = None) -> Checked:
    """
    ``previous`` is a previous period built from an approved check (see
    ``previous_from_paid``); it is used only when no previous period file was
    uploaded, and the report says where it came from.
    """
    loaded, parsed = inputs.load(files, profile, template)
    if loaded.previous is None and previous is not None:
        loaded.previous = previous
        loaded.notes.append(Note("previous period", f"Taken from {previous.filename}: the amounts the approved "
                                 "clean file paid, by employee, with their accounts."))
    result = engine.run(loaded, settings)
    clean = clean_filename = None
    if result.verdict != DO_NOT_RELEASE:
        clean = templates.write_clean(parsed, result.kept_lines, template)
        clean_filename = clean_name(files["bank_file"][0])
    described = []
    for slot in INPUT_ORDER:
        if slot not in files:
            continue
        name, content = files[slot]
        table = getattr(loaded, slot, None)
        described.append({"slot": slot, "label": inputs.LABEL[slot].capitalize(), "filename": name,
                          "sha256": templates.fingerprint(content),
                          "rows": len(table.rows) if table is not None else None})
    if "previous" not in files and previous is not None and previous_source is not None:
        described.append({"slot": "previous", "label": "Previous period", **previous_source,
                          "rows": len(previous.rows)})
    paid = []
    if clean is not None:
        paid = [{"employee_id": r.employee_id or "", "amount": str(r.amount) if r.amount is not None else None,
                 "account_number": r.account_number or "", "ifsc": r.ifsc or ""}
                for r in loaded.bank_file.rows if r.line in result.kept_lines]
    report = outputs.build_report(result, {
        **meta,
        "profile": profile.get("name", profile.get("key")),
        "template": template.get("name", template.get("key")),
        "inputs": described,
        "settings": settings.snapshot(),
        "clean_filename": clean_filename,
        "clean_sha256": templates.fingerprint(clean) if clean is not None else None,
    }, loaded.bank_file.rows)
    return Checked(result, report, clean, clean_filename, paid)


def previous_from_paid(paid: list[dict[str, Any]], label: str) -> Table:
    """A previous period from the paid list of an approved check: total paid, account and IFSC per employee."""
    rows: dict[str, PreviousRow] = {}
    for i, p in enumerate(paid, start=1):
        key = match_key(p.get("employee_id"), "trim")
        if not key:
            continue
        amount = Decimal(p["amount"]) if p.get("amount") else None
        if key in rows:
            row = rows[key]
            if amount is not None:
                row.total_payable = (row.total_payable or Decimal("0")) + amount
            continue
        rows[key] = PreviousRow(i, p["employee_id"], key, account_number=p.get("account_number") or None,
                                ifsc=p.get("ifsc") or None, total_payable=amount)
    return Table(list(rows.values()), {"employee_id", "total_payable", "account_number", "ifsc"}, label)
