"""
One disbursement check, end to end: read the files, run the checks, write the
clean file, and freeze everything into the report that is stored and drawn
from. No database here — the router stores what this returns.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from app.services.disbursement import engine, inputs, outputs
from app.services.disbursement import template as templates
from app.services.disbursement.config import DO_NOT_RELEASE, Settings
from app.services.disbursement.engine import Result

INPUT_ORDER = ("bank_file", "register", "bank_master", "change_log", "previous", "hold_list", "offcycle")


@dataclass
class Checked:
    result: Result
    report: dict[str, Any]
    clean: bytes | None
    clean_filename: str | None


def clean_name(filename: str) -> str:
    path = PurePath(filename or "bank_file.csv")
    return f"{path.stem}_clean{path.suffix}"


def run_check(files: dict[str, tuple[str, bytes]], profile: dict[str, Any], template: dict[str, Any],
              settings: Settings, meta: dict[str, Any]) -> Checked:
    loaded, parsed = inputs.load(files, profile, template)
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
    report = outputs.build_report(result, {
        **meta,
        "profile": profile.get("name", profile.get("key")),
        "template": template.get("name", template.get("key")),
        "inputs": described,
        "settings": settings.snapshot(),
        "clean_filename": clean_filename,
        "clean_sha256": templates.fingerprint(clean) if clean is not None else None,
    }, loaded.bank_file.rows)
    return Checked(result, report, clean, clean_filename)
