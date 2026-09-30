"""
Uploaded files are data. A workbook built to exhaust memory is refused before
it is parsed, a macro is never run, and XML entity tricks are refused.
"""
from __future__ import annotations

import io
import json
import zipfile

import openpyxl
import pytest

from app.config import settings
from app.services import upload_safety
from tests.test_run_history import PERIOD, _company


def _bomb(expanded_mb: int) -> bytes:
    """A small file that declares a huge sheet — the shape of an .xlsx zip bomb."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/worksheets/sheet1.xml", b"0" * (expanded_mb * 1024 * 1024))
    return buf.getvalue()


def test_defusedxml_is_what_openpyxl_parses_with():
    from openpyxl.xml import DEFUSEDXML

    assert DEFUSEDXML is True, "defusedxml is missing: uploaded workbooks would be parsed without entity protection"


def test_a_workbook_that_expands_past_the_ceiling_is_refused_unread(client, monkeypatch):
    monkeypatch.setattr(settings, "max_workbook_expanded_mb", 5)
    bomb = _bomb(6)
    assert len(bomb) < 64 * 1024                           # small on the wire
    with pytest.raises(ValueError, match="expands to over 5 MB"):
        upload_safety.check_workbook(bomb)

    company = _company(client, "bomb")
    r = client.post("/api/payroll/upload", headers=company,
                    files={"file": ("register.xlsx", io.BytesIO(bomb), "application/octet-stream")},
                    data={"meta": json.dumps({"period_month": PERIOD})})
    assert 400 <= r.status_code < 500, r.text
    assert "expands to over 5 MB" in r.text


def test_something_that_is_not_a_zip_is_refused():
    with pytest.raises(ValueError, match="not a readable"):
        upload_safety.check_workbook(b"MZ\x90\x00 definitely not a workbook")


def test_a_macro_workbook_is_read_as_data_and_the_macro_is_never_loaded():
    book = openpyxl.Workbook()
    book.active.append(["employee_id", "basic"])
    book.active.append(["E1", 1000])
    buf = io.BytesIO()
    book.save(buf)
    # Graft a VBA project in, as an .xlsm would carry.
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.writestr("xl/vbaProject.bin", b"\xd0\xcf\x11\xe0 pretend macro")
    upload_safety.check_workbook(out.getvalue())
    from app.services.payroll_parse import parse_payroll_file

    frame = parse_payroll_file(out.getvalue(), "register.xlsx")
    assert frame.to_dict("records") == [{"employee_id": "E1", "basic": 1000}]
    reopened = openpyxl.load_workbook(io.BytesIO(out.getvalue()))
    assert getattr(reopened, "vba_archive", None) is None   # keep_vba is off: never read, never kept
