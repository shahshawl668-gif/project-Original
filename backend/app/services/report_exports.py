"""One workbook implementation for direct and queued aggregate exports."""
from __future__ import annotations

import hashlib
import io
from datetime import UTC, date, datetime

from app.models import SalaryRegister
from app.services import report_builder, reporting


def build(db, entity, report, requester) -> tuple[bytes, dict]:
    spec = report_builder.validate(report.specification)
    if not spec["date_from"] or not spec["date_to"]:
        raise ValueError("Choose both period bounds before export")
    result = report_builder.preview(db, entity.id, spec, row_limit=None)
    registers = (db.query(SalaryRegister)
                 .filter(SalaryRegister.entity_id == entity.id,
                         SalaryRegister.period_month >= date.fromisoformat(spec["date_from"]),
                         SalaryRegister.period_month <= date.fromisoformat(spec["date_to"]))
                 .order_by(SalaryRegister.period_month, SalaryRegister.id).all())
    sources = [{"id": str(reg.id), "period": reg.period_month.isoformat(),
                "uploaded_at": reg.created_at.isoformat() if reg.created_at else None}
               for reg in registers]
    generated_at = datetime.now(UTC)
    wb = reporting._openpyxl().Workbook()
    reporting._provenance_sheet(wb, {
        "Module": "PeopleOps Reports", "Report": report.name,
        "Definition ID": str(report.id), "Definition version": report.version,
        "Entity": entity.name, "Entity code": getattr(entity, "code", "") or "",
        "Period from": spec["date_from"], "Period to": spec["date_to"],
        "Breakdown": spec["dimension"], "Filters": str(spec["filters"]),
        "Requested by": requester.email, "Generated at": generated_at.isoformat(timespec="seconds"),
        "Data basis": "Current stored data at generation; output is fixed after generation",
        "Outcome": result["status"], "Record count": result["record_count"],
        "Source register IDs": ", ".join(ref["id"] for ref in sources) or "none",
    })
    reporting._sheet(wb, "Summary", ["Metric", "Value"], [
        ["Matched records", result["record_count"]],
        *[[key.replace("_", " ").title(), value] for key, value in (result["control_totals"] or {}).items()],
    ])
    headers = spec["fields"]
    rows = [[date.fromisoformat(item[key]) if key == "period" and item[key]
             else item[key] for key in headers] for item in result["rows"]]
    reporting._sheet(wb, "Details", headers, rows)
    if "period" in headers:
        column = headers.index("period") + 1
        for sheet in wb.worksheets:
            if sheet.title.startswith("Details"):
                for cells in sheet.iter_cols(min_col=column, max_col=column, min_row=2):
                    for cell in cells:
                        cell.number_format = "mmm yyyy"
    reporting._basis_sheet(db, entity.id, {
        "date_from": date.fromisoformat(spec["date_from"]),
        "date_to": date.fromisoformat(spec["date_to"]),
    }, wb)
    payload = io.BytesIO()
    wb.save(payload)
    data = payload.getvalue()
    return data, {
        "record_count": result["record_count"],
        "control_totals": result["control_totals"],
        "source_references": sources,
        "sha256": hashlib.sha256(data).hexdigest(),
        "generated_at": generated_at,
    }
