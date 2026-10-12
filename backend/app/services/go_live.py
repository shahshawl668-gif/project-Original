"""
The parallel-run pack: GO_LIVE.md Phase 4 as a workbook the client signs.

A parallel run is one real, already-paid month validated alongside the client's
existing process, with the client's payroll lead walking every finding and
giving it one of four verdicts. The exit criteria are counts of those verdicts
— zero false positives, at least one true positive — plus three statements
only the client can make. This builds that workbook from a recorded run: every
finding with an empty yellow verdict cell, the checks the run could not
perform, and an exit-criteria tab whose formulas count the verdicts as they are
filled in. Nothing is pre-filled: a verdict the product chose for itself would
not be a review.
"""
from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy.orm import Session

from app.branding import PRODUCT_NAME
from app.models import Entity, FindingRecord, RegisterUpload, ValidationRun
from app.services.clock import india_today

FONT = "Arial"
INPUT_FILL = PatternFill("solid", fgColor="FFFF00")
HEAD_FILL = PatternFill("solid", fgColor="0C4A6E")
BAND_FILL = PatternFill("solid", fgColor="E0F2FE")
RISK_FILL = PatternFill("solid", fgColor="FEE2E2")
THIN = Side(style="thin", color="BFDBFE")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

VERDICTS = ("True positive", "Known and accepted", "Configuration error", "False positive")
VERDICT_MEANING = {
    "True positive": "A real defect the client did not know about. This is the product's value: record it.",
    "Known and accepted": "Real, and the client has a reason. Waive it in the product, with the reason.",
    "Configuration error": "The rule is right, the setup was wrong. Fix the configuration and validate again.",
    "False positive": "The product is wrong. Stop: the code is fixed before go-live.",
}


def _text(ws, row: int, col: int, value: Any, *, bold: bool = False, size: int = 10, color: str = "000000"):
    """A cell from data: a string that looks like a formula stays text."""
    cell = ws.cell(row=row, column=col, value=value)
    if isinstance(value, str) and value.startswith("="):
        cell.data_type = "s"
    cell.font = Font(FONT, size=size, bold=bold, color=color)
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    return cell


def _header(ws, row: int, headers: list[tuple[str, int]]) -> None:
    for i, (label, width) in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=i, value=label)
        cell.font = Font(FONT, size=10, bold=True, color="FFFFFF")
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = BOX
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _input(ws, row: int, col: int) -> None:
    cell = ws.cell(row=row, column=col)
    cell.fill = INPUT_FILL
    cell.border = BOX
    cell.font = Font(FONT, size=10)


def parallel_run_workbook(db: Session, entity: Entity, run: ValidationRun) -> tuple[bytes, dict[str, int]]:
    """The pack for one run, and how many findings it carries."""
    wb = Workbook()
    wb.remove(wb.active)
    month = run.period_month.strftime("%B %Y")

    # ---------------------------------------------------------------- guide
    ws = wb.create_sheet("How to use")
    ws.column_dimensions["A"].width = 110
    lines: list[tuple[str, int, bool, str]] = [
        (f"{PRODUCT_NAME} — parallel run, {entity.name}, {month}", 14, True, "0C4A6E"),
        ("", 10, False, "000000"),
        ("What this is", 11, True, "0C4A6E"),
        ("One real month that has already been paid, validated alongside your existing process. Nothing in "
         "your process changes and nothing is at risk. Your payroll lead walks every finding with the "
         "implementer and gives it a verdict. The month passes when the Exit criteria tab says so.", 10, False, "000000"),
        ("", 10, False, "000000"),
        ("What to do", 11, True, "0C4A6E"),
        ("1. On the Findings tab, give every finding a verdict in the yellow column. Nothing else is yellow.",
         10, False, "000000"),
        ("2. Write a note for any verdict other than True positive: the reason, or the configuration change.",
         10, False, "000000"),
        ("3. Read the Could not check tab. A check that could not run is not a pass; supply the input or "
         "accept the gap in writing.", 10, False, "000000"),
        ("4. Answer the three statements on the Exit criteria tab, then sign the Sign-off tab.", 10, False, "000000"),
        ("", 10, False, "000000"),
        ("The four verdicts", 11, True, "0C4A6E"),
        *[(f"{v} — {VERDICT_MEANING[v]}", 10, False, "000000") for v in VERDICTS],
        ("", 10, False, "000000"),
        ("A false positive is not a tuning exercise. A client shown one fabricated finding will not trust the "
         "ninety that are real, so any false positive stops the go-live until the rule is fixed.", 10, True, "991B1B"),
        ("", 10, False, "000000"),
        (f"Generated {india_today().isoformat()} from run #{run.run_number}. The findings are as the run "
         "recorded them; validating the month again makes a new run and needs a new pack.", 9, False, "475569"),
    ]
    for i, (text, size, bold, colour) in enumerate(lines, start=1):
        _text(ws, i, 1, text, bold=bold, size=size, color=colour)

    # ------------------------------------------------------------------ run
    ws = wb.create_sheet("Run")
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 70
    upload = db.get(RegisterUpload, run.upload_id) if run.upload_id else None
    facts = [
        ("Company", entity.name),
        ("Payroll month", month),
        ("Run", f"#{run.run_number} ({run.status})"),
        ("Run ID", str(run.id)),
        ("Validated at", run.finished_at.isoformat() if run.finished_at else ""),
        ("Engine version", run.engine_version or "not recorded"),
        ("Employees", run.employee_count),
        ("Findings", run.total_findings),
        ("Critical", run.critical_count),
        ("Warnings", run.warning_count),
        ("Source file", upload.filename if upload else "not recorded"),
        ("Source file SHA-256", upload.file_sha256 if upload else "not recorded"),
    ]
    for i, (k, v) in enumerate(facts, start=1):
        _text(ws, i, 1, k, bold=True)
        _text(ws, i, 2, v)

    # ------------------------------------------------------------- findings
    ws = wb.create_sheet("Findings")
    headers = [("Employee ID", 14), ("Employee", 22), ("Rule", 10), ("Check", 30), ("Severity", 11),
               ("Expected", 16), ("Actual", 16), ("Impact (₹)", 13), ("Reason", 50), ("Waived in product", 11),
               ("Verdict", 22), ("Note", 40), ("Reviewer", 14), ("Date", 12)]
    _header(ws, 1, headers)
    verdict_col = 11
    rows = (db.query(FindingRecord)
            .filter(FindingRecord.run_id == run.id, FindingRecord.status == "FAIL")
            .order_by(FindingRecord.severity, FindingRecord.rule_id, FindingRecord.employee_id)
            .all())
    r = 2
    for f in rows:
        values = [f.employee_id, f.employee_name, f.rule_id, f.rule_name, f.severity, f.expected_value,
                  f.actual_value, float(f.financial_impact or 0), f.reason, "yes" if f.was_waived else "no"]
        for c, v in enumerate(values, start=1):
            _text(ws, r, c, v).border = BOX
        for c in range(verdict_col, verdict_col + 4):
            _input(ws, r, c)
        r += 1
    last = max(r - 1, 2)
    dv = DataValidation(type="list", formula1='"' + ",".join(VERDICTS) + '"', allow_blank=True,
                        showErrorMessage=True, errorTitle="Verdict",
                        error="Choose one of the four verdicts.")
    ws.add_data_validation(dv)
    col = get_column_letter(verdict_col)
    dv.add(f"{col}2:{col}{last}")
    verdicts = f"Findings!${col}$2:${col}${last}"

    # -------------------------------------------------------- could not check
    ws = wb.create_sheet("Could not check")
    _header(ws, 1, [("Rule", 12), ("Check", 40), ("Employees it could not check", 16), ("Material", 10),
                    ("What it needed", 50), ("Supplied, or gap accepted by", 30)])
    coverage = (run.summary or {}).get("coverage") or {}
    missing = coverage.get("missing_inputs") or {}
    r = 2
    for rule in coverage.get("rules") or []:
        n = (rule.get("counts") or {}).get("cannot_validate", 0)
        if not n:
            continue
        for c, v in enumerate([rule["rule_id"], rule["name"], n, "yes" if rule.get("material") else "no"], start=1):
            _text(ws, r, c, v).border = BOX
        _text(ws, r, 5, "The inputs missing are listed below; the run's coverage in the product names "
              "each employee and what they lacked").border = BOX
        _input(ws, r, 6)
        r += 1
    if r == 2:
        _text(ws, 2, 1, "Every check that applied reached a verdict." if coverage else
              "This run recorded no coverage. Validate the month again before using this pack.")
    if missing:
        r += 1
        _text(ws, r, 1, "Inputs missing, by employees affected", bold=True)
        r += 1
        for label, n in missing.items():
            _text(ws, r, 1, label)
            _text(ws, r, 3, n)
            r += 1

    # --------------------------------------------------------- exit criteria
    ws = wb.create_sheet("Exit criteria")
    for c, w in (("A", 60), ("B", 16), ("C", 16)):
        ws.column_dimensions[c].width = w
    _text(ws, 1, 1, "Exit criteria — GO_LIVE.md Phase 4.2", bold=True, size=14, color="0C4A6E")
    _text(ws, 2, 1, "Counts update themselves from the Findings tab. Yellow cells take Y or N.", size=9,
          color="475569")
    _header(ws, 4, [("Verdict", 60), ("Findings", 16), ("", 16)])
    r = 5
    for v in VERDICTS:
        _text(ws, r, 1, v)
        ws.cell(row=r, column=2, value=f'=COUNTIF({verdicts},"{v}")')
        r += 1
    _text(ws, r, 1, "Not yet reviewed", bold=True)
    ws.cell(row=r, column=2, value=f"={len(rows)}-SUM(B5:B{r - 1})")
    unreviewed = r
    fp_row, tp_row = 5 + VERDICTS.index("False positive"), 5 + VERDICTS.index("True positive")
    r += 2
    _header(ws, r, [("Criterion", 60), ("Answer", 16), ("Status", 16)])
    r += 1
    first = r
    criteria = [
        ("Every finding has a verdict", f"=B{unreviewed}", f'=IF(B{r}=0,"MET","NOT MET")'),
        ("Zero false positives", f"=B{fp_row}", f'=IF(B{r + 1}=0,"MET","NOT MET")'),
        ("At least one true positive the client did not already know about", f"=B{tp_row}",
         f'=IF(B{r + 2}>=1,"MET","NOT MET")'),
    ]
    for label, answer, status in criteria:
        _text(ws, r, 1, label)
        ws.cell(row=r, column=2, value=answer).fill = BAND_FILL
        ws.cell(row=r, column=3, value=status).font = Font(FONT, size=10, bold=True)
        r += 1
    for label in ("Configuration errors are fixed and the month validated again (Y/N)",
                  "The payroll lead states in writing that the findings are sound (Y/N)",
                  "Cost dashboard totals match the client's management accounts (Y/N)",
                  "The journal voucher balances and the client's accountant accepts the mapping (Y/N)"):
        _text(ws, r, 1, label)
        _input(ws, r, 2)
        ws.cell(row=r, column=3, value=f'=IF(UPPER(B{r})="Y","MET","NOT MET")').font = Font(FONT, size=10, bold=True)
        r += 1
    r += 1
    _text(ws, r, 1, "Parallel run", bold=True, size=11)
    overall = ws.cell(row=r, column=3,
                      value=f'=IF(COUNTIF(C{first}:C{r - 2},"MET")={r - 1 - first},"PASSED","NOT YET")')
    overall.font = Font(FONT, size=11, bold=True)
    overall.fill = RISK_FILL
    if not rows:
        _text(ws, r + 2, 1, "This run raised no findings, so there is no true positive. Across two months, "
              "that means the product is not earning its place — worth knowing before charging for it.",
              size=9, color="991B1B")

    # -------------------------------------------------------------- sign-off
    ws = wb.create_sheet("Sign-off")
    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 50
    _text(ws, 1, 1, "Sign-off", bold=True, size=14, color="0C4A6E")
    r = 3
    for who in ("Client payroll lead", "Implementer"):
        _text(ws, r, 1, who, bold=True, size=11, color="0C4A6E")
        r += 1
        for label in ("Name", "Designation", "Date", "Signature"):
            _text(ws, r, 1, label)
            _input(ws, r, 2)
            r += 1
        r += 1
    _text(ws, r, 1, f"I have reviewed every finding in this pack for {entity.name}, {month}, and the verdicts "
          "recorded are my own.", size=10)
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), {"findings": len(rows)}
