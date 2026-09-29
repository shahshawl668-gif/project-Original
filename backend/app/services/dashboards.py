"""
Configurable dashboards: datasets, metrics, breakdowns, and one query engine.

A dashboard tile is a question, asked afresh each time it is shown:
*dataset → metric (or custom KPI) → breakdown → chart → filters → period*.
Every dataset answers from the same services the fixed pages use — cost from
``analytics.cost_analysis``, movement from ``workforce_analytics``, budget from
``budgeting``, findings and runs from their tables — so a tile and the page it
drills into cannot disagree.

Three rules every answer keeps:

* **Absent is not zero.** A value that could not be computed is ``None`` and
  the chart shows a gap; a range with no register says "no data".
* **Every figure says what it is.** Each metric carries its unit and its
  definition, and payroll-based answers carry their data basis (months present
  and missing, validation and sign-off state).
* **Custom KPIs are formulas, not code** — evaluated by the whitelisted formula
  evaluator over the dataset's own metric keys.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.services.formula_eval import ALLOWED_FUNCS, FormulaError, evaluate_formula


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str  # inr | number | pct
    definition: str
    #: How a total is formed: "sum", "last", "first", or "ratio" (recomputed from the total row).
    total: str = "sum"


@dataclass(frozen=True)
class Dataset:
    key: str
    label: str
    source: str
    metrics: tuple[Metric, ...]
    breakdowns: tuple[tuple[str, str], ...]
    filters: tuple[str, ...] = ()
    periodic: bool = True
    run: Callable[..., dict[str, Any]] | None = field(default=None, compare=False)

    def metric(self, key: str) -> Metric | None:
        return next((m for m in self.metrics if m.key == key), None)


class QueryError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------
def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def resolve_period(db: Session, entity_id: Any, period: dict[str, Any] | None) -> tuple[date | None, date | None, str]:
    """{"preset": "last_3|last_6|last_12|all|custom", "from": "YYYY-MM", "to": "YYYY-MM"} → dates."""
    from sqlalchemy import func

    from app.models import SalaryRegister

    period = period or {"preset": "last_6"}
    preset = period.get("preset") or "last_6"
    if preset == "custom":
        try:
            start = date.fromisoformat(f"{period['from']}-01") if period.get("from") else None
            end = date.fromisoformat(f"{period['to']}-01") if period.get("to") else None
        except ValueError as exc:
            raise QueryError("Period months are YYYY-MM") from exc
        if start and end and start > end:
            raise QueryError("The period starts after it ends")
        label = f"{start:%b %Y} – {end:%b %Y}" if start and end else "custom"
        return start, end, label
    if preset == "all":
        return None, None, "All months"
    try:
        n = int(preset.split("_")[1])
    except (IndexError, ValueError) as exc:
        raise QueryError("Unknown period preset") from exc
    latest = db.query(func.max(SalaryRegister.period_month)).filter(SalaryRegister.entity_id == entity_id).scalar()
    anchor = latest or date.today().replace(day=1)
    start = _add_months(anchor, -(n - 1))
    return start, anchor, f"Last {n} months to {anchor:%b %Y}"


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------
def _dims() -> tuple[tuple[str, str], ...]:
    from app.services.dimensions import DIMENSION_KEYS, DIMENSION_LABELS

    return tuple((k, DIMENSION_LABELS[k]) for k in DIMENSION_KEYS)


def _payroll_metrics() -> tuple[Metric, ...]:
    from app.services.analytics import DEFINITIONS
    from app.services.cost_model import MEASURES

    base = [
        Metric("ctc", "Total CTC", "inr", DEFINITIONS["ctc"]),
        Metric("gross", "Gross pay", "inr", "Earnings on the register, arrears included."),
        Metric("employer_cost", "Employer contributions", "inr", "EPF, EDLI and admin, ESI, gratuity provision and LWF paid by the employer."),
        Metric("deductions", "Employee deductions", "inr", "EPF, ESI, PT, LWF and TDS deducted from pay."),
        Metric("net", "Net pay", "inr", "Gross less employee deductions."),
        Metric("headcount", "People paid", "number", DEFINITIONS["headcount"], total="distinct"),
        Metric("average_headcount", "Average monthly headcount", "number", DEFINITIONS["average_headcount"], total="ratio"),
        Metric("person_months", "Person-months", "number", DEFINITIONS["person_months"]),
        Metric("cost_per_head", "Cost per head / month", "inr", DEFINITIONS["cost_per_head"], total="ratio"),
    ]
    extra = [Metric(m.key, m.label, "inr", f"{m.label} ({m.layer}), as costed from the register.") for m in MEASURES]
    return tuple(base + extra)


def _run_payroll(db, entity, *, breakdown, granularity, date_from, date_to, filters):
    from app.services.analytics import cost_analysis

    group_by = breakdown if breakdown != "period" else "department"
    a = cost_analysis(db, entity.id, group_by=group_by, granularity=granularity, measure="ctc",
                      date_from=date_from, date_to=date_to, filters=filters)
    if a["data_status"] == "no_register":
        return {"status": "no_data", "rows": [], "total": None, "basis": a["basis"],
                "note": "No register in this range — no figure, not a figure of zero."}
    months = a["totals"]["months_with_register"] or 0

    def metrics(measures, headcount, person_months, cph, avg):
        return {**measures, "headcount": headcount, "person_months": person_months,
                "cost_per_head": cph, "average_headcount": avg}

    rows = []
    if breakdown == "period":
        for p in a["period_totals"]:
            rows.append({"key": p["period"], "label": p["label"],
                         "metrics": metrics(p["measures"], p["headcount"], p["person_months"],
                                            p["cost_per_head_monthly"], p["average_headcount"]),
                         "drill": f"/cost?view=overview&granularity={granularity}"})
    else:
        for g in a["matrix"]:
            rows.append({"key": g["group"], "label": g["group"],
                         "metrics": metrics(g["measures"], g["headcount"], g["person_months"],
                                            g["cost_per_head_monthly"],
                                            round(g["person_months"] / months, 1) if months else None),
                         "drill": f"/cost?view=overview&group_by={breakdown}&f_{breakdown}={quote(g['group'])}"})
    t = a["totals"]
    total = metrics({k: v for k, v in t.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
                    t["headcount"], t["person_months"], t["cost_per_head"], t["average_headcount"])
    return {"status": "ok", "rows": rows, "total": total, "basis": a["basis"]}


def _run_headcount(db, entity, *, breakdown, granularity, date_from, date_to, filters):
    from app.services.workforce_analytics import headcount_movement

    m = headcount_movement(db, entity.id, date_from=date_from, date_to=date_to, filters=filters)
    periods = m.get("periods") or []
    if not periods:
        return {"status": "no_data", "rows": [], "total": None,
                "note": "No register in this range — no movement to show."}
    rows = [{"key": p["period"], "label": p["label"],
             "metrics": {k: p.get(k) for k in ("opening", "joiners", "exits", "closing", "net_change", "average_headcount")},
             "drill": "/cost?view=headcount"} for p in periods]
    total = {
        "opening": periods[0].get("opening"), "closing": periods[-1].get("closing"),
        "joiners": sum(p["joiners"] for p in periods), "exits": sum(p["exits"] for p in periods),
        "net_change": (periods[-1]["closing"] - periods[0]["opening"]) if periods[0].get("opening") is not None else None,
        "average_headcount": round(sum(p["average_headcount"] for p in periods) / len(periods), 1),
    }
    return {"status": "ok", "rows": rows, "total": total}


def _run_findings(db, entity, *, breakdown, granularity, date_from, date_to, filters):
    from app.models import FindingState, User
    from app.services.explain import impact_known

    q = db.query(FindingState).filter(FindingState.entity_id == entity.id)
    states = (filters or {}).get("state") or ["open", "acknowledged"]
    q = q.filter(FindingState.state.in_(states))
    if (filters or {}).get("severity"):
        q = q.filter(FindingState.severity.in_(filters["severity"]))
    if date_from:
        q = q.filter(FindingState.last_seen_period >= date_from)
    if date_to:
        q = q.filter(FindingState.last_seen_period <= date_to)
    today = date.today()
    owners = {}
    groups: dict[str, dict[str, Any]] = {}
    for s in q.all():
        if breakdown == "rule":
            key, label, drill = s.rule_id, f"{s.rule_id} · {s.rule_name}", f"/payroll/issues?rule_id={quote(s.rule_id)}&state="
        elif breakdown == "severity":
            key, label, drill = s.severity, s.severity.title(), f"/payroll/issues?severity={s.severity}"
        elif breakdown == "state":
            key, label, drill = s.state, s.state.title(), f"/payroll/issues?state={s.state}"
        elif breakdown == "owner":
            key = str(s.owner_user_id) if s.owner_user_id else "none"
            if s.owner_user_id and s.owner_user_id not in owners:
                u = db.get(User, s.owner_user_id)
                owners[s.owner_user_id] = u.email if u else "—"
            label = owners.get(s.owner_user_id, "Unassigned")
            drill = f"/payroll/issues?owner={key}"
        else:  # period: when it was last seen
            key = s.last_seen_period.isoformat()
            label, drill = s.last_seen_period.strftime("%b %Y"), "/payroll/issues"
        g = groups.setdefault(key, {"label": label, "drill": drill, "m": dict.fromkeys(
            ("issues", "critical", "exposure", "not_priced", "overdue", "recurring"), 0)})
        m = g["m"]
        m["issues"] += 1
        m["critical"] += s.severity == "CRITICAL"
        if impact_known(s.rule_id, s.last_financial_impact):
            m["exposure"] = round(m["exposure"] + float(s.last_financial_impact or 0), 2)
        else:
            m["not_priced"] += 1
        m["overdue"] += bool(s.due_date and s.due_date < today and s.state in ("open", "acknowledged"))
        m["recurring"] += s.occurrence_count >= 3
    ordered = sorted(groups.items(), key=lambda kv: kv[0] if breakdown == "period" else -kv[1]["m"]["issues"])
    rows = [{"key": k, "label": g["label"], "metrics": g["m"], "drill": g["drill"]} for k, g in ordered]
    total = {k: (round(sum(r["metrics"][k] for r in rows), 2) if k == "exposure" else sum(r["metrics"][k] for r in rows))
             for k in ("issues", "critical", "exposure", "not_priced", "overdue", "recurring")}
    return {"status": "ok" if rows else "empty", "rows": rows, "total": total,
            "note": None if rows else "No issues match — which, on its own, does not mean the month was checked."}


def _run_validation(db, entity, *, breakdown, granularity, date_from, date_to, filters):
    from app.models import PeriodSignOff, ValidationRun

    q = db.query(ValidationRun).filter(ValidationRun.entity_id == entity.id, ValidationRun.status == "current")
    if date_from:
        q = q.filter(ValidationRun.period_month >= date_from)
    if date_to:
        q = q.filter(ValidationRun.period_month <= date_to)
    runs = q.order_by(ValidationRun.period_month).all()
    if not runs:
        return {"status": "no_data", "rows": [], "total": None,
                "note": "No month in this range has been validated."}
    signed = {s.period_month for s in db.query(PeriodSignOff).filter(
        PeriodSignOff.entity_id == entity.id, PeriodSignOff.state == "signed")}
    rows = []
    agg = {"assessed": 0, "applicable": 0}
    for r in runs:
        cov = (r.summary or {}).get("coverage") or {}
        totals = cov.get("totals") or {}
        assessed = (totals.get("passed") or 0) + (totals.get("failed") or 0)
        applicable = assessed + (totals.get("cannot_validate") or 0)
        agg["assessed"] += assessed
        agg["applicable"] += applicable
        rows.append({"key": r.period_month.isoformat(), "label": r.period_month.strftime("%b %Y"),
                     "metrics": {
                         "employees": r.employee_count, "failed_checks": r.total_findings,
                         "critical": r.critical_count,
                         "coverage_pct": cov.get("coverage_pct"),
                         "checks_not_performed": cov.get("material_cannot_validate"),
                         "exposure": float(r.open_financial_impact or 0),
                         "signed_off": 1 if r.period_month in signed else 0,
                     },
                     "drill": f"/payroll/results?run={r.id}"})
    total = {
        "employees": rows[-1]["metrics"]["employees"],
        "failed_checks": sum(r["metrics"]["failed_checks"] for r in rows),
        "critical": sum(r["metrics"]["critical"] for r in rows),
        "coverage_pct": round(agg["assessed"] * 100 / agg["applicable"], 1) if agg["applicable"] else None,
        "checks_not_performed": sum(r["metrics"]["checks_not_performed"] or 0 for r in rows),
        "exposure": round(sum(r["metrics"]["exposure"] for r in rows), 2),
        "signed_off": sum(r["metrics"]["signed_off"] for r in rows),
    }
    return {"status": "ok", "rows": rows, "total": total}


def _run_budget(db, entity, *, breakdown, granularity, date_from, date_to, filters):
    from app.services.budgeting import budget_variance

    v = budget_variance(db, entity.id, date_from=date_from, date_to=date_to, filters=filters)
    if v.get("version") is None:
        return {"status": "no_budget", "rows": [], "total": None, "note": v.get("note")}
    rows = []
    if breakdown == "scope":
        for s in v["scopes"]:
            rows.append({"key": s["scope"], "label": s["scope"],
                         "metrics": {k: s.get(k) for k in ("actual", "budget", "variance", "utilisation_pct")},
                         "drill": "/cost?view=budget"})
    else:
        for p in v["periods"]:
            rows.append({"key": p["period"], "label": p["label"],
                         "metrics": {k: p.get(k) for k in ("actual", "budget", "variance", "utilisation_pct")},
                         "drill": "/cost?view=budget"})
    t = v["totals"]
    return {"status": "ok", "rows": rows,
            "total": {k: t.get(k) for k in ("actual", "budget", "variance", "utilisation_pct")},
            "note": ("Months with a budget and no register are left out of the totals: "
                     + ", ".join(v.get("no_register_periods") or [])) if v.get("no_register_periods") else None}


def _datasets() -> dict[str, Dataset]:
    dims = _dims()
    return {d.key: d for d in (
        Dataset("payroll_cost", "Payroll cost", "Stored salary registers (regular runs), costed through the component configuration",
                _payroll_metrics(), (("period", "Period"), *dims), filters=tuple(k for k, _ in dims), run=_run_payroll),
        Dataset("headcount", "Headcount movement", "Presence on the stored registers, month on month",
                (Metric("closing", "Closing headcount", "number", "People on the month's register.", total="last"),
                 Metric("opening", "Opening headcount", "number", "People on the previous month's register (none for the first month in range).", total="first"),
                 Metric("joiners", "Joiners", "number", "Paid this month, not last month."),
                 Metric("exits", "Exits", "number", "Paid last month, not this month."),
                 Metric("net_change", "Net change", "number", "Closing less opening.", total="ratio"),
                 Metric("average_headcount", "Average headcount", "number", "Average of opening and closing.", total="ratio")),
                (("period", "Period"),), filters=tuple(k for k, _ in dims), run=_run_headcount),
        Dataset("findings", "Issues", "Findings worklist (open and in progress unless filtered)",
                (Metric("issues", "Issues", "number", "Findings in the chosen states."),
                 Metric("critical", "Critical issues", "number", "Issues of CRITICAL severity."),
                 Metric("exposure", "Priced exposure", "inr", "Last calculated financial impact of priced findings. Unpriced findings are counted separately, never as ₹0."),
                 Metric("not_priced", "Issues without a calculated impact", "number", "Findings whose rule does not price its effect."),
                 Metric("overdue", "Overdue", "number", "Open issues past their due date."),
                 Metric("recurring", "Recurring (3+ months)", "number", "Issues seen in three or more months.")),
                (("rule", "Rule"), ("severity", "Severity"), ("state", "State"), ("owner", "Owner"), ("period", "Last seen")),
                filters=("state", "severity"), run=_run_findings),
        Dataset("validation", "Validation quality", "Current validation run of each month",
                (Metric("failed_checks", "Failed checks", "number", "Findings in the month's current run."),
                 Metric("critical", "Critical findings", "number", "CRITICAL findings in the run, open."),
                 Metric("coverage_pct", "Coverage %", "pct", "Share of applicable checks that reached a verdict (passed or failed).", total="ratio"),
                 Metric("checks_not_performed", "Statutory checks not performed", "number", "Material checks that could not run for want of an input."),
                 Metric("exposure", "Open exposure", "inr", "De-duplicated financial impact of open findings in the run."),
                 Metric("employees", "Employees validated", "number", "Employees in the run.", total="last"),
                 Metric("signed_off", "Months signed off", "number", "1 when the month is signed off.")),
                (("period", "Period"),), run=_run_validation),
        Dataset("budget", "Budget vs actual", "The approved budget against stored registers, on the budget's own measure",
                (Metric("actual", "Actual", "inr", "Payroll cost on the budget's measure; none for a month with no register."),
                 Metric("budget", "Budget", "inr", "The approved budget."),
                 Metric("variance", "Variance", "inr", "Actual less budget, only where both exist."),
                 Metric("utilisation_pct", "Utilisation %", "pct", "Actual ÷ budget.", total="ratio")),
                (("period", "Period"), ("scope", "Budget scope")), filters=tuple(k for k, _ in dims), run=_run_budget),
    )}


DATASETS = _datasets()


def catalogue() -> list[dict[str, Any]]:
    return [{
        "key": d.key, "label": d.label, "source": d.source,
        "metrics": [{"key": m.key, "label": m.label, "unit": m.unit, "definition": m.definition} for m in d.metrics],
        "breakdowns": [{"key": k, "label": label} for k, label in d.breakdowns],
        "filters": list(d.filters),
    } for d in DATASETS.values()]


# ---------------------------------------------------------------------------
# Custom KPIs
# ---------------------------------------------------------------------------
def validate_kpi(dataset: str, formula: str) -> None:
    ds = DATASETS.get(dataset)
    if ds is None:
        raise QueryError("Unknown dataset")
    try:
        tree = ast.parse(formula or "", mode="eval")
    except SyntaxError as exc:
        raise QueryError(f"The formula is not valid: {exc.msg}") from exc
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id not in ALLOWED_FUNCS}
    unknown = names - {m.key for m in ds.metrics}
    if unknown:
        raise QueryError(f"Unknown metric(s) for {ds.label}: {', '.join(sorted(unknown))}")
    try:
        evaluate_formula(formula, {m.key: 1.0 for m in ds.metrics})
    except FormulaError as exc:
        raise QueryError(f"The formula is not valid: {exc}") from exc
    except (ZeroDivisionError, OverflowError, TypeError, ValueError):
        pass


def _kpi_value(formula: str, metrics: dict[str, Any]) -> float | None:
    values = {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)}
    try:
        return round(evaluate_formula(formula, values), 4)
    except (FormulaError, ZeroDivisionError, OverflowError, TypeError, ValueError):
        return None  # an input absent or zero where it divides: unknown, not 0


# ---------------------------------------------------------------------------
# The query
# ---------------------------------------------------------------------------
def query(
    db: Session, entity: Any, *, dataset: str, metric: str | None = None, kpi: Any = None,
    breakdown: str = "period", granularity: str = "month", filters: dict[str, list[str]] | None = None,
    period: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ds = DATASETS.get(dataset)
    if ds is None:
        raise QueryError("Unknown dataset")
    if breakdown not in {k for k, _ in ds.breakdowns}:
        raise QueryError(f"{ds.label} cannot be broken down by {breakdown}")
    if granularity not in ("month", "quarter", "year"):
        raise QueryError("Granularity is month, quarter or year")
    clean_filters = {k: [str(x) for x in v if str(x).strip()] for k, v in (filters or {}).items() if v}
    bad = set(clean_filters) - set(ds.filters)
    if bad:
        raise QueryError(f"{ds.label} cannot be filtered by {', '.join(sorted(bad))}")
    if kpi is not None:
        if kpi.dataset != dataset:
            raise QueryError("That KPI belongs to another dataset")
        meta = {"key": f"kpi:{kpi.id}", "label": kpi.name, "unit": kpi.unit,
                "definition": f"Custom KPI: {kpi.formula}" + (f" — {kpi.description}" if kpi.description else ""),
                "custom": True, "formula": kpi.formula}
        value_of = lambda m: _kpi_value(kpi.formula, m)  # noqa: E731
        total_rule = "ratio"
    else:
        m = ds.metric(metric or "")
        if m is None:
            raise QueryError(f"{ds.label} has no metric {metric}")
        meta = {"key": m.key, "label": m.label, "unit": m.unit, "definition": m.definition, "custom": False}
        value_of = lambda row: row.get(m.key)  # noqa: E731
        total_rule = m.total
    date_from, date_to, period_label = resolve_period(db, entity.id, period)
    if date_to and ds.key in ("payroll_cost", "headcount", "budget"):
        import calendar

        date_to_end = date_to.replace(day=calendar.monthrange(date_to.year, date_to.month)[1])
    else:
        date_to_end = date_to
    out = ds.run(db, entity, breakdown=breakdown, granularity=granularity, date_from=date_from,
                 date_to=date_to_end, filters=clean_filters)
    rows = [{"key": r["key"], "label": r["label"], "value": value_of(r["metrics"]), "drill": r.get("drill")}
            for r in out["rows"]]
    total = None
    if out.get("total") is not None:
        if total_rule in ("ratio", "last", "first", "distinct"):
            total = value_of(out["total"])
        else:
            values = [r["value"] for r in rows if r["value"] is not None]
            total = round(sum(values), 2) if values else None
    return {
        "dataset": {"key": ds.key, "label": ds.label, "source": ds.source},
        "metric": meta,
        "breakdown": {"key": breakdown, "label": dict(ds.breakdowns)[breakdown]},
        "granularity": granularity,
        "filters": clean_filters,
        "period": {"from": date_from.isoformat() if date_from else None,
                   "to": date_to.isoformat() if date_to else None, "label": period_label},
        "status": out["status"],
        "rows": rows,
        "total": total,
        "note": out.get("note"),
        "basis": out.get("basis"),
    }


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
def _tile(title, dataset, metric, breakdown="period", chart="bar", **kw):
    return {"title": title, "dataset": dataset, "metric": metric, "breakdown": breakdown, "chart": chart,
            "filters": kw.get("filters", {}), "granularity": kw.get("granularity", "month"), "period": {"inherit": True}}


TEMPLATES: dict[str, dict[str, Any]] = {
    "payroll_cost": {"name": "Payroll cost overview", "description": "What payroll costs, month by month and by department.",
                     "tiles": [_tile("Total CTC", "payroll_cost", "ctc", chart="kpi"),
                               _tile("Cost per head / month", "payroll_cost", "cost_per_head", chart="kpi"),
                               _tile("Total CTC by month", "payroll_cost", "ctc", chart="line"),
                               _tile("Total CTC by department", "payroll_cost", "ctc", "department"),
                               _tile("Employer contributions by month", "payroll_cost", "employer_cost")]},
    "headcount": {"name": "Headcount and movement", "description": "Who joined, who left, and the establishment month by month.",
                  "tiles": [_tile("Closing headcount", "headcount", "closing", chart="kpi"),
                            _tile("Closing headcount by month", "headcount", "closing"),
                            _tile("Joiners by month", "headcount", "joiners", chart="line"),
                            _tile("Exits by month", "headcount", "exits", chart="line")]},
    "statutory": {"name": "Statutory contributions", "description": "Employer and employee statutory amounts as costed from the register.",
                  "tiles": [_tile("EPF — employer", "payroll_cost", "er_pf", chart="kpi"),
                            _tile("ESI — employer", "payroll_cost", "er_esi", chart="kpi"),
                            _tile("EPF — employer by month", "payroll_cost", "er_pf"),
                            _tile("Professional tax by month", "payroll_cost", "pt"),
                            _tile("TDS by month", "payroll_cost", "tds", chart="line")]},
    "validation_quality": {"name": "Validation quality", "description": "What was checked, what failed, and what could not be checked.",
                           "tiles": [_tile("Coverage %", "validation", "coverage_pct", chart="kpi"),
                                     _tile("Coverage % by month", "validation", "coverage_pct", chart="line"),
                                     _tile("Failed checks by month", "validation", "failed_checks"),
                                     _tile("Statutory checks not performed", "validation", "checks_not_performed")]},
    "issues": {"name": "Issue resolution", "description": "Open issues by rule, severity and owner.",
               "tiles": [_tile("Open issues", "findings", "issues", chart="kpi"),
                         _tile("Overdue", "findings", "overdue", chart="kpi"),
                         _tile("Open issues by rule", "findings", "issues", "rule"),
                         _tile("Open issues by severity", "findings", "issues", "severity", chart="pie"),
                         _tile("Open issues by owner", "findings", "issues", "owner", chart="table")]},
    "budget": {"name": "Budget vs actual", "description": "Spend against the approved budget.",
               "tiles": [_tile("Utilisation %", "budget", "utilisation_pct", chart="kpi"),
                         _tile("Actual by month", "budget", "actual"),
                         _tile("Variance by month", "budget", "variance", chart="line"),
                         _tile("Variance by scope", "budget", "variance", "scope", chart="table")]},
    "department_cost": {"name": "Department cost", "description": "Cost, people and cost per head by department.",
                        "tiles": [_tile("Total CTC by department", "payroll_cost", "ctc", "department"),
                                  _tile("Cost per head by department", "payroll_cost", "cost_per_head", "department"),
                                  _tile("People paid by department", "payroll_cost", "headcount", "department", chart="table")]},
    "month_close": {"name": "Month-close readiness", "description": "Validation, coverage, open issues and sign-off, month by month.",
                    "tiles": [_tile("Months signed off", "validation", "signed_off", chart="kpi"),
                              _tile("Open critical issues", "findings", "critical", chart="kpi"),
                              _tile("Signed off by month", "validation", "signed_off", chart="table"),
                              _tile("Coverage % by month", "validation", "coverage_pct", chart="line")]},
}
