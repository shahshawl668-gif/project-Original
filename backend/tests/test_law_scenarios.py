"""
Registers built by hand from the law, not from the engine.

Every other suite here checks the engine against expectations written next to
it, which is how a whole suite can stay green while the law moves: when the
EPF wage ceiling rose to ₹25,000 on 17 September 2026, 1,317 tests still passed
and a correct October register came back with six critical findings.

These scenarios are written from the statute and the state schedules. A clean
employee is payroll done correctly for that month; the product must raise
nothing above INFO against them. A planted employee carries one real mistake;
the product must report it. When a law changes, a scenario here changes first.

Sources (also in docs/STATUTORY_RATE_AUDIT.md):
* EPF/EPS/EDLI ceiling ₹25,000 from 17 Sep 2026 — S.O. 5109(E). September 2026
  is worked on one blended ceiling, 15,000 × 16/30 + 25,000 × 14/30 = 19,667.
* ESI Act s.2(9) proviso — an employee whose wage rises above the ceiling
  after a contribution period (April–September, October–March) begins stays
  covered to its end. Where an earlier month of the period is not loaded, a
  deduction above the ceiling can be neither confirmed nor faulted.
* CBDT salary-TDS circular — no tax is deducted where income is below the
  taxable limit, PAN or not; the no-PAN rate applies only where tax is due.
* State LWF schedules — half-yearly contributions on June and December wages.
  Haryana ₹35/₹70 from 1 Jan 2026 (HLWB/REV/2026/3436); Madhya Pradesh
  employer ₹50 a half-year from 2026 (rules amendment of 28 Jan 2026).
* Odisha PT — to 31 March 2026, above ₹3 lakh a year: ₹200 a month for eleven
  months and ₹300 in March (odishatax.gov.in). Repealed from 1 April 2026 by
  Ordinance 02 of 2026 (Finance Department notification 1496, 21 Apr 2026).
"""
from __future__ import annotations

import calendar
import io
import json
import math

import pytest

PASSWORD = "Passw0rd!x"
COMPONENTS = [
    {"component_name": "Basic", "pf_applicable": True, "esic_applicable": True, "pt_applicable": True,
     "lwf_applicable": True, "included_in_wages": True, "taxable": True},
    {"component_name": "HRA", "esic_applicable": True, "pt_applicable": True, "included_in_wages": True,
     "taxable": True},
    {"component_name": "Special Allowance", "esic_applicable": True, "pt_applicable": True,
     "included_in_wages": True, "taxable": True},
    {"component_name": "Conveyance", "esic_applicable": True, "pt_applicable": True, "included_in_wages": True,
     "taxable": True},
]
SERIOUS = {"CRITICAL", "ERROR", "WARNING", "HIGH", "MEDIUM"}
STATUTORY = ("STAT-", "PF-", "TDS-", "ESI-", "PT-", "LWF-", "DATA-PT", "DATA-LWF")


def _ceil(x: float) -> int:
    return math.ceil(round(x, 4))


def employee(eid, state, basic, *, gender="M", pf=None, esic=None, pt=0, lwf=None, pan=True, gross_extra=0,
             **extra):
    """One register row. ``pf``/``esic`` default to the correct figure for a full month."""
    parts = {"basic": basic, "hra": round(basic * 0.4), "special allowance": round(basic * 0.25) + gross_extra,
             "conveyance": 1600}
    gross = sum(parts.values())
    pf = round(min(basic, 25000) * 0.12) if pf is None else pf
    if esic is None:
        esic = (_ceil(gross * 0.0075), _ceil(gross * 0.0325)) if gross <= 21000 else (0, 0)
    elif esic is True:
        esic = (_ceil(gross * 0.0075), _ceil(gross * 0.0325))
    elif esic is False:
        esic = (0, 0)
    n = sum(ord(ch) for ch in eid) * 7
    row = {
        "employee_id": eid, "employee_name": f"Employee {eid}", "gender": gender, "state": state,
        "uan": f"1012{n:08d}", "esi_number": f"31{n:08d}",
        "pan": f"ABCP{chr(65 + n % 26)}{1000 + n % 9000:04d}K" if pan else "",
        **parts,
        "pf_employee": pf, "pf_employer": pf,
        "esic_employee": esic[0], "esic_employer": esic[1],
        "pt": pt, "tds": 0,
    }
    if lwf is not None:
        row["lwf_employee"] = lwf
    row["net_pay"] = gross - pf - esic[0] - pt - (lwf or 0)
    row.update(extra)
    return row


def to_csv(rows: list[dict], days: int) -> str:
    cols: list[str] = []
    for r in rows:
        cols += [k for k in r if k not in cols and k not in ("paid_days", "lop_days")]
    lines = [",".join(["paid_days", "lop_days", *cols])]
    for r in rows:
        lines.append(",".join([str(r.get("paid_days", days)), str(r.get("lop_days", 0)),
                               *(str(r.get(c, "")) for c in cols)]))
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def company(client):
    email = "scenarios@law-example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": PASSWORD,
                                              "company_name": "Law Scenarios Pvt Ltd"})
    if r.status_code != 200:
        r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
    entity = client.post("/api/org/entities", json={"name": "Law Scenarios", "primary_state": "Maharashtra"},
                         headers=headers).json()["data"]["id"]
    headers["X-Entity-Id"] = entity
    for c in COMPONENTS:
        assert client.post("/api/components", json=c, headers=headers).status_code == 201
    for rule_type in ("PT", "LWF"):
        client.post(f"/api/rule-engine/slabs/import-defaults/all?rule_type={rule_type}&overwrite=true",
                    headers=headers)
    return headers


def upload(client, headers, period: str, rows: list[dict]) -> list[dict]:
    year, month = int(period[:4]), int(period[5:7])
    days = calendar.monthrange(year, month)[1]
    r = client.post("/api/payroll/upload", headers=headers,
                    files={"file": (f"reg-{period}.csv", io.BytesIO(to_csv(rows, days).encode()), "text/csv")},
                    data={"meta": json.dumps({"period_month": period, "strict_header_check": False})})
    assert r.status_code == 200, r.text
    return r.json()["data"]["employees"]


def validate(client, headers, period: str, rows: list[dict]) -> dict[str, list[dict]]:
    employees = upload(client, headers, period, rows)
    r = client.post("/api/payroll/validate", headers=headers,
                    json={"employees": employees, "period_month": period})
    assert r.status_code == 200, r.text
    return {row["employee_id"]: row.get("findings", []) for row in r.json()["data"]["results"]}


def serious(findings: list[dict]) -> list[str]:
    return [f"{f['rule_id']} {f['severity']}: {f.get('reason', '')[:120]}" for f in findings
            if f.get("severity") in SERIOUS and f.get("status") != "PASS" and f["rule_id"].startswith(STATUTORY)]


def rules(findings: list[dict]) -> set[str]:
    return {f["rule_id"] for f in findings if f.get("severity") in SERIOUS and f.get("status") != "PASS"}


# ---------------------------------------------------------------------------
# PF: the ₹25,000 ceiling from 17 September 2026
# ---------------------------------------------------------------------------
def test_october_2026_correct_pf_on_the_new_ceiling_is_clean(client, company):
    found = validate(client, company, "2026-10-01", [
        employee("OC1", "Maharashtra", 20000, pt=200),    # PF on 20,000: above the old limit, under the new
        employee("OC2", "Karnataka", 30000, pt=200, gender="F"),   # PF capped at 25,000 = 3,000
        employee("OC3", "Odisha", 18000, pt=0),            # no PT in Odisha from April 2026
        employee("OC4", "Gujarat", 9000, pt=200),         # ESIC-eligible
    ])
    for eid, findings in found.items():
        assert serious(findings) == [], (eid, serious(findings))


def test_october_2026_pf_still_on_the_old_ceiling_is_caught(client, company):
    found = validate(client, company, "2026-10-01", [
        employee("OX1", "Maharashtra", 22000, pf=1800, pt=200),   # should be 2,640
    ])
    assert rules(found["OX1"]) & {"STAT-001", "PF-009"}, found["OX1"]


def test_august_2026_is_still_on_the_old_ceiling(client, company):
    found = validate(client, company, "2026-08-01", [
        employee("AU1", "Maharashtra", 20000, pf=1800, pt=200),   # correct before 17 Sep 2026
    ])
    assert serious(found["AU1"]) == []




# ---------------------------------------------------------------------------
# ESIC: coverage runs to the end of the contribution period
# ---------------------------------------------------------------------------
def test_esic_continues_after_a_mid_period_raise(client, company):
    # The whole period so far is stored, so coverage can be told either way.
    for month in ("2026-04-01", "2026-05-01", "2026-06-01", "2026-07-01"):
        upload(client, company, month, [
            employee("EC1", "Karnataka", 11500),           # gross 20,725 → covered from April
            employee("EC2", "Karnataka", 11500),
            employee("EC3", "Karnataka", 13000),           # gross 23,050 → never covered
        ])
    found = validate(client, company, "2026-08-01", [
        employee("EC1", "Karnataka", 11500, gross_extra=1500, esic=True),    # gross 22,225: still covered
        employee("EC2", "Karnataka", 11500, gross_extra=1500, esic=False),   # stopped too early
        employee("EC3", "Karnataka", 13000, esic=True),                       # deducted though never covered
    ])
    assert serious(found["EC1"]) == [], serious(found["EC1"])
    assert rules(found["EC2"]) & {"STAT-006", "STAT-007"}
    assert rules(found["EC3"]) & {"STAT-006", "STAT-007"}


def test_esic_coverage_ends_with_the_contribution_period(client, company):
    upload(client, company, "2026-09-01", [employee("EP1", "Karnataka", 11500, gross_extra=1500, esic=True)])
    found = validate(client, company, "2026-10-01", [
        employee("EP1", "Karnataka", 11500, gross_extra=1500, esic=True),    # October: a new period begins
    ])
    assert rules(found["EP1"]) & {"STAT-006", "STAT-007"}




def test_a_part_month_is_read_on_its_full_month_rate(client, company):
    # Joined 20 November 2027 on about ₹30,000 a month: November earns 11/30 of
    # it, ₹12,594 — under ₹21,000 as earned, never within the ceiling as a rate.
    upload(client, company, "2027-11-01", [
        employee("EJ1", "Karnataka", 6663, doj="2027-11-20", paid_days=11, esic=False, pt=200),
    ])
    upload(client, company, "2027-12-01", [employee("EJ1", "Karnataka", 17212, doj="2027-11-20", pt=200)])
    found = validate(client, company, "2028-01-01", [
        employee("EJ1", "Karnataka", 17212, doj="2027-11-20", pt=200),        # no ESIC: correct
    ])
    assert not rules(found["EJ1"]) & {"STAT-006", "STAT-007"}, serious(found["EJ1"])


# ---------------------------------------------------------------------------
# TDS without a PAN
# ---------------------------------------------------------------------------
def test_no_pan_and_no_tax_due_is_not_a_finding(client, company):
    found = validate(client, company, "2026-10-01", [employee("NP1", "Karnataka", 9000, pan=False)])
    assert "TDS-001" not in rules(found["NP1"])


def test_no_pan_with_tax_due_is_still_caught(client, company):
    found = validate(client, company, "2026-10-01", [employee("NP2", "Karnataka", 90000, pan=False, pt=200)])
    assert "TDS-001" in rules(found["NP2"])


# ---------------------------------------------------------------------------
# PT and LWF: due months, and nothing silently skipped
# ---------------------------------------------------------------------------
def test_pt_is_checked_once_the_schedules_are_loaded(client, company):
    # No states ticked in settings: the loaded schedules decide which states are checked.
    found = validate(client, company, "2026-10-01", [
        employee("PT1", "Maharashtra", 20000, pt=0),      # ₹200 due
        employee("PT2", "Gujarat", 9000, pt=300),         # ₹200 due
        employee("PT3", "Delhi", 20000, pt=0),            # Delhi levies no PT
    ])
    assert "STAT-008" in rules(found["PT1"])
    assert "STAT-008" in rules(found["PT2"])
    assert serious(found["PT3"]) == []




def test_gujarat_lwf_falls_in_june_and_december_only(client, company):
    june = validate(client, company, "2026-06-01", [
        employee("LW1", "Gujarat", 9000, pt=200, lwf=6),
        employee("LW2", "Gujarat", 9000, pt=200, lwf=0),
    ])
    assert "STAT-009" not in rules(june["LW1"])
    assert "STAT-009" in rules(june["LW2"])
    october = validate(client, company, "2026-10-01", [employee("LW3", "Gujarat", 9000, pt=200, lwf=0)])
    assert "STAT-009" not in rules(october["LW3"])




# ---------------------------------------------------------------------------
# EPS: the pensionable-wage cap moves with the ceiling
# ---------------------------------------------------------------------------


def test_september_2026_eps_is_split_by_days(client, company):
    # 8.33% × (15,000 × 16/30 + 25,000 × 14/30) = 8.33% × 19,666.67 = 1,638
    found = validate(client, company, "2026-09-01", [
        employee("ES1", "Maharashtra", 40000, pf=2360, pt=200, eps=1638),
        employee("ES2", "Maharashtra", 40000, pf=2360, pt=200, eps=2083),
    ])
    assert "PF-004" not in rules(found["ES1"]), found["ES1"]
    assert "PF-004" in rules(found["ES2"])




# ---------------------------------------------------------------------------
# TDS risk: the employee's own regime, and arrears whatever was deducted
# ---------------------------------------------------------------------------
def _direct(client, headers, period: str, rows: list[dict]) -> dict[str, list[dict]]:
    r = client.post("/api/payroll/validate", headers=headers, json={"employees": rows, "period_month": period})
    assert r.status_code == 200, r.text
    return {row["employee_id"]: row.get("findings", []) for row in r.json()["data"]["results"]}


def test_odisha_pt_was_300_in_march_until_the_repeal(client, company):
    found = validate(client, company, "2026-03-01", [
        employee("OD1", "Odisha", 18000, pf=1800, pt=300),
        employee("OD2", "Odisha", 18000, pf=1800, pt=200),
    ])
    assert "STAT-008" not in rules(found["OD1"])
    assert "STAT-008" in rules(found["OD2"])


def test_odisha_levies_no_pt_from_april_2026(client, company):
    found = validate(client, company, "2026-11-01", [
        employee("OR1", "Odisha", 18000, pt=0),
        employee("OR2", "Odisha", 18000, pt=200),         # still deducting a repealed tax
    ])
    assert serious(found["OR1"]) == [], serious(found["OR1"])
    assert "STAT-008" in rules(found["OR2"])
    reason = next(f["reason"] for f in found["OR2"] if f["rule_id"] == "STAT-008")
    assert "nil" in reason


def test_companies_with_the_old_odisha_schedule_are_brought_up_to_the_law(client, company):
    import uuid

    from app.database import SessionLocal
    from app.models import AuditEvent, SlabRule
    from app.seed import _correct_odisha_pt

    db = SessionLocal()
    try:
        entity_id = uuid.UUID(company["X-Entity-Id"])

        def odisha():
            return db.query(SlabRule).filter_by(entity_id=entity_id, rule_type="PT", state="Odisha").all()

        for row in odisha():
            if row.applicable_months == [3] or row.effective_from is not None:
                db.delete(row)          # back to the catalog as it was before November 2026
        db.commit()
        assert len(odisha()) == 3
        _correct_odisha_pt(db)
        _correct_odisha_pt(db)          # idempotent
        rows = odisha()
        assert sum(1 for r in rows if r.applicable_months == [3]) == 1
        nil = [r for r in rows if r.effective_from is not None]
        assert len(nil) == 1 and nil[0].effective_from.isoformat() == "2026-04-01" and nil[0].deduction_amount == 0
        trail = db.query(AuditEvent).filter_by(entity_id=entity_id, action="slab_rule.platform_correction").all()
        assert len(trail) == 2          # said in the company's own trail, once each
    finally:
        db.close()
    found = validate(client, company, "2026-12-01", [employee("OD3", "Odisha", 18000, pt=200)])
    assert "STAT-008" in rules(found["OD3"])


def test_haryana_lwf_follows_the_yearly_cap(client, company):
    # ₹35 / ₹70 from January 2026; ₹34 / ₹68 through 2025.
    now = validate(client, company, "2026-10-01", [
        employee("HR1", "Haryana", 20000, lwf=35),
        employee("HR2", "Haryana", 20000, lwf=31),        # the 2024 figure
    ])
    assert "STAT-009" not in rules(now["HR1"]), now["HR1"]
    assert "STAT-009" in rules(now["HR2"])
    earlier = validate(client, company, "2025-10-01", [employee("HR3", "Haryana", 14000, pf=1680, lwf=34)])
    assert "STAT-009" not in rules(earlier["HR3"]), earlier["HR3"]


def test_esic_above_the_ceiling_with_an_earlier_month_missing_is_not_confirmed(client, company):
    # February 2027: the months to December are stored by the tests above, but
    # January is not. Someone on ₹22,225 with ESIC deducted may have been
    # covered in a month that is not here.
    found = validate(client, company, "2027-02-01", [
        employee("EU1", "Karnataka", 11500, gross_extra=1500, esic=True),      # what a covered employee owes
        employee("EU2", "Karnataka", 11500, gross_extra=1500, esic=(50, 200)),  # wrong either way
        employee("EU3", "Karnataka", 11500, gross_extra=1500, esic=False),      # nothing deducted: nothing to fault
        employee("EU4", "Karnataka", 11500, gross_extra=1500, esic=True, doj="2027-02-03"),  # joined this month
    ])
    assert not rules(found["EU1"]) & {"STAT-006", "STAT-007"}, found["EU1"]
    named = {f["rule_id"]: f for f in found["EU1"] if f["rule_name"] == "ESIC Coverage Not Confirmed"}
    assert set(named) == {"STAT-006", "STAT-007"} and "January 2027" in named["STAT-006"]["reason"]
    assert rules(found["EU2"]) & {"STAT-006", "STAT-007"}
    assert not rules(found["EU3"]) & {"STAT-006", "STAT-007"}
    assert rules(found["EU4"]) & {"STAT-006", "STAT-007"}     # could not have been covered earlier
