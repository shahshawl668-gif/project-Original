"""
One run, counted for drawing.

The results page draws a run several ways — by severity, by area of payroll, by
department, by risk, and as a grid of who failed what. Every one of those is a
count, and a picture that disagrees with the table under it is worse than no
picture, so the counts are made here, in the database, over the whole run:
never from the one page of findings the browser happens to hold.

Counts are of findings as the run recorded them. Review state (waived,
resolved) is not applied — the totals match the run's own "findings" figure,
and the page says so.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models import FindingRecord, ValidationRun, ValidationRunEmployee

SEVERITIES = ("CRITICAL", "WARNING", "INFO")

# Area of payroll a check belongs to, in the order a payroll team works them.
AREAS: tuple[tuple[str, str], ...] = (
    ("pf", "Provident fund"),
    ("esic", "ESIC"),
    ("pt_lwf", "PT and LWF"),
    ("tds", "Income tax"),
    ("wages", "Wages and structure"),
    ("attendance", "Attendance and LOP"),
    ("changes", "Arrears and changes"),
    ("totals", "Totals"),
    ("data", "Data and master"),
    ("other", "Other"),
)
_STAT = {"STAT-001": "pf", "STAT-002": "pf", "STAT-003": "pf", "STAT-004": "pf",
         "STAT-005": "esic", "STAT-006": "esic", "STAT-007": "esic",
         "STAT-008": "pt_lwf", "STAT-009": "pt_lwf", "STAT-010": "tds", "STAT-011": "tds"}
_PREFIX = {
    "PF": "pf", "ESI": "esic", "PT": "pt_lwf", "LWF": "pt_lwf", "TDS": "tds",
    "MW": "wages", "LC": "wages", "STRUCT": "wages", "BON": "wages", "GRAT": "wages",
    "ATT": "attendance", "LOP": "attendance",
    "ARR": "changes", "INC": "changes", "MOM": "changes", "ADV": "changes", "OTI": "changes",
    "AGG": "totals",
    "DATA": "data", "MST": "data", "ID": "data", "COMP": "data", "HC": "data",
}

MATRIX_ROWS = 40
GROUP_ROWS = 12
RISK_BUCKET = 10


def area_of(rule_id: str) -> str:
    """The area a rule belongs to; anything unrecognised is "other", never dropped."""
    if rule_id in _STAT:
        return _STAT[rule_id]
    return _PREFIX.get(rule_id.split("-", 1)[0].upper(), "other")


def _blank() -> dict[str, int]:
    return dict.fromkeys(SEVERITIES, 0)


def _groups(db: Session, run: ValidationRun, column) -> dict[str, Any]:
    """Employees and employees with a finding, by one employee attribute."""
    rows = (
        db.query(column, func.count(), func.sum(case((ValidationRunEmployee.failed_checks > 0, 1), else_=0)),
                 func.sum(ValidationRunEmployee.critical_count))
        .filter(ValidationRunEmployee.run_id == run.id)
        .group_by(column)
        .all()
    )
    named = sorted(
        ({"name": name, "employees": int(n), "with_findings": int(hit or 0), "critical": int(crit or 0)}
         for name, n, hit, crit in rows if name),
        key=lambda g: (-g["with_findings"], -g["employees"], g["name"]),
    )
    unnamed = [(n, hit, crit) for name, n, hit, crit in rows if not name]
    return {
        "items": named[:GROUP_ROWS],
        # What the chart leaves out is stated, so its bars never pass for the whole.
        "not_shown": len(named) - len(named[:GROUP_ROWS]),
        "unassigned": {"employees": int(sum(n for n, _, _ in unnamed)),
                       "with_findings": int(sum(hit or 0 for _, hit, _ in unnamed))},
    }


def picture(db: Session, run: ValidationRun) -> dict[str, Any]:
    by_rule = (
        db.query(FindingRecord.rule_id, FindingRecord.severity, func.count(),
                 func.count(func.distinct(FindingRecord.employee_id)))
        .filter(FindingRecord.run_id == run.id, FindingRecord.status == "FAIL")
        .group_by(FindingRecord.rule_id, FindingRecord.severity)
        .all()
    )
    severity = _blank()
    areas: dict[str, dict[str, Any]] = {key: {"area": key, "label": label, "findings": 0, **_blank()}
                                        for key, label in AREAS}
    for rule_id, sev, n, _people in by_rule:
        sev = sev if sev in severity else "INFO"
        severity[sev] += n
        slot = areas[area_of(rule_id)]
        slot[sev] += n
        slot["findings"] += n

    # Distinct employees per area cannot be summed from per-rule counts (one
    # person can fail two PF checks), so they are counted per employee.
    per_employee = (
        db.query(FindingRecord.employee_id, FindingRecord.rule_id, FindingRecord.severity, func.count())
        .filter(FindingRecord.run_id == run.id, FindingRecord.status == "FAIL")
        .group_by(FindingRecord.employee_id, FindingRecord.rule_id, FindingRecord.severity)
        .all()
    )
    people: dict[str, set[str]] = {key: set() for key, _ in AREAS}
    cells: dict[str, dict[str, dict[str, int]]] = {}
    for employee_id, rule_id, sev, n in per_employee:
        area = area_of(rule_id)
        people[area].add(employee_id)
        cell = cells.setdefault(employee_id, {}).setdefault(area, _blank())
        cell[sev if sev in cell else "INFO"] += n
    for key in areas:
        areas[key]["employees"] = len(people[key])

    top = (
        db.query(ValidationRunEmployee)
        .filter(ValidationRunEmployee.run_id == run.id, ValidationRunEmployee.failed_checks > 0)
        .order_by(ValidationRunEmployee.risk_score.desc(), ValidationRunEmployee.employee_id.asc())
        .limit(MATRIX_ROWS)
        .all()
    )
    with_findings = (
        db.query(func.count()).select_from(ValidationRunEmployee)
        .filter(ValidationRunEmployee.run_id == run.id, ValidationRunEmployee.failed_checks > 0)
        .scalar() or 0
    )
    used = [key for key, _ in AREAS if areas[key]["findings"]]

    bucket = func.floor(ValidationRunEmployee.risk_score / RISK_BUCKET)
    risk = {
        int(b): int(n) for b, n in
        db.query(bucket, func.count()).filter(ValidationRunEmployee.run_id == run.id).group_by(bucket).all()
    }
    top_bucket = max(risk, default=0)

    return {
        "run_id": str(run.id),
        "employees": run.employee_count,
        "employees_with_findings": int(with_findings),
        "findings": sum(severity.values()),
        "severity": severity,
        "areas": [areas[key] for key in used],
        "departments": _groups(db, run, ValidationRunEmployee.department),
        "locations": _groups(db, run, ValidationRunEmployee.work_state),
        "risk": {
            "bucket": RISK_BUCKET,
            "buckets": [{"from": b * RISK_BUCKET, "to": b * RISK_BUCKET + RISK_BUCKET - 1, "employees": risk.get(b, 0)}
                        for b in range(top_bucket + 1)],
        },
        "matrix": {
            "areas": [{"area": key, "label": areas[key]["label"]} for key in used],
            "rows": [
                {"employee_id": e.employee_id, "employee_name": e.employee_name, "risk_level": e.risk_level,
                 "risk_score": e.risk_score, "cells": cells.get(e.employee_id, {})}
                for e in top
            ],
            "shown": len(top),
            "employees_with_findings": int(with_findings),
        },
    }
