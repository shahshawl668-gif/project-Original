"""The configuration file: ordinary spreadsheet tables, as CSV or Excel.

Nothing in the file is code. Each kind of setting is a table with one row per
record and a column per setting; Yes/No for switches, plain numbers and dates,
and comma-separated lists. CSV carries all the tables in one file as
``section, record, field, value`` lines; Excel carries one sheet per table.

A table is only applied when it has at least one filled row, so a file that
includes only the sheets you changed leaves everything else alone.

The same adapters feed the existing validation and replace logic in
``routers.config_bundle``, which is the one place that decides what a bundle may
set; this module only translates between that and the spreadsheet.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import JSON
from sqlalchemy.orm import Session

from app.models import Entity, StatutorySettings
from app.schemas.statutory_config import ESICConfig, PFConfig
from app.services.config_service import ConfigService

MAX_ROWS = 10_000

# file section -> (columns, what the section is)
STATUTORY_FIELDS = [
    "pf_employee_rate", "pf_wage_ceiling", "pf_restrict_to_ceiling", "pf_employee_formula",
    "esic_employee_rate", "esic_wage_ceiling", "esic_rounding", "esic_employee_formula",
    "esic_full_month_on_entry", "esic_continue_month_on_exit", "pt_states", "lwf_states",
]
FILE_SECTIONS: dict[str, dict[str, Any]] = {
    "components": {
        "title": "Salary components",
        "fields": ["component_name", "pf_applicable", "esic_applicable", "pt_applicable", "lwf_applicable", "bonus_applicable", "included_in_wages", "taxable", "tax_exemption_type"],
        "bundle": "components",
    },
    "statutory": {"title": "PF, ESIC, PT and LWF settings (one row)", "fields": STATUTORY_FIELDS, "bundle": None},
    "pt_lwf_slabs": {
        "title": "Professional tax and LWF slabs",
        "fields": ["state", "rule_type", "min_salary", "max_salary", "deduction_amount", "employer_amount", "frequency", "gender", "applicable_months", "effective_from", "effective_to", "source_reference", "sort_order"],
        "bundle": "pt_lwf_slabs",
    },
    "minimum_wage_rates": {
        "title": "Minimum wage rates",
        "fields": ["state", "zone", "scheduled_employment", "skill_category", "basic_per_month", "vda_per_month", "working_days_basis", "effective_from", "effective_to", "source_reference"],
        "bundle": "minimum_wage_rates",
    },
    "minimum_wage_applicability": {
        "title": "Minimum wage applicability decision",
        "fields": ["effective_from", "applicable", "reason", "source_reference"],
        "bundle": "minimum_wage_applicability",
    },
    "rule_preferences": {"title": "Switched-off checks", "fields": ["rule_id", "suppressed"], "bundle": "rule_preferences"},
    "import_mappings": {
        "title": "Import column mappings (your file's heading -> product field)",
        "fields": ["profile", "file_column", "product_field"], "bundle": None,
    },
}
CSV_COLUMNS = ["section", "record", "field", "value"]
_TRUE = {"yes", "y", "true", "1"}
_FALSE = {"no", "n", "false", "0"}


# ── cell values ─────────────────────────────────────────────────────────────
def _show(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, Decimal):
        text = format(value.normalize(), "f")
        return text
    return str(value)


def _coerce(model, field: str, text: str, where: str) -> Any:
    """A cell's text as the value its column holds. Blank is None."""
    text = text.strip()
    if text == "":
        return None
    column = model.__table__.columns[field]
    try:
        if isinstance(column.type, JSON):
            return [int(p) if re.fullmatch(r"\d+", p) else p for p in (x.strip() for x in text.split(",")) if p]
        typ = column.type.python_type
        if typ is bool:
            low = text.lower()
            if low in _TRUE:
                return True
            if low in _FALSE:
                return False
            raise ValueError("use Yes or No")
        if typ is int:
            return int(Decimal(text))
        if typ is Decimal:
            value = Decimal(text.replace(",", ""))
            if not value.is_finite():
                raise ValueError("not a number")
            return value
        if typ is date:
            return date.fromisoformat(text).isoformat()
        return text
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f"{where}: “{text}” is not valid for {field.replace('_', ' ')} ({exc})") from exc


def _is_blank(row: dict[str, Any]) -> bool:
    return all(str(v).strip() == "" for v in row.values())


# ── bundle  <->  tables ─────────────────────────────────────────────────────
def to_tables(db: Session, entity: Entity, bundle: dict) -> dict[str, list[dict[str, str]]]:
    """The entity's current configuration as display-ready tables, one per file section."""
    sections = bundle["sections"]
    tables: dict[str, list[dict[str, str]]] = {}
    for name, spec in FILE_SECTIONS.items():
        if spec["bundle"]:
            tables[name] = [{f: _show(row.get(f)) for f in spec["fields"]} for row in sections.get(spec["bundle"], [])]

    cfg = ConfigService(db).get_full_config(entity.id)
    settings = db.get(StatutorySettings, entity.id)
    row = {
        "pf_employee_rate": cfg.pf.rates.employee_rate, "pf_wage_ceiling": cfg.pf.wage.wage_ceiling,
        "pf_restrict_to_ceiling": cfg.pf.wage.restrict_to_ceiling, "pf_employee_formula": cfg.pf.employee_formula,
        "esic_employee_rate": cfg.esic.rates.employee_rate, "esic_wage_ceiling": cfg.esic.wage.wage_ceiling,
        "esic_rounding": cfg.esic.rounding.mode, "esic_employee_formula": cfg.esic.employee_formula,
        "esic_full_month_on_entry": cfg.esic.eligibility.full_month_on_entry,
        "esic_continue_month_on_exit": cfg.esic.eligibility.continue_month_on_exit,
        "pt_states": (settings.pt_states if settings else []), "lwf_states": (settings.lwf_states if settings else []),
    }
    tables["statutory"] = [{f: _show(row[f]) for f in STATUTORY_FIELDS}]

    mappings: list[dict[str, str]] = []
    for profile in sections.get("salary_import_profiles", []):
        for file_column, field in (profile.get("column_mapping") or {}).items():
            mappings.append({"profile": profile["name"], "file_column": file_column, "product_field": str(field)})
    tables["import_mappings"] = mappings
    return {name: tables[name] for name in FILE_SECTIONS}


def to_bundle(db: Session, entity: Entity, tables: dict[str, list[dict[str, str]]]) -> dict:
    """Tables read from a file as a bundle the existing validator understands. Raises ValueError."""
    from app.routers.config_bundle import SECTIONS, _export

    current = _export(db, entity.id)["sections"]
    sections: dict[str, list[dict]] = {}
    for name, spec in FILE_SECTIONS.items():
        rows = [r for r in tables.get(name, []) if not _is_blank(r)]
        if not rows:
            continue
        if len(rows) > MAX_ROWS:
            raise ValueError(f"{spec['title']}: too many rows")
        if spec["bundle"]:
            model, fields = SECTIONS[spec["bundle"]]
            out = []
            for index, row in enumerate(rows, 1):
                unknown = set(row) - set(fields)
                if unknown:
                    raise ValueError(f"{spec['title']}: unknown column {sorted(unknown)[0]}")
                where = f"{spec['title']}, row {index}"
                out.append({f: _coerce(model, f, str(row.get(f, "")), where) for f in fields})
            sections[spec["bundle"]] = out
        elif name == "statutory":
            sections.update(_statutory_sections(current, rows[0], spec["title"]))
        elif name == "import_mappings":
            sections["salary_import_profiles"] = _profiles(rows, spec["title"])
    return {"format": "peopleopslab-config", "version": 1, "sections": sections}


def _statutory_sections(current: dict, row: dict[str, str], title: str) -> dict[str, list[dict]]:
    def text(key: str) -> str:
        return str(row.get(key, "")).strip()

    def number(key: str, default: Decimal) -> Decimal:
        if not text(key):
            return default
        try:
            return Decimal(text(key).replace(",", ""))
        except InvalidOperation as exc:
            raise ValueError(f"{title}: “{text(key)}” is not a number for {key.replace('_', ' ')}") from exc

    def yes_no(key: str, default: bool) -> bool:
        if not text(key):
            return default
        low = text(key).lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise ValueError(f"{title}: use Yes or No for {key.replace('_', ' ')}")

    def names(key: str, default: list) -> list:
        return [p.strip() for p in text(key).split(",") if p.strip()] if text(key) else default

    engine = (current.get("statutory_engine") or [{}])[0]
    pf = PFConfig.model_validate(engine.get("pf_config") or {})
    esic = ESICConfig.model_validate(engine.get("esic_config") or {})
    old = (current.get("statutory_settings") or [{}])[0]

    pf.rates.employee_rate = number("pf_employee_rate", pf.rates.employee_rate)
    pf.wage.wage_ceiling = number("pf_wage_ceiling", pf.wage.wage_ceiling)
    pf.wage.restrict_to_ceiling = yes_no("pf_restrict_to_ceiling", pf.wage.restrict_to_ceiling)
    pf.employee_formula = text("pf_employee_formula") or ""
    esic.rates.employee_rate = number("esic_employee_rate", esic.rates.employee_rate)
    esic.wage.wage_ceiling = number("esic_wage_ceiling", esic.wage.wage_ceiling)
    rounding = text("esic_rounding").lower() or esic.rounding.mode
    if rounding not in ("up", "down", "nearest"):
        raise ValueError(f"{title}: ESIC rounding must be up, down or nearest")
    esic.rounding.mode = rounding
    esic.employee_formula = text("esic_employee_formula") or ""
    esic.eligibility.full_month_on_entry = yes_no("esic_full_month_on_entry", esic.eligibility.full_month_on_entry)
    esic.eligibility.continue_month_on_exit = yes_no("esic_continue_month_on_exit", esic.eligibility.continue_month_on_exit)

    settings = {
        "pf_wage_ceiling": pf.wage.wage_ceiling, "pf_employee_rate": pf.rates.employee_rate,
        "pf_employer_rate": old.get("pf_employer_rate", pf.rates.employer_rate),
        "pf_eps_rate": old.get("pf_eps_rate", pf.rates.eps_rate),
        "pf_edli_rate": old.get("pf_edli_rate", pf.rates.edli_rate),
        "pf_admin_rate": old.get("pf_admin_rate", pf.rates.admin_rate),
        "pf_restrict_to_ceiling": pf.wage.restrict_to_ceiling,
        "esic_wage_ceiling": esic.wage.wage_ceiling, "esic_employee_rate": esic.rates.employee_rate,
        "esic_employer_rate": old.get("esic_employer_rate", esic.rates.employer_rate),
        "esic_round_mode": esic.rounding.mode,
        "pt_states": names("pt_states", old.get("pt_states", [])),
        "lwf_states": names("lwf_states", old.get("lwf_states", [])),
    }
    return {
        "statutory_settings": [settings],
        "statutory_engine": [{
            "pf_config": pf.model_dump(mode="json"), "esic_config": esic.model_dump(mode="json"),
            "component_mapping_config": engine.get("component_mapping_config"),
            "income_tax_config": engine.get("income_tax_config"),
            "rule_thresholds_config": engine.get("rule_thresholds_config"),
            "exposure_config": engine.get("exposure_config"),
        }],
    }


def _profiles(rows: list[dict[str, str]], title: str) -> list[dict]:
    grouped: dict[str, dict[str, str]] = {}
    for index, row in enumerate(rows, 1):
        profile, column, field = (str(row.get(k, "")).strip() for k in ("profile", "file_column", "product_field"))
        if not (profile and column and field):
            raise ValueError(f"{title}, row {index}: profile, file column and product field are all needed")
        grouped.setdefault(profile, {})[column] = field
    return [{"name": name, "column_mapping": mapping} for name, mapping in grouped.items()]


# ── files ───────────────────────────────────────────────────────────────────
def tables_to_csv(tables: dict[str, list[dict[str, str]]]) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for name, spec in FILE_SECTIONS.items():
        rows = tables.get(name) or [dict.fromkeys(spec["fields"], "")]   # a blank record shows the columns
        for record, row in enumerate(rows, 1):
            for field in spec["fields"]:
                value = row.get(field, "")
                # Keep text a spreadsheet would evaluate as a formula from being one.
                if value[:1] in ("=", "+", "-", "@") and not re.fullmatch(r"-?\d+(\.\d+)?", value):
                    value = "'" + value
                writer.writerow([name, record, field, value])
    return ("﻿" + out.getvalue()).encode("utf-8")


def csv_to_tables(raw: bytes) -> dict[str, list[dict[str, str]]]:
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    except UnicodeError as exc:
        raise ValueError(f"The file cannot be read as text: {exc}") from exc
    if reader.fieldnames != CSV_COLUMNS:
        raise ValueError(f"The first line must be: {', '.join(CSV_COLUMNS)}")
    records: dict[str, dict[int, dict[str, str]]] = {}
    try:
        for line_number, line in enumerate(reader, 2):
            if line_number > MAX_ROWS * 30:
                raise ValueError("The file has too many lines")
            if None in line or any(v is None for v in line.values()):
                raise ValueError(f"Line {line_number} does not have four columns")
            section, field, value = line["section"].strip(), line["field"].strip(), line["value"]
            if section not in FILE_SECTIONS:
                raise ValueError(f"Line {line_number}: “{section}” is not a section of this file")
            if field not in FILE_SECTIONS[section]["fields"]:
                raise ValueError(f"Line {line_number}: “{field}” is not a column of {section}")
            try:
                record = int(line["record"])
            except ValueError as exc:
                raise ValueError(f"Line {line_number}: record must be a number") from exc
            if value.startswith("'"):
                value = value[1:]
            records.setdefault(section, {}).setdefault(record, {})[field] = value
    except csv.Error as exc:
        raise ValueError(f"The file cannot be read: {exc}") from exc
    return {section: [rows[i] for i in sorted(rows)] for section, rows in records.items()}


def tables_to_xlsx(tables: dict[str, list[dict[str, str]]]) -> bytes:
    wb = Workbook()
    guide = wb.active
    guide.title = "Read me"
    guide.append(["Sheet", "What it holds"])
    for name, spec in FILE_SECTIONS.items():
        guide.append([name, spec["title"]])
    guide.append([])
    for line in (
        "Edit the sheets you want to change and upload the file; sheets you leave empty are not touched.",
        "A sheet is applied when it has at least one filled row, and replaces that kind of setting.",
        "Use Yes or No for switches, YYYY-MM-DD for dates, and commas between list items (states, months).",
        "The statutory sheet is a single row.",
    ):
        guide.append([line])
    guide.column_dimensions["A"].width = 28
    guide.column_dimensions["B"].width = 70
    head_fill = PatternFill("solid", fgColor="1F4E79")
    for cell in guide[1]:
        cell.font = Font(bold=True)
    for name, spec in FILE_SECTIONS.items():
        sheet = wb.create_sheet(name[:31])
        sheet.append(spec["fields"])
        for row in tables.get(name, []):
            sheet.append([row.get(f, "") for f in spec["fields"]])
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = head_fill
            cell.alignment = Alignment(horizontal="center")
        for index, field in enumerate(spec["fields"], 1):
            sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = max(14, len(field) + 4)
        sheet.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def xlsx_to_tables(raw: bytes) -> dict[str, list[dict[str, str]]]:
    try:
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 — any unreadable workbook is the user's file, not ours
        raise ValueError(f"The Excel file cannot be read: {exc}") from exc
    tables: dict[str, list[dict[str, str]]] = {}
    for name, spec in FILE_SECTIONS.items():
        if name[:31] not in wb.sheetnames:
            continue
        rows = list(wb[name[:31]].iter_rows(values_only=True))
        if not rows:
            continue
        header = [str(h).strip() if h is not None else "" for h in rows[0]]
        unknown = [h for h in header if h and h not in spec["fields"]]
        if unknown:
            raise ValueError(f"Sheet {name}: “{unknown[0]}” is not a column of this sheet")
        tables[name] = [
            {h: ("" if v is None else v.isoformat()[:10] if isinstance(v, date) else str(v)) for h, v in zip(header, row, strict=False) if h}
            for row in rows[1:]
        ]
    return tables
