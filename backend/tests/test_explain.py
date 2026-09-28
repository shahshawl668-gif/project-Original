"""
"Why this result?" — built from what the run recorded, pointing at the file.

E002's PF is planted ₹100 short (independently: 12% of min(Basic + Special,
₹15,000)). The explanation must name the file row (E002 is the second data
row, so row 3), the source column, the calculation basis, and a calculated
₹100 impact; a data finding must say its impact was not calculated rather
than show ₹0.
"""
from __future__ import annotations

from decimal import Decimal

from tests.test_coverage import BASE_ROWS, _register, _run
from tests.test_run_history import _company, _data, _empty_queue  # noqa: F401


def _finding(client, headers, run_id, rule, employee):
    page = _data(client.get(
        f"/api/validation/runs/{run_id}/findings?rule_id={rule}&employee_id={employee}", headers=headers))
    assert page["items"], (rule, employee)
    return page["items"][0]


def test_a_statutory_finding_explains_itself_from_the_run(client):
    headers = _company(client, "why")
    run_id = _run(client, headers, _register(BASE_ROWS))
    finding = _finding(client, headers, run_id, "STAT-001", "E002")
    why = _data(client.get(f"/api/validation/runs/{run_id}/findings/{finding['id']}/explain", headers=headers))

    assert why["context"]["run_id"] == run_id and why["context"]["period_month"] == "2026-06-01"
    assert why["source"]["row"] == 3
    assert why["source"]["field"] == "pf_employee"
    assert why["source"]["filename"] == "r.csv" and len(why["source"]["file_sha256"]) == 64
    assert why["values"]["impact_calculated"] is True
    assert why["values"]["financial_impact"] == 100.0
    steps = " ".join(why["calculation"]["steps"])
    assert "PF wage" in steps and "Employee PF" in steps
    assert why["calculation"]["tolerance"] is not None
    assert why["rule"]["policy"]["kind"] == "statutory_configuration"
    assert "not a certification" in why["rule"]["policy"]["note"]
    assert why["inputs"]["pf_employee"] is not None


def test_a_data_finding_says_its_impact_was_not_calculated(client):
    headers = _company(client, "why2")
    rows = [r.replace("100200300400", "") for r in BASE_ROWS]  # no UAN: ID-003
    run_id = _run(client, headers, _register(rows))
    finding = _finding(client, headers, run_id, "ID-003", "E001")
    assert finding["impact_calculated"] is False and finding["financial_impact"] is None
    why = _data(client.get(f"/api/validation/runs/{run_id}/findings/{finding['id']}/explain", headers=headers))
    assert why["values"]["impact_label"] == "Impact not calculated"


def test_the_review_history_travels_with_the_explanation(client):
    headers = _company(client, "why3")
    run_id = _run(client, headers, _register(BASE_ROWS))
    finding = _finding(client, headers, run_id, "STAT-001", "E002")
    r = client.post(f"/api/findings/{finding['fingerprint']}/decision", headers=headers,
                    json={"state": "waived", "reason": "Recovered in the next payroll"})
    assert r.status_code == 200, r.text
    why = _data(client.get(f"/api/validation/runs/{run_id}/findings/{finding['id']}/explain", headers=headers))
    assert why["review"]["state"] == "waived"
    assert why["review"]["waiver_reason"] == "Recovered in the next payroll"
    assert why["review"]["waived_until"] is not None  # a waiver always ends
    assert why["review"]["history"][-1]["to"] == "waived"


def test_another_company_cannot_ask_why(client):
    headers = _company(client, "why4")
    run_id = _run(client, headers, _register(BASE_ROWS))
    finding = _finding(client, headers, run_id, "STAT-001", "E002")
    stranger = _company(client, "why5")
    r = client.get(f"/api/validation/runs/{run_id}/findings/{finding['id']}/explain", headers=stranger)
    assert r.status_code == 404


def test_an_employee_impact_counts_overlapping_findings_once(client):
    """Overlapping checks can report the same rupees; the employee figures must
    add up to the run's de-duplicated exposure rather than exceed it."""
    headers = _company(client, "overlap")
    run_id = _run(client, headers, _register(BASE_ROWS))
    page = _data(client.get(f"/api/validation/runs/{run_id}/employees?page_size=10", headers=headers))
    total = sum(Decimal(str(e["financial_impact"] or 0)) for e in page["items"])
    run = _data(client.get(f"/api/validation/runs/{run_id}", headers=headers))
    assert total == Decimal(str(run["total_financial_impact"]))
