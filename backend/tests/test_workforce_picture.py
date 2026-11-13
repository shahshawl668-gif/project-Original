"""
The master, attendance and audit pictures: counts for the charts on those pages.

Each is held to the rows it summarises, read back through the list endpoints
the page already shows, and to 404 for another company.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from tests.test_run_history import _company, _data

PACK = Path(__file__).resolve().parents[2] / "testdata" / "payroll-qa-sep2026"


def _file(name: str):
    return {"file": (name, (PACK / name).read_bytes(), "text/csv")}


@pytest.fixture(scope="module")
def loaded(client):
    h = _company(client, "wf-picture")
    r = client.post("/api/workforce/master/commit", files=_file("2_employee_master.csv"),
                    data={"meta": json.dumps({"effective_from": "2022-04-01"})}, headers=h)
    assert r.status_code == 200, r.text
    meta = {"meta": json.dumps({"period_month": "2026-09-01"})}
    r = client.post("/api/workforce/attendance/commit", files=_file("4_attendance_report.csv"), data=meta, headers=h)
    assert r.status_code == 200, r.text
    return h


def test_the_master_picture_counts_every_employee_once(client, loaded):
    records = _data(client.get("/api/workforce/master", headers=loaded))
    pic = _data(client.get("/api/workforce/master/picture", headers=loaded))
    assert pic["employees"] == len(records) > 0
    assert pic["active"] + pic["left"] == pic["employees"]
    for key, column in (("by_state", "work_state"), ("by_department", "department"), ("by_gender", "gender"),
                        ("by_employment_type", "employment_type")):
        group = pic[key]
        # Named, beyond-the-chart and not-recorded together are everyone: nobody dropped, nobody twice.
        assert sum(g["employees"] for g in group["items"]) + group["not_shown_employees"] + group["not_recorded"] \
            == pic["employees"], key
        expected = Counter((r[column] or "").strip() for r in records)
        assert group["not_recorded"] == expected.get("", 0), key
        for g in group["items"]:
            assert g["employees"] == expected[g["name"]], (key, g)
    joined = pic["joined_by_year"]
    assert sum(y["employees"] for y in joined["items"]) + joined["not_recorded"] == pic["employees"]
    for f in pic["fields"]:
        assert f["recorded"] == sum(1 for r in records if r.get(f["field"]) not in (None, "")), f


def test_the_attendance_picture_adds_up_to_its_rows(client, loaded):
    register = _data(client.get("/api/workforce/attendance", headers=loaded))[0]
    detail = _data(client.get(f"/api/workforce/attendance/{register['id']}", headers=loaded))
    rows = detail["rows"]
    pic = _data(client.get(f"/api/workforce/attendance/{register['id']}/picture", headers=loaded))
    assert pic["employees"] == len(rows) > 0
    for column, figure in pic["days"].items():
        stated = [float(r[column]) for r in rows if r.get(column) is not None]
        assert figure["employees_stated"] == len(stated), column
        if stated:
            assert figure["total"] == pytest.approx(sum(stated)), column
        else:
            assert figure["total"] is None, column          # never a zero for a column the file lacked
    bands = pic["lop_bands"]
    assert sum(b["employees"] for b in bands["items"]) + bands["not_recorded"] == pic["employees"]
    none = next(b for b in bands["items"] if b["label"] == "None")
    assert none["employees"] == sum(1 for r in rows if r.get("lop_days") is not None and float(r["lop_days"]) == 0)


def test_the_audit_picture_counts_the_trail(client, loaded):
    events = _data(client.get("/api/audit?limit=1000", headers=loaded))["events"]
    pic = _data(client.get("/api/audit/picture?days=30", headers=loaded))
    assert len(pic["by_day"]) == 30 and pic["by_day"][-1]["date"] == pic["to"]
    assert pic["entries"] == sum(d["entries"] for d in pic["by_day"]) == len(events) == pic["all_time"] > 0
    assert sum(a["entries"] for a in pic["by_action"]["items"]) + pic["by_action"]["not_shown_entries"] == pic["entries"]
    expected = Counter(e["action"] for e in events)
    for a in pic["by_action"]["items"]:
        assert a["entries"] == expected[a["action"]], a


def test_pictures_are_closed_to_another_company(client, loaded):
    register = _data(client.get("/api/workforce/attendance", headers=loaded))[0]
    stranger = _company(client, "wf-picture-other")
    assert client.get(f"/api/workforce/attendance/{register['id']}/picture", headers=stranger).status_code == 404
    assert _data(client.get("/api/workforce/master/picture", headers=stranger))["employees"] == 0
    # Each company's picture counts its own trail and nothing else.
    for headers in (stranger, loaded):
        own = _data(client.get("/api/audit?limit=1000", headers=headers))["events"]
        assert _data(client.get("/api/audit/picture", headers=headers))["all_time"] == len(own)
