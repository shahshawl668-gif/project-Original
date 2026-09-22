"""
Downloadable reports, each one able to say where it came from.

Every workbook opens with a provenance sheet: which entity, which period range,
which filters were applied, when the underlying registers were last uploaded,
who generated it and when. A payroll report that circulates by email without
that header becomes an orphan figure within a week — someone finds it in a
folder in November and cannot tell what it covered.

Reports are built from the same services the dashboards read, never from a
second query written for export. A report that disagrees with the screen it was
downloaded from destroys confidence in both.
"""
from __future__ import annotations

import io
import uuid
from datetime import date, datetime, UTC
from decimal import Decimal
from typing import Any
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.models import SalaryRegister


def _openpyxl():
    try:
        import openpyxl  # noqa: F401
        from openpyxl.styles import Alignment, Font, PatternFill  # noqa: F401
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise RuntimeError("openpyxl is required to generate reports") from exc
    import openpyxl

    return openpyxl


HEADER_FILL = "1F2A44"
SUBHEAD_FILL = "EEF1F6"


def _style_header(ws, row: int, columns: int) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill

    for column in range(1, columns + 1):
        cell = ws.cell(row=row, column=column)
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    # A cell *reference*, not ws.cell(...): asking openpyxl for a cell creates
    # it, which would push max_row past the header and leave every sheet with a
    # blank row between its headings and its first figure.
    ws.freeze_panes = f"A{row + 1}"


def _autosize(ws, minimum: int = 10, maximum: int = 46) -> None:
    for column in ws.columns:
        longest = max((len(str(c.value)) for c in column if c.value is not None), default=0)
        letter = column[0].column_letter
        ws.column_dimensions[letter].width = max(minimum, min(maximum, longest + 2))


def _sheet(wb, title: str, headers: list[str], rows: list[list[Any]]):
    ws = wb.create_sheet(title[:31])
    ws.append(headers)
    _style_header(ws, 1, len(headers))
    for row in rows:
        ws.append(row)
    _autosize(ws)
    return ws


def _provenance_sheet(wb, meta: dict) -> None:
    from openpyxl.styles import Font

    ws = wb.active
    ws.title = "About this report"
    ws.append(["PayrollCheck report"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    for label, value in meta.items():
        ws.append([label, value])
    for row in range(3, 3 + len(meta)):
        ws.cell(row=row, column=1).font = Font(bold=True, size=10)
    ws.append([])
    ws.append([
        "Note",
        "Figures are derived from the salary registers stored in this workspace. "
        "Forecast figures, where present, are projections from stated assumptions "
        "and are not financial results.",
    ])
    _autosize(ws, minimum=22, maximum=90)


def _freshness(db: Session, entity_id: uuid.UUID) -> dict:
    registers = (
        db.query(SalaryRegister)
        .filter(SalaryRegister.entity_id == entity_id)
        .order_by(SalaryRegister.period_month.desc())
        .all()
    )
    if not registers:
        return {"latest_period": None, "last_uploaded_at": None, "register_count": 0}
    newest_upload = max((r.created_at for r in registers if r.created_at), default=None)
    return {
        "latest_period": registers[0].period_month.strftime("%b %Y"),
        "last_uploaded_at": newest_upload.isoformat() if newest_upload else None,
        "register_count": len(registers),
    }


# ---------------------------------------------------------------------------
# The reports
# ---------------------------------------------------------------------------
def _management_summary(db, entity_id, ctx, wb) -> None:
    from app.services.analytics import cost_analysis
    from app.services.cost_model import MEASURES

    analysis = cost_analysis(
        db, entity_id, group_by=ctx["group_by"], granularity="month",
        measure="ctc", date_from=ctx["date_from"], date_to=ctx["date_to"],
        filters=ctx["filters"],
    )
    totals = analysis["totals"]

    _sheet(wb, "Summary", ["Measure", "Amount (INR)"], [
        ["Total CTC", totals["ctc"]],
        ["Gross pay", totals["gross"]],
        ["Employer contributions", totals["employer_cost"]],
        ["Employee deductions", totals["deductions"]],
        ["Net payout", totals["net"]],
        ["Headcount (distinct employees)", totals["headcount"]],
        ["Cost per head (CTC ÷ distinct employees)", totals["cost_per_head"]],
    ])

    _sheet(wb, "By month", ["Period", "Gross", "Employer cost", "Total CTC",
                            "Deductions", "Net", "Headcount"],
           [[p["label"], p["measures"]["gross"], p["measures"]["employer_cost"],
             p["measures"]["ctc"], p["measures"]["deductions"], p["measures"]["net"],
             p["headcount"]] for p in analysis["period_totals"]])

    _sheet(wb, "Components", ["Layer", "Component", "Amount (INR)", "Share of CTC %"],
           [[m.layer, m.label, totals[m.key],
             round(totals[m.key] / totals["ctc"] * 100, 2) if totals["ctc"] else 0]
            for m in MEASURES])


def _department_cost(db, entity_id, ctx, wb) -> None:
    from app.services.analytics import cost_analysis

    analysis = cost_analysis(
        db, entity_id, group_by=ctx["group_by"], granularity="month",
        measure="ctc", date_from=ctx["date_from"], date_to=ctx["date_to"],
        filters=ctx["filters"],
    )
    label = analysis["group_by_label"]

    _sheet(wb, "By " + label[:24], [label, "Gross", "Employer cost", "Total CTC", "Share %"],
           [[g["group"], g["measures"]["gross"], g["measures"]["employer_cost"],
             g["measures"]["ctc"], g["share_pct"]] for g in analysis["matrix"]])

    headers = [label] + [p["label"] for p in analysis["periods"]] + ["Total"]
    rows = []
    for group in analysis["matrix"]:
        by_period = {s["period"]: s["value"] for s in group["series"]}
        rows.append([group["group"]] + [by_period.get(p["key"], 0) for p in analysis["periods"]]
                    + [group["total"]])
    _sheet(wb, "Monthly matrix", headers, rows)


def _headcount(db, entity_id, ctx, wb) -> None:
    from app.services.workforce_analytics import headcount_movement

    movement = headcount_movement(
        db, entity_id, date_from=ctx["date_from"], date_to=ctx["date_to"],
        filters=ctx["filters"],
    )
    _sheet(wb, "Movement",
           ["Period", "Opening", "Joiners", "Exits", "Closing", "Net change",
            "Average headcount", "Total CTC", "Cost per head (closing)",
            "Cost per head (average)", "Master agrees"],
           [[p["label"], p["opening"], p["joiners"], p["exits"], p["closing"],
             p["net_change"], p["average_headcount"], p["total_ctc"],
             p["cost_per_head_closing"], p["cost_per_head_average"],
             "yes" if p["master_agrees"] else "check"] for p in movement["periods"]])

    from app.services.analytics import cost_analysis

    for dimension in ("department", "work_location", "grade", "employment_type"):
        analysis = cost_analysis(
            db, entity_id, group_by=dimension, granularity="month", measure="ctc",
            date_from=ctx["date_from"], date_to=ctx["date_to"], filters=ctx["filters"],
        )
        last = analysis["periods"][-1]["key"] if analysis["periods"] else None
        _sheet(wb, "By " + analysis["group_by_label"][:24],
               [analysis["group_by_label"], "Headcount (latest period)", "Total CTC"],
               [[g["group"],
                 next((s["headcount"] for s in g["series"] if s["period"] == last), 0),
                 g["measures"]["ctc"]] for g in analysis["matrix"]])


def _compensation(db, entity_id, ctx, wb) -> None:
    from app.services.workforce_analytics import compensation_analysis

    result = compensation_analysis(
        db, entity_id, period=ctx["date_to"], group_by=ctx["group_by"], filters=ctx["filters"],
    )
    overall = result["overall"]
    _sheet(wb, "Distribution", ["Statistic", "Annualised CTC (INR)"], [
        ["Employees", overall["count"]],
        ["Mean", overall["mean"]],
        ["Median", overall["median"]],
        ["25th percentile", overall["p25"]],
        ["75th percentile", overall["p75"]],
        ["90th percentile", overall["p90"]],
        ["Minimum", overall["min"]],
        ["Maximum", overall["max"]],
        ["Range ratio (max ÷ min)", overall["range_ratio"]],
        ["Basis", result["basis"]],
        ["Period", result["period_label"]],
    ])
    _sheet(wb, "By " + result["group_by_label"][:24],
           [result["group_by_label"], "Employees", "Median", "Mean", "P25", "P75",
            "Minimum", "Maximum"],
           [[g["group"], g["count"], g["median"], g["mean"], g["p25"], g["p75"],
             g["min"], g["max"]] for g in result["groups"]])
    _sheet(wb, "Salary bands", ["From", "To", "Employees"],
           [[b["from"], b["to"], b["count"]] for b in result["distribution"]])
    _sheet(wb, "Fixed vs variable", ["Element", "Amount (INR)", "Share %"], [
        ["Fixed pay", result["mix"]["fixed"], result["mix"]["fixed_pct"]],
        ["Variable pay", result["mix"]["variable"], result["mix"]["variable_pct"]],
    ])


def _statutory(db, entity_id, ctx, wb) -> None:
    from app.services.analytics import cost_analysis, statutory_exposure
    from app.services.compliance_calendar import filing_calendar
    from app.services.config_service import ConfigService
    from app.services.cost_model import DEDUCTION_KEYS, EMPLOYER_KEYS, MEASURE_BY_KEY

    analysis = cost_analysis(
        db, entity_id, group_by=ctx["group_by"], granularity="month", measure="ctc",
        date_from=ctx["date_from"], date_to=ctx["date_to"], filters=ctx["filters"],
    )
    _sheet(wb, "Statutory cost", ["Period"] + [MEASURE_BY_KEY[k].label
                                               for k in EMPLOYER_KEYS + DEDUCTION_KEYS],
           [[p["label"]] + [p["measures"][k] for k in EMPLOYER_KEYS + DEDUCTION_KEYS]
            for p in analysis["period_totals"]])

    _sheet(wb, "Source of figures", ["Basis", "Amount (INR)"], [
        ["Reported by the payroll system", analysis["sources"]["reported"]],
        ["Computed by this engine", analysis["sources"]["computed"]],
    ])

    calendar = filing_calendar(db, entity_id, months=12)
    _sheet(wb, "Filing readiness",
           ["Wage month", "Obligation", "Authority", "Due date", "Days left",
            "Status", "Open findings", "At risk (INR)"],
           [[period["period_label"], o["label"], o["authority"], o["due_date"],
             o["days_left"], o["status"], o["open_findings"], o["at_risk_amount"]]
            for period in calendar["periods"] for o in period["obligations"]])

    exposure = statutory_exposure(db, entity_id, ConfigService(db).get_exposure_config(entity_id))
    _sheet(wb, "Exposure", ["Head", "Principal", "Interest", "Damages", "Total",
                            "Findings", "Oldest period"],
           [[h["head"].upper(), h["principal"], h["interest"], h["damages"], h["total"],
             h["finding_count"], h["oldest_period"]] for h in exposure["by_head"]])


def _budget_variance(db, entity_id, ctx, wb) -> None:
    from app.services.budgeting import budget_variance

    result = budget_variance(
        db, entity_id, date_from=ctx["date_from"], date_to=ctx["date_to"],
        filters=ctx["filters"],
    )
    if result["version"] is None:
        _sheet(wb, "Budget variance", ["Status"], [[result["note"]]])
        return

    version = result["version"]
    _sheet(wb, "Budget", ["Field", "Value"], [
        ["Budget version", version["name"]],
        ["Financial year", version["financial_year"]],
        ["Approved at level", version["scope_key"]],
        ["Measure", version["measure"]],
        ["Approved by", version["approved_by"]],
        ["Approved at", version["approved_at"]],
    ])
    _sheet(wb, "By month",
           ["Period", "Actual", "Budget", "Variance", "Variance %", "Utilisation %"],
           [[p["label"], p["actual"], p["budget"], p["variance"], p["variance_pct"],
             p["utilisation_pct"]] for p in result["periods"]])
    if result["scopes"]:
        _sheet(wb, "By scope",
               ["Scope", "Actual", "Budget", "Variance", "Variance %", "Utilisation %"],
               [[s["scope"], s["actual"], s["budget"], s["variance"], s["variance_pct"],
                 s["utilisation_pct"]] for s in result["scopes"]])


def _component_breakdown(db, entity_id, ctx, wb) -> None:
    from app.services.analytics import cost_analysis
    from app.services.cost_model import MEASURES

    analysis = cost_analysis(
        db, entity_id, group_by=ctx["group_by"], granularity="month", measure="ctc",
        date_from=ctx["date_from"], date_to=ctx["date_to"], filters=ctx["filters"],
    )
    headers = ["Period"] + [m.label for m in MEASURES] + ["Gross", "Employer cost",
                                                          "Total CTC", "Deductions", "Net"]
    rows = [[p["label"]] + [p["measures"][m.key] for m in MEASURES]
            + [p["measures"][k] for k in ("gross", "employer_cost", "ctc", "deductions", "net")]
            for p in analysis["period_totals"]]
    _sheet(wb, "Components by month", headers, rows)

    label = analysis["group_by_label"]
    _sheet(wb, "Components by " + label[:18],
           [label] + [m.label for m in MEASURES] + ["Total CTC"],
           [[g["group"]] + [g["measures"][m.key] for m in MEASURES] + [g["measures"]["ctc"]]
            for g in analysis["matrix"]])


def _reconciliation(db, entity_id, ctx, wb) -> None:
    from app.models import FindingState

    states = (
        db.query(FindingState)
        .filter(FindingState.entity_id == entity_id)
        .order_by(FindingState.last_seen_period.desc())
        .all()
    )
    identity = ctx["identity"]
    _sheet(wb, "Exceptions",
           ["Rule", "Rule name", "Severity", "State", "Employee", "Component",
            "First seen", "Last seen", "Occurrences", "Financial impact (INR)",
            "Decided by", "Note"],
           [[s.rule_id, s.rule_name, s.severity, s.state,
             identity.employee(s.employee_id, s.employee_name)["employee_id"],
             s.component, s.first_seen_period.isoformat(), s.last_seen_period.isoformat(),
             s.occurrence_count, float(s.last_financial_impact or 0),
             getattr(s, "decided_by_email", None), s.note] for s in states])

    counts: dict[tuple[str, str], int] = {}
    for state in states:
        counts[(state.severity, state.state)] = counts.get((state.severity, state.state), 0) + 1
    _sheet(wb, "Exception summary", ["Severity", "State", "Count"],
           [[severity, state, count] for (severity, state), count in sorted(counts.items())])


def _bank_jv_reconciliation(db, entity_id, ctx, wb) -> None:
    """
    The month held three ways: register, bank file, journal voucher.

    Where a comparison could not be made, the sheet says so instead of being
    absent. A reconciliation pack whose missing halves are simply missing reads
    as a clean month, which is the one impression it must never give.
    """
    from app.models import BankFile, JvTemplate
    from app.services import reconciliation as recon

    identity = ctx["identity"]
    period = ctx.get("date_to") or _latest_period(db, entity_id)
    if period is None:
        _sheet(wb, "Reconciliation", ["Status"],
               [["No salary register is stored, so there is nothing to reconcile."]])
        return
    period = period.replace(day=1)

    register = recon.register_net(db, entity_id, period)
    bank = (
        db.query(BankFile)
        .filter(BankFile.entity_id == entity_id, BankFile.period_month == period)
        .order_by(BankFile.created_at.desc())
        .first()
    )

    if bank is None:
        _sheet(wb, "Bank reconciliation", ["Status", "Period", "Net pay due (INR)"],
               [["No bank file has been uploaded for this month. Payments are "
                 "UNRECONCILED — this is not a clean result.",
                 period.strftime("%b %Y"),
                 float(sum((e.expected for e in register), Decimal("0")))]])
    else:
        result = recon.bank_reconciliation(db, entity_id, period, bank)
        summary = result["summary"]
        _sheet(wb, "Bank reconciliation",
               ["Measure", "Value"],
               [["Period", period.strftime("%b %Y")],
                ["Bank file", bank.filename or ""],
                ["Employees on the register", summary["register_employees"]],
                ["Payment lines in the file", summary["bank_rows"]],
                ["Matched on employee code", summary["matched"]],
                ["Net pay due (INR)", summary["due_total"]],
                ["Paid by the file (INR)", summary["paid_total"]],
                ["Difference (INR)", summary["difference"]],
                ["Reconciled", "yes" if summary["reconciled"] else "no"]])

        _sheet(wb, "Bank exceptions",
               ["Severity", "Exception", "Employee", "Name", "Expected (INR)",
                "Paid (INR)", "Difference (INR)", "What it means", "What to do"],
               [[e["severity"], e["label"],
                 identity.employee(e["employee_id"], e["employee_name"])["employee_id"]
                 if e["employee_id"] else "",
                 identity.employee(e["employee_id"], e["employee_name"])["employee_name"]
                 if e["employee_id"] else "",
                 e["expected"], e["actual"], e["difference"], e["meaning"], e["action"]]
                for e in result["exceptions"]])

    template = (
        db.query(JvTemplate)
        .filter(JvTemplate.entity_id == entity_id, JvTemplate.is_current.is_(True))
        .first()
    )
    if template is None:
        _sheet(wb, "Journal voucher", ["Status"],
               [["No JV template is approved for this entity, so no voucher could be "
                 "built. Nothing has been posted to the ledger from this product."]])
        return

    jv = recon.jv_reconciliation(db, entity_id, period, template)
    _sheet(wb, "Journal voucher",
           ["Voucher", "Date", "Account code", "Account", "Cost centre",
            "Debit (INR)", "Credit (INR)", "Narration"],
           [[v["number"], v["date"], line["account_code"], line["account_name"],
             line["cost_center"] or "", line["debit"], line["credit"], v["narration"]]
            for v in jv["vouchers"] for line in v["lines"]])

    _sheet(wb, "Voucher check", ["Measure", "Value"],
           [["Template", template.name],
            ["Approved by", template.approved_by_email or "not approved"],
            ["Posting basis", template.posting_basis],
            ["Total debits (INR)", jv["summary"]["total_debit"]],
            ["Total credits (INR)", jv["summary"]["total_credit"]],
            ["Difference (INR)", jv["summary"]["difference"]],
            ["Payroll cost for the month (INR)", jv["summary"]["payroll_cost"]],
            ["Balanced", "yes" if jv["balanced"] else "no"]])

    _sheet(wb, "Voucher exceptions",
           ["Severity", "Exception", "Detail", "Expected (INR)", "Actual (INR)",
            "Difference (INR)", "What to do"],
           [[e["severity"], e["label"], e["title"], e["expected"], e["actual"],
             e["difference"], e["action"]] for e in jv["exceptions"]])


def _latest_period(db, entity_id):
    row = (
        db.query(SalaryRegister.period_month)
        .filter(SalaryRegister.entity_id == entity_id)
        .order_by(SalaryRegister.period_month.desc())
        .first()
    )
    return row[0] if row else None


def _employee_cost(db, entity_id, ctx, wb) -> None:
    from app.services.analytics import _Costing, _register_rows
    from app.services.cost_model import MEASURES
    from app.services.dimensions import DIMENSIONS, UNASSIGNED

    rows, by_register = _register_rows(db, entity_id, ctx["date_from"], ctx["date_to"])
    costing = _Costing(db, entity_id)
    identity = ctx["identity"]
    active = {k: set(v) for k, v in (ctx["filters"] or {}).items() if v}

    headers = (["Period", "Employee", "Name"]
               + [label for _, label in DIMENSIONS]
               + [m.label for m in MEASURES]
               + ["Gross", "Employer cost", "Total CTC", "Deductions", "Net"])
    out = []
    for row in rows:
        dims = row.dimensions or {}
        if any(dims.get(key, UNASSIGNED) not in wanted for key, wanted in active.items()):
            continue
        who = identity.employee(row.employee_id, row.employee_name)
        measures = costing.cost(row).measures
        from app.services.cost_model import with_derived

        full = with_derived(measures)
        out.append(
            [by_register[row.register_id].period_month.strftime("%b %Y"),
             who["employee_id"], who["employee_name"]]
            + [dims.get(key, UNASSIGNED) for key, _ in DIMENSIONS]
            + [float(measures[m.key]) for m in MEASURES]
            + [float(full[k]) for k in ("gross", "employer_cost", "ctc", "deductions", "net")]
        )
    _sheet(wb, "Employee cost", headers, out)


def _pay_equity(db, entity_id, ctx, wb) -> None:
    from app.services.pay_equity import pay_equity

    result = pay_equity(
        db, entity_id, period=ctx["date_to"], group_by=ctx["group_by"],
        filters=ctx["filters"],
    )
    coverage = result["coverage"]
    _sheet(wb, "Coverage", ["Category", "Employees"],
           [[row["label"], row["count"]] for row in coverage["by_gender"]]
           + [["Total", coverage["total"]],
              ["Gender recorded", coverage["recorded"]],
              ["Coverage %", coverage["recorded_pct"]],
              ["Period", result["period_label"]],
              ["Basis", result["basis"]],
              ["Minimum group size", result["min_group_size"]]])

    headline = result["headline"] or {}
    _sheet(wb, "Headline gap", ["Measure", "Value"], [
        ["Median gap %", headline.get("median_gap_pct")],
        ["Mean gap %", headline.get("mean_gap_pct")],
        ["Variable pay median gap %", headline.get("variable_gap_pct")],
        ["Women — median", (headline.get("women") or {}).get("median")],
        ["Women — count", (headline.get("women") or {}).get("count")],
        ["Men — median", (headline.get("men") or {}).get("median")],
        ["Men — count", (headline.get("men") or {}).get("count")],
        ["Direction", result["direction"]],
        ["Comparable", "yes" if headline.get("comparable") else "no"],
        ["Why not", headline.get("reason")],
    ])

    _sheet(wb, "Pay quartiles",
           ["Band", "Employees", "Women", "Men", "Other", "Not recorded",
            "Women % of known", "Pay from", "Pay to"],
           [[q["band"], q["count"], q["counts"]["female"], q["counts"]["male"],
             q["counts"]["other"], q["counts"]["not_recorded"], q["female_pct"],
             q["pay_from"], q["pay_to"]] for q in result["quartiles"]])

    _sheet(wb, "Like for like",
           [result["group_by_label"], "Women", "Men", "Women median", "Men median",
            "Median gap %", "Mean gap %", "Comparable", "Why not"],
           [[g["group"], g["women"]["count"], g["men"]["count"],
             g["women"]["median"], g["men"]["median"], g["median_gap_pct"],
             g["mean_gap_pct"], "yes" if g["comparable"] else "no", g["reason"]]
            for g in result["like_for_like"]])

    _sheet(wb, "How to read this", ["Caveat"], [[c] for c in result["caveats"]])


REPORTS: dict[str, tuple[str, str, Callable]] = {
    "management-summary": ("Management summary",
                           "Totals, month by month, and the full component list.",
                           _management_summary),
    "department-cost": ("Department cost",
                        "Cost by the chosen dimension, and a month-by-month matrix.",
                        _department_cost),
    "headcount": ("Headcount",
                  "Opening, joiners, exits, closing, and cost per head.",
                  _headcount),
    "compensation": ("Compensation",
                     "Distribution, percentiles, salary bands and pay mix.",
                     _compensation),
    "statutory-cost": ("Statutory cost",
                       "Employer and employee statutory heads, readiness and exposure.",
                       _statutory),
    "budget-variance": ("Budget variance",
                        "Actual against the approved budget, by month and scope.",
                        _budget_variance),
    "component-breakdown": ("Salary component breakdown",
                            "Every component by month and by dimension.",
                            _component_breakdown),
    "reconciliation": ("Payroll reconciliation",
                       "Open exceptions with severity, state and financial impact.",
                       _reconciliation),
    "bank-jv-reconciliation": ("Bank & journal voucher reconciliation",
                               "Net pay against the bank file, and the voucher against "
                               "payroll cost, with every exception behind both.",
                               _bank_jv_reconciliation),
    "employee-cost": ("Employee payroll cost",
                      "One row per employee per month, fully costed.",
                      _employee_cost),
    "pay-equity": ("Gender pay gap",
                   "Unadjusted and like-for-like, with pay quartiles. Aggregate only; "
                   "small groups withheld.",
                   _pay_equity),
}

# Reports that carry data about a protected characteristic. These are not served
# by role alone — the entity must also have authorised the analysis.
RESTRICTED_REPORTS = {"pay-equity"}


def catalogue() -> list[dict]:
    return [{"key": key, "title": title, "description": description}
            for key, (title, description, _) in REPORTS.items()]


def build(
    db: Session,
    entity: Any,
    *,
    kind: str,
    user: Any,
    identity: Any,
    group_by: str = "department",
    date_from: date | None = None,
    date_to: date | None = None,
    filters: dict[str, list[str]] | None = None,
) -> tuple[bytes, str]:
    """Generate one report as an .xlsx file, and the filename to serve it under."""
    if kind not in REPORTS:
        raise ValueError(f"Unknown report: {kind}. One of: {', '.join(REPORTS)}")

    openpyxl = _openpyxl()
    title, description, builder = REPORTS[kind]
    wb = openpyxl.Workbook()

    freshness = _freshness(db, entity.id)
    _provenance_sheet(wb, {
        "Report": title,
        "What it covers": description,
        "Entity": getattr(entity, "name", ""),
        "Entity code": getattr(entity, "code", ""),
        "Period from": date_from.strftime("%b %Y") if date_from else "earliest stored",
        "Period to": date_to.strftime("%b %Y") if date_to else "latest stored",
        "Breakdown dimension": group_by,
        "Filters applied": ", ".join(
            f"{k}={'/'.join(v)}" for k, v in (filters or {}).items() if v
        ) or "none",
        "Employee identity": "masked" if identity.masked else "visible",
        "Latest register": freshness["latest_period"] or "none uploaded",
        "Registers stored": freshness["register_count"],
        "Data last uploaded": freshness["last_uploaded_at"] or "—",
        "Generated by": getattr(user, "email", "unknown"),
        "Generated at": datetime.now(UTC).isoformat(timespec="seconds"),
    })

    ctx = {
        "group_by": group_by,
        "date_from": date_from,
        "date_to": date_to,
        "filters": filters or {},
        "identity": identity,
    }
    builder(db, entity.id, ctx, wb)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    stamp = date.today().isoformat()
    code = getattr(entity, "code", None) or "entity"
    return buffer.getvalue(), f"{code}-{kind}-{stamp}.xlsx"
