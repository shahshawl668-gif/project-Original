"""End-to-end coverage for master and attendance ingestion."""
from __future__ import annotations

import io

import pandas as pd


def _signup(client, email: str, company: str) -> dict:
    r = client.post(
        "/api/auth/signup",
        json={"email": email, "password": "Passw0rd!x", "company_name": company},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def _csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode()


MASTER_ROWS = [
    {"Emp Code": "1001", "Employee Name": "Asha Menon", "DOJ": "15/06/2021",
     "State": "Karnataka", "Designation": "Operator", "Skill": "skilled"},
    {"Emp Code": "1002", "Employee Name": "Ravi Kumar", "DOJ": "01/02/2024",
     "Date of Leaving": "31/03/2025", "State": "Maharashtra", "Skill": "unskilled"},
]


def test_master_preview_reports_how_headers_were_read(client):
    h = _signup(client, "wf1@example-co.com", "Workforce One")
    r = client.post(
        "/api/workforce/master/upload",
        files={"file": ("master.csv", _csv(MASTER_ROWS), "text/csv")},
        data={"meta": "{}"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    preview = r.json()["data"]

    assert preview["row_count"] == 2
    assert preview["header_map"]["DOJ"] == "date_of_joining"
    assert preview["header_map"]["Date of Leaving"] == "date_of_exit"
    assert preview["warnings"] == []


def test_preview_warns_when_joining_dates_are_missing(client):
    """Silence here would disable exit checks and gratuity service years."""
    h = _signup(client, "wf2@example-co.com", "Workforce Two")
    rows = [{"Emp Code": "1001", "Employee Name": "Asha"}]
    r = client.post(
        "/api/workforce/master/upload",
        files={"file": ("master.csv", _csv(rows), "text/csv")},
        data={"meta": "{}"},
        headers=h,
    )
    warnings = " ".join(r.json()["data"]["warnings"])
    assert "joining-date" in warnings
    assert "work-state" in warnings


def test_master_commit_stores_typed_records(client):
    h = _signup(client, "wf3@example-co.com", "Workforce Three")
    r = client.post(
        "/api/workforce/master/commit",
        files={"file": ("master.csv", _csv(MASTER_ROWS), "text/csv")},
        data={"meta": '{"effective_from": "2025-04-01"}'},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["employee_count"] == 2

    records = client.get("/api/workforce/master?as_of=2025-04-30", headers=h).json()["data"]
    by_id = {r["employee_id"]: r for r in records}

    assert by_id["1001"]["date_of_joining"] == "2021-06-15"
    assert by_id["1001"]["work_state"] == "Karnataka"
    assert by_id["1001"]["skill_category"] == "skilled"
    assert by_id["1002"]["date_of_exit"] == "2025-03-31"


def test_master_as_of_returns_the_version_in_force_then(client):
    """Re-running an old month must not see later master changes."""
    h = _signup(client, "wf4@example-co.com", "Workforce Four")

    client.post(
        "/api/workforce/master/commit",
        files={"file": ("m.csv", _csv([{"Emp Code": "1001", "Designation": "Operator"}]), "text/csv")},
        data={"meta": '{"effective_from": "2025-04-01"}'},
        headers=h,
    )
    client.post(
        "/api/workforce/master/commit",
        files={"file": ("m.csv", _csv([{"Emp Code": "1001", "Designation": "Supervisor"}]), "text/csv")},
        data={"meta": '{"effective_from": "2025-07-01"}'},
        headers=h,
    )

    april = client.get("/api/workforce/master?as_of=2025-04-30", headers=h).json()["data"]
    august = client.get("/api/workforce/master?as_of=2025-08-31", headers=h).json()["data"]

    assert april[0]["designation"] == "Operator"
    assert august[0]["designation"] == "Supervisor"


def test_recommitting_the_same_effective_date_replaces_it(client):
    """A corrected file is re-sent, not merged with the wrong one."""
    h = _signup(client, "wf5@example-co.com", "Workforce Five")
    meta = '{"effective_from": "2025-04-01"}'

    client.post(
        "/api/workforce/master/commit",
        files={"file": ("m.csv", _csv([{"Emp Code": "1001", "Designation": "Typo"}]), "text/csv")},
        data={"meta": meta},
        headers=h,
    )
    client.post(
        "/api/workforce/master/commit",
        files={"file": ("m.csv", _csv([{"Emp Code": "1001", "Designation": "Operator"}]), "text/csv")},
        data={"meta": meta},
        headers=h,
    )

    uploads = client.get("/api/workforce/master/uploads", headers=h).json()["data"]
    assert len(uploads) == 1

    records = client.get("/api/workforce/master?as_of=2025-04-30", headers=h).json()["data"]
    assert len(records) == 1
    assert records[0]["designation"] == "Operator"


ATTENDANCE_ROWS = [
    {"Emp Code": "1001", "Paid Days": 30, "LOP": 0, "OT Hours": 8},
    {"Emp Code": "1002", "Paid Days": 25, "LOP": 5},
]


def test_attendance_commit_and_read_back(client):
    h = _signup(client, "wf6@example-co.com", "Workforce Six")
    r = client.post(
        "/api/workforce/attendance/commit",
        files={"file": ("att.csv", _csv(ATTENDANCE_ROWS), "text/csv")},
        data={"meta": '{"period_month": "2025-04-01"}'},
        headers=h,
    )
    assert r.status_code == 200, r.text
    register_id = r.json()["data"]["id"]

    detail = client.get(f"/api/workforce/attendance/{register_id}", headers=h).json()["data"]
    by_id = {row["employee_id"]: row for row in detail["rows"]}

    assert float(by_id["1001"]["paid_days"]) == 30
    assert float(by_id["1001"]["overtime_hours"]) == 8
    # April has 30 days, so the calendar figure is filled in for both rows.
    assert float(by_id["1002"]["calendar_days"]) == 30


def test_attendance_derives_the_missing_figure(client):
    h = _signup(client, "wf7@example-co.com", "Workforce Seven")
    rows = [{"Emp Code": "1001", "LOP": 3}]  # paid days not stated
    r = client.post(
        "/api/workforce/attendance/commit",
        files={"file": ("att.csv", _csv(rows), "text/csv")},
        data={"meta": '{"period_month": "2025-05-01"}'},  # 31 days
        headers=h,
    )
    register_id = r.json()["data"]["id"]
    detail = client.get(f"/api/workforce/attendance/{register_id}", headers=h).json()["data"]
    assert float(detail["rows"][0]["paid_days"]) == 28


def test_attendance_is_scoped_to_its_entity(client):
    h = _signup(client, "wf8@example-co.com", "Workforce Eight")
    other = client.post("/api/org/entities", json={"name": "Other Client"}, headers=h).json()["data"]["id"]

    r = client.post(
        "/api/workforce/attendance/commit",
        files={"file": ("att.csv", _csv(ATTENDANCE_ROWS), "text/csv")},
        data={"meta": '{"period_month": "2025-04-01"}'},
        headers=h,
    )
    register_id = r.json()["data"]["id"]

    r = client.get(f"/api/workforce/attendance/{register_id}", headers={**h, "X-Entity-Id": other})
    assert r.status_code == 404

    assert client.get("/api/workforce/attendance", headers={**h, "X-Entity-Id": other}).json()["data"] == []
