"""
The run picture: counts for the charts on the results page.

A chart that disagrees with the table under it is worse than no chart, so the
picture is held to the run's own totals and to the findings list, and another
company cannot read it.
"""
from __future__ import annotations

from app.services.run_picture import AREAS, area_of
from tests.test_go_live_kit import _run
from tests.test_run_history import _company, _data


def test_every_rule_lands_in_one_known_area():
    known = {key for key, _ in AREAS}
    for rule in ("STAT-001", "PF-012", "STAT-006", "ESI-009", "STAT-008", "STAT-009", "TDS-001", "MW-001", "LC-001",
                 "ATT-001", "LOP-003", "ARR-005", "INC-002", "MOM-006", "AGG-001", "DATA-014", "MST-007", "HC-001"):
        assert area_of(rule) in known - {"other"}, rule
    assert area_of("ZZZ-999") == "other"        # never dropped


def test_the_picture_adds_up_to_the_run(client):
    company = _company(client, "picture")
    run_id = _run(client, company)
    run = _data(client.get(f"/api/validation/runs/{run_id}", headers=company))
    pic = _data(client.get(f"/api/validation/runs/{run_id}/picture", headers=company))

    assert pic["findings"] == run["total_findings"] > 0
    assert pic["severity"]["CRITICAL"] == run["critical_count"]
    assert pic["severity"]["WARNING"] == run["warning_count"]
    assert sum(pic["severity"].values()) == pic["findings"]
    # Areas partition the findings: nothing counted twice, nothing left out.
    assert sum(a["findings"] for a in pic["areas"]) == pic["findings"]
    for a in pic["areas"]:
        assert a["CRITICAL"] + a["WARNING"] + a["INFO"] == a["findings"] > 0
        assert 0 < a["employees"] <= pic["employees"]

    # The grid's cells are the same findings the list returns for that employee.
    assert pic["matrix"]["shown"] == len(pic["matrix"]["rows"]) <= pic["matrix"]["employees_with_findings"]
    for row in pic["matrix"]["rows"]:
        listed = _data(client.get(f"/api/validation/runs/{run_id}/findings?employee_id={row['employee_id']}"
                                  "&page_size=500", headers=company))["items"]
        assert sum(sum(c.values()) for c in row["cells"].values()) == len(listed)
        for f in listed:
            assert row["cells"][area_of(f["rule_id"])][f["severity"]] >= 1

    assert sum(b["employees"] for b in pic["risk"]["buckets"]) == pic["employees"]
    for group in (pic["departments"], pic["locations"]):
        assert sum(g["employees"] for g in group["items"]) + group["unassigned"]["employees"] <= pic["employees"]
        assert group["not_shown"] >= 0


def test_the_picture_is_404_for_another_company(client):
    company = _company(client, "picture-own")
    run_id = _run(client, company)
    stranger = _company(client, "picture-other")
    assert client.get(f"/api/validation/runs/{run_id}/picture", headers=stranger).status_code == 404
