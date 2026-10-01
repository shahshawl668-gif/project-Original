"""
Mapping samples are read on the server, never in the browser.

The mapping editor used to parse uploaded spreadsheets in the browser with the
``xlsx`` package, which carries advisories with no fix on npm. The server's
checked reader does it instead: size and expansion limits before a workbook is
opened, values as text, nothing stored.
"""
from __future__ import annotations

import io
import zipfile

from openpyxl import Workbook

from app.config import settings
from tests.test_run_history import _company, _data

URL = "/api/studio/mappings/sample"


def _xlsx(rows: list[list[object]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _send(client, headers, name: str, content: bytes, kind: str = "application/octet-stream"):
    return client.post(URL, headers=headers, files={"file": (name, content, kind)})


def test_a_csv_sample_is_read_as_text(client):
    headers = _company(client, "samplecsv")
    csv = b"Employee Code,Name,Basic\n0042,Asha,25000\n0043,,\n"
    out = _data(_send(client, headers, "people.csv", csv, "text/csv"))
    assert out["rows"] == 2 and out["truncated"] is False
    assert out["records"][0] == {"Employee Code": "0042", "Name": "Asha", "Basic": "25000"}
    # An empty cell is absent, not an empty string and not zero.
    assert out["records"][1] == {"Employee Code": "0043", "Name": None, "Basic": None}


def test_an_xlsx_sample_is_read_as_text(client):
    headers = _company(client, "samplexlsx")
    book = _xlsx([["Employee Code", "Name", "Basic"], ["0042", "Asha", 25000], ["0043", "Ravi", None]])
    out = _data(_send(client, headers, "people.xlsx", book))
    assert out["records"][0] == {"Employee Code": "0042", "Name": "Asha", "Basic": "25000"}
    assert out["records"][1]["Basic"] is None


def test_a_long_sample_is_cut_short_not_refused(client):
    headers = _company(client, "samplelong")
    csv = "Code\n" + "".join(f"{i:04d}\n" for i in range(600))
    out = _data(_send(client, headers, "long.csv", csv.encode(), "text/csv"))
    assert out["rows"] == 500 and out["truncated"] is True
    assert out["records"][0] == {"Code": "0000"} and out["records"][-1] == {"Code": "0499"}


def test_what_is_not_a_plain_workbook_is_refused(client, monkeypatch):
    headers = _company(client, "samplebad")
    assert _send(client, headers, "macro.xlsm", b"anything").status_code == 400
    assert _send(client, headers, "notes.txt", b"a,b\n1,2\n").status_code == 400
    garbage = _send(client, headers, "fake.xlsx", b"this is not a zip")
    assert garbage.status_code == 400 and "not a readable .xlsx" in garbage.json()["error"]["detail"]

    # A zip that is not a workbook is refused, not a server error.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "hi")
    other = _send(client, headers, "zip.xlsx", buf.getvalue())
    assert other.status_code == 400, other.text

    # A workbook that expands past the limit is refused before it is opened.
    monkeypatch.setattr(settings, "max_workbook_expanded_mb", 0)
    big = _send(client, headers, "people.xlsx", _xlsx([["Code"], ["0042"]]))
    assert big.status_code == 400 and "expands to over" in big.json()["error"]["detail"]


def test_only_studio_members_of_the_company_can_use_it(client):
    headers = _company(client, "sampleauth")
    csv = b"Code\n0042\n"
    assert client.post(URL, files={"file": ("a.csv", csv, "text/csv")}).status_code == 401
    stranger = _company(client, "samplestranger")
    foreign = {**stranger, "X-Entity-Id": headers["X-Entity-Id"]}
    assert _send(client, foreign, "a.csv", csv, "text/csv").status_code == 404
