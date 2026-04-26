"""
Risk Scoring Engine
===================
Computes a 0–100 risk score and LOW / MEDIUM / HIGH level for each employee
based on the validation findings produced by rule_engine_v2.

Scoring weights (per finding, capped at 100):
  CRITICAL FAIL  → 25 points
  WARNING  FAIL  → 10 points
  INFO     FAIL  →  2 points
  PASS           →  0 points

Special boosts:
  financial_impact > ₹5,000  → +5 extra points per finding
  DATA-002 (duplicate)       → always forces HIGH regardless of score
"""
from __future__ import annotations

from typing import Any

WEIGHTS: dict[tuple[str, str], int] = {
    ("CRITICAL", "FAIL"): 25,
    ("WARNING",  "FAIL"): 10,
    ("INFO",     "FAIL"):  2,
}
IMPACT_BOOST_THRESHOLD = 5000.0
IMPACT_BOOST = 5


def compute_risk(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Given a list of finding dicts (from ValidationFinding.to_dict()),
    return:
        {
            "risk_score":  int   0–100,
            "risk_level":  str   LOW | MEDIUM | HIGH,
            "score_breakdown": {...}
        }
    """
    score = 0
    breakdown = {"CRITICAL": 0, "WARNING": 0, "INFO": 0, "impact_boosts": 0}
    force_high = False

    for f in findings:
        sev = f.get("severity", "")
        status = f.get("status", "")
        key = (sev, status)
        pts = WEIGHTS.get(key, 0)

        if pts > 0:
            breakdown[sev] = breakdown.get(sev, 0) + pts
            score += pts

        # Financial impact boost
        impact = float(f.get("financial_impact", 0) or 0)
        if impact > IMPACT_BOOST_THRESHOLD and status == "FAIL":
            score += IMPACT_BOOST
            breakdown["impact_boosts"] += IMPACT_BOOST

        # Duplicates always force HIGH
        if f.get("rule_id") == "DATA-002":
            force_high = True

    score = min(score, 100)

    if force_high or score >= 60:
        level = "HIGH"
    elif score >= 25:
        level = "MEDIUM"
    else:
        level = "LOW"

    return {
        "risk_score": score,
        "risk_level": level,
        "score_breakdown": breakdown,
    }


def compute_batch_risk(
    employees_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Takes the full validate_employees result list (each item has 'findings' key)
    and returns a list of risk objects, one per employee.
    """
    out = []
    for emp in employees_results:
        findings = emp.get("findings", [])
        risk = compute_risk(findings)
        out.append({
            "employee_id":   emp.get("employee_id", ""),
            "employee_name": emp.get("employee_name", ""),
            **risk,
        })
    return out


def risk_distribution(risk_results: list[dict[str, Any]]) -> dict[str, int]:
    """Return counts per risk level."""
    dist: dict[str, int] = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    for r in risk_results:
        lvl = r.get("risk_level", "LOW")
        dist[lvl] = dist.get(lvl, 0) + 1
    return dist
