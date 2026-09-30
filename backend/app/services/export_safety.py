"""
Spreadsheets built from uploaded data must not execute that data.

A register row whose employee name is ``=HYPERLINK("https://…","Click")`` is
text in the register. openpyxl stores any string starting with ``=`` as a
formula, so without this the exported workbook would carry a live formula that
runs in whoever opens it — the payroll team, an auditor. This product writes no
formulas on purpose, so every cell holding a string is forced to be text. The
value is unchanged: the cell reads exactly what the register said.

Leading ``+``, ``-`` and ``@`` are a CSV hazard, not an .xlsx one: in a
workbook those cells are already stored as text. CSV exports that carry
free text escape them where they are written (see config_bundle and
validation_matrix).
"""
from __future__ import annotations

from typing import Any
from collections.abc import Iterable


def neutralise_workbook(book) -> int:
    """Force every string cell of a normal (not write-only) workbook to text. Returns how many were formulas."""
    changed = 0
    for sheet in book.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.data_type == "f" and isinstance(cell.value, str):
                    cell.data_type = "s"
                    changed += 1
    return changed


def text_row(sheet, values: Iterable[Any]) -> list[Any]:
    """A row for a write-only sheet, with any formula-looking string written as text."""
    from openpyxl.cell import WriteOnlyCell

    out: list[Any] = []
    for value in values:
        if isinstance(value, str) and value.startswith("="):
            cell = WriteOnlyCell(sheet, value=value)
            cell.data_type = "s"
            out.append(cell)
        else:
            out.append(value)
    return out
