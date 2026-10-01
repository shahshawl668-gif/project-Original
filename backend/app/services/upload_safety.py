"""
Checks on an uploaded workbook before anything parses it.

An .xlsx file is a zip of XML. A few kilobytes can declare gigabytes of
content, and pandas reads a whole sheet into memory: one such upload would
take the API process down for every client on it. The zip's own directory
says how large each member will be once expanded, so the check costs nothing
and happens before a byte is inflated.

Nothing in an upload is ever executed. openpyxl drops VBA projects (an .xlsm's
macros are not even read), formulas are read as their text or their cached
values, and XML entity expansion is refused by defusedxml (required in
requirements.txt; tests/test_upload_safety.py fails if it goes missing).
"""
from __future__ import annotations

import io
import zipfile

from app.config import settings

MAX_MEMBERS = 10_000


def check_workbook(content: bytes) -> None:
    """Raise ValueError if the bytes are not a workbook this server should open."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError("The file is not a readable .xlsx workbook.") from exc
    with archive:
        members = archive.infolist()
        if len(members) > MAX_MEMBERS:
            raise ValueError("The workbook has more parts than any payroll file needs.")
        expanded = sum(m.file_size for m in members)
        ceiling = settings.max_workbook_expanded_mb * 1024 * 1024
        if expanded > ceiling:
            raise ValueError(
                f"The workbook expands to over {settings.max_workbook_expanded_mb} MB. "
                "Save it as .csv, or split it, and upload again."
            )
