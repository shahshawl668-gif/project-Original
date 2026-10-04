"""
Reading the uploaded files into the internal model.

Tables (CSV or XLSX) are read with every cell as text — account numbers keep
their leading zeros and never pass through a float — then mapped by an ordinary
Studio mapping specification from a profile. Values are parsed here rather than
by the mapping engine so that one unreadable cell becomes a note on that row,
not a rejected row that silently disappears from the check.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.services.bank_file import match_key, parse_amount
from app.services.disbursement import template as templates
from app.services.disbursement import values
from app.services.disbursement.fields import OBJECT_FOR_SLOT
from app.services.disbursement.model import (
    ChangeRow, HoldRow, Inputs, MasterRow, Note, OffCycleRow, PreviousRow, RegisterRow, Table,
)
from app.services.studio import mapping

PROFILE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "disbursement" / "profiles"
SLOTS = ("register", "bank_master", "change_log", "previous", "hold_list", "offcycle")
LABEL = {"register": "register", "bank_master": "bank master", "change_log": "bank change log",
         "previous": "previous period", "hold_list": "hold list", "offcycle": "off-cycle payments",
         "bank_file": "bank file"}


def builtin_profiles() -> dict[str, dict[str, Any]]:
    out = {}
    for path in sorted(PROFILE_DIR.glob("*.json")):
        profile = json.loads(path.read_text(encoding="utf-8"))
        out[profile["key"]] = check_profile(profile)
    return out


def check_profile(profile: dict[str, Any]) -> dict[str, Any]:
    for slot, spec in (profile.get("inputs") or {}).items():
        if slot not in OBJECT_FOR_SLOT:
            raise ValueError(f"Unknown input {slot!r} in profile {profile.get('key')!r}")
        mapping.check_spec(spec, OBJECT_FOR_SLOT[slot])
    return profile


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
def _cell(value: Any) -> Any:
    """A spreadsheet cell as text, never through scientific notation; dates stay dates."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    if isinstance(value, (datetime, date)):
        return value
    return str(value)


def read_table(content: bytes, filename: str) -> tuple[list[dict[str, Any]], list[str]]:
    lower = (filename or "").lower()
    if lower.endswith(".xlsx"):
        from openpyxl import load_workbook

        from app.services.upload_safety import check_workbook

        check_workbook(content)
        try:
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:  # a zip that is not a workbook is refused, not a 500
            raise ValueError(f"{filename}: not a readable .xlsx workbook.") from exc
        rows = wb.worksheets[0].iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(rows, [])]
        records = []
        for raw in rows:
            if raw is None or all(v is None or str(v).strip() == "" for v in raw):
                continue
            records.append({h: _cell(v) for h, v in zip(header, raw, strict=False) if h})
        wb.close()
        return records, [h for h in header if h]
    if lower.endswith((".csv", ".txt")):
        for enc in ("utf-8-sig", "cp1252"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError(f"{filename}: the text encoding could not be read.")
        reader = csv.reader(io.StringIO(text))
        header = [h.strip() for h in next(reader, [])]
        records = []
        for raw in reader:
            if not any(c.strip() for c in raw):
                continue
            records.append({h: v for h, v in zip(header, raw, strict=False) if h})
        return records, [h for h in header if h]
    raise ValueError(f"{filename}: upload a .csv or .xlsx file.")


def _present(spec: dict[str, Any], headers: list[str]) -> set[str]:
    """The internal fields this file actually carries, given its column names."""
    have = set(headers)
    out = set()
    for f in spec["fields"]:
        sources = [f.get("source"), *(f.get("aliases") or [])]
        if f.get("formula") or f.get("cases") or any(s in have for s in sources if s):
            out.add(f["target"])
    return out


def _mapped(slot: str, content: bytes, filename: str, spec: dict[str, Any], notes: list[Note]):
    records, headers = read_table(content, filename)
    present = _present(spec, headers)
    if "employee_id" not in present:
        raise ValueError(f"The {LABEL[slot]} file has no employee code column the profile recognises "
                         f"(looked for {spec['fields'][0].get('source')!r}).")
    out = []
    for m in mapping.apply(spec, records, start_row=2):
        if m.output is None:
            for e in m.errors:
                notes.append(Note(LABEL[slot], f"row skipped: {e['message']}", row=m.row))
            continue
        for d in m.defaults_used:
            notes.append(Note(LABEL[slot], f"{d} was blank and the profile's default was used", row=m.row,
                              employee_id=m.output.get("employee_id")))
        out.append((m.row, m.output))
    return out, present


def _decimal(value: Any, slot: str, field: str, row: int, emp: str, notes: list[Note]):
    raw = values.text(value)
    if raw is None:
        return None, None
    amount = parse_amount(raw)
    if amount is None:
        notes.append(Note(LABEL[slot], f"{field} '{raw}' could not be read as a number", row=row, employee_id=emp))
    return amount, raw


def _date(value: Any, slot: str, field: str, row: int, emp: str, notes: list[Note]):
    if value is None or values.text(value) is None:
        return None
    out = values.when(value)
    if out is None:
        notes.append(Note(LABEL[slot], f"{field} '{values.text(value)}' could not be read as a date",
                          row=row, employee_id=emp))
    return out


def _flag(value: Any, slot: str, field: str, row: int, emp: str, notes: list[Note]):
    if values.text(value) is None:
        return None
    out = values.flag(value)
    if out is None:
        notes.append(Note(LABEL[slot], f"{field} '{values.text(value)}' is neither yes nor no; it was not "
                          "treated as either", row=row, employee_id=emp))
    return out


def read_slot(slot: str, content: bytes, filename: str, spec: dict[str, Any], notes: list[Note]) -> Table:
    rows, present = _mapped(slot, content, filename, spec, notes)
    built: list[Any] = []
    for row, o in rows:
        emp = o["employee_id"]
        key = match_key(emp, "trim")
        g = o.get
        if slot == "register":
            net, net_raw = _decimal(g("net_pay"), slot, "net pay", row, emp, notes)
            arrears, _ = _decimal(g("arrears"), slot, "arrears", row, emp, notes)
            total, total_raw = _decimal(g("total_payable"), slot, "total salary", row, emp, notes)
            reimb, _ = _decimal(g("reimbursement"), slot, "reimbursement", row, emp, notes)
            held, _ = _decimal(g("salary_hold"), slot, "salary hold", row, emp, notes)
            released, _ = _decimal(g("hold_release"), slot, "hold release", row, emp, notes)
            built.append(RegisterRow(
                row, emp, key, employee_name=values.text(g("employee_name")), net_pay=net,
                net_raw=net_raw, status=values.text(g("status")),
                date_of_joining=_date(g("date_of_joining"), slot, "date of joining", row, emp, notes),
                date_of_exit=_date(g("date_of_exit"), slot, "date of exit", row, emp, notes),
                ff_processed=_flag(g("ff_processed"), slot, "F&F processed", row, emp, notes),
                on_hold=_flag(g("on_hold"), slot, "on hold", row, emp, notes),
                arrears=arrears, increment=_flag(g("increment"), slot, "increment", row, emp, notes),
                total_payable=total, total_raw=total_raw, reimbursement=reimb, salary_hold=held,
                hold_release=released))
        elif slot == "bank_master":
            built.append(MasterRow(
                row, emp, key, account_number=values.account(g("account_number")), ifsc=values.ifsc(g("ifsc")),
                beneficiary_name=values.text(g("beneficiary_name")),
                verification_status=values.text(g("verification_status")),
                last_changed=_date(g("last_changed"), slot, "last changed", row, emp, notes)))
        elif slot == "change_log":
            built.append(ChangeRow(
                row, emp, key, field_changed=values.text(g("field_changed")), old_value=values.text(g("old_value")),
                new_value=values.text(g("new_value")),
                changed_on=_date(g("changed_on"), slot, "changed on", row, emp, notes),
                verification_status=values.text(g("verification_status"))))
        elif slot == "previous":
            net, _ = _decimal(g("net_pay"), slot, "net pay", row, emp, notes)
            total, _ = _decimal(g("total_payable"), slot, "total salary", row, emp, notes)
            built.append(PreviousRow(row, emp, key, net_pay=net, account_number=values.account(g("account_number")),
                                     ifsc=values.ifsc(g("ifsc")), total_payable=total))
        elif slot == "hold_list":
            built.append(HoldRow(row, emp, key, category=values.text(g("category")), reason=values.text(g("reason")),
                                 effective_date=_date(g("effective_date"), slot, "effective date", row, emp, notes)))
        elif slot == "offcycle":
            amount, _ = _decimal(g("amount"), slot, "amount", row, emp, notes)
            built.append(OffCycleRow(row, emp, key, amount=amount,
                                     payment_date=_date(g("payment_date"), slot, "payment date", row, emp, notes),
                                     reference=values.text(g("reference"))))
    return Table(built, present, filename)


def load(files: dict[str, tuple[str, bytes]], profile: dict[str, Any],
         template: dict[str, Any]) -> tuple[Inputs, templates.Parsed]:
    """
    ``files`` maps an input slot ("bank_file", "register", …) to (filename, bytes).
    Slots not given are absent — never empty — so the checks that need them report NOT_RUN.
    """
    if "bank_file" not in files:
        raise ValueError("Upload the bank payment file to be checked.")
    if "register" not in files:
        raise ValueError("Upload the current period's payroll register.")
    notes: list[Note] = []
    name, content = files["bank_file"]
    parsed = templates.read(content, name, template)
    inputs = Inputs(bank_file=parsed.bank, notes=notes)
    for slot in SLOTS:
        if slot not in files:
            continue
        spec = (profile.get("inputs") or {}).get(slot)
        if spec is None:
            raise ValueError(f"The profile {profile.get('name')!r} has no mapping for the {LABEL[slot]}.")
        fname, data = files[slot]
        setattr(inputs, slot, read_slot(slot, data, fname, spec, notes))
    return inputs, parsed
