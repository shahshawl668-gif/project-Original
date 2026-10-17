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
* EPF/EPS/EDLI ceiling ₹25,000 from 17 Sep 2026 — S.O. 5109(E); September
  2026 contributions split: 1–16 Sep on ₹15,000, 17–30 Sep on ₹25,000.
* ESI Act s.2(9) proviso — an employee whose wage rises above the ceiling
  after a contribution period (April–September, October–March) begins stays
  covered to its end. Coverage is proven from wages earlier in the period;
  where months of the period are missing, it cannot be told either way.
* EPS — the pensionable-wage cap follows the ₹25,000 ceiling, September 2026
  split by days; new entrants are EPS members up to ₹25,000 (SGCMS summary of
  G.S.R. 847(E)).
* CBDT salary-TDS circular — no tax is deducted where income is below the
  taxable limit, PAN or not; the no-PAN rate applies only where tax is due.
* State LWF schedules — Gujarat contributions on June and December wages.
* Odisha PT — above ₹3 lakh a year: ₹200 a month for eleven months and ₹300 in
  the last month (odishatax.gov.in).
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
        cols += [k for k in r if k not in cols]
    lines = [",".join(["paid_days", "lop_days", *cols])]
    for r in rows:
        lines.append(",".join([str(days), "0", *(str(r.get(c, "")) for c in cols)]))
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
        employee("OC3", "Odisha", 18000, pt=200),
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


def test_september_2026_is_split_at_the_17th(client, company):
    # 12% × (15,000 × 16/30 + 20,000 × 14/30) = 12% × 17,333.33 = 2,080
    found = validate(client, company, "2026-09-01", [
        employee("SP1", "Maharashtra", 20000, pf=2080, pt=200),
        employee("SP2", "Maharashtra", 20000, pf=1800, pt=200),   # whole month on the old ceiling
        employee("SP3", "Maharashtra", 20000, pf=2400, pt=200),   # whole month on the new ceiling
        employee("SP4", "Maharashtra", 40000, pf=2360, pt=200),   # 12% × (8,000 + 11,666.67)
    ])
    assert serious(found["SP1"]) == []
    assert serious(found["SP4"]) == []
    assert rules(found["SP2"]) & {"STAT-001", "PF-009"}
    assert rules(found["SP3"]) & {"STAT-001", "PF-009"}


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


def _unconfirmed(findings: list[dict]) -> bool:
    by_rule = {f["rule_id"]: f for f in findings if f["rule_id"] in ("STAT-006", "STAT-007")}
    return (set(by_rule) == {"STAT-006", "STAT-007"}
            and all(f.get("actual_value") == "(missing)" and f.get("status") != "PASS" for f in by_rule.values()))


def test_esic_without_the_periods_registers_is_neither_passed_nor_failed(client, company):
    # No register stored for October 2026 – January 2027 (the October tests
    # store October, but not this employee, and November–January are absent).
    found = validate(client, company, "2027-02-01", [
        employee("EU1", "Karnataka", 11500, gross_extra=1500, esic=True),    # deducted
        employee("EU2", "Karnataka", 11500, gross_extra=1500, esic=False),   # not deducted
    ])
    for eid in ("EU1", "EU2"):
        assert not rules(found[eid]) & {"STAT-006", "STAT-007"}, found[eid]
        assert _unconfirmed(found[eid]), found[eid]        # not a PASS: the commonest error hides here


def test_a_register_column_can_state_esic_coverage_where_history_cannot(client, company):
    row = employee("EK1", "Karnataka", 11500, gross_extra=1500, esic=True)
    row["esic_covered"] = "Y"
    found = validate(client, company, "2027-03-01", [row])
    assert serious(found["EK1"]) == []


def test_a_register_flag_does_not_override_a_new_period(client, company):
    # April: a new contribution period, so this month's wage decides. A
    # payroll system's own "covered" flag is the setting that goes wrong.
    row = employee("EF1", "Karnataka", 11500, gross_extra=1500, esic=True)
    row["esic_covered"] = "Y"
    april = validate(client, company, "2027-04-01", [row])
    assert rules(april["EF1"]) & {"STAT-006", "STAT-007"}


def test_a_wrong_deduction_does_not_vouch_for_the_next_month(client, company):
    # April 2027 deducted ESIC on 22,225 (wrong, and caught above). May
    # repeats it; last month's deduction is not evidence of coverage — April's
    # wage was above the ceiling, so it is still wrong.
    may = validate(client, company, "2027-05-01", [
        employee("EF1", "Karnataka", 11500, gross_extra=1500, esic=True),
    ])
    assert rules(may["EF1"]) & {"STAT-006", "STAT-007"}


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


def test_odisha_pt_is_300_in_the_last_month(client, company):
    found = validate(client, company, "2027-03-01", [
        employee("OD1", "Odisha", 18000, pt=300),
        employee("OD2", "Odisha", 18000, pt=200),
    ])
    assert "STAT-008" not in rules(found["OD1"])
    assert "STAT-008" in rules(found["OD2"])


def test_gujarat_lwf_falls_in_june_and_december_only(client, company):
    june = validate(client, company, "2026-06-01", [
        employee("LW1", "Gujarat", 9000, pt=200, lwf=6),
        employee("LW2", "Gujarat", 9000, pt=200, lwf=0),
    ])
    assert "STAT-009" not in rules(june["LW1"])
    assert "STAT-009" in rules(june["LW2"])
    october = validate(client, company, "2026-10-01", [employee("LW3", "Gujarat", 9000, pt=200, lwf=0)])
    assert "STAT-009" not in rules(october["LW3"])


def test_companies_with_the_old_odisha_schedule_get_the_march_row(client, company):
    import uuid

    from app.database import SessionLocal
    from app.models import SlabRule
    from app.seed import _add_odisha_march_pt

    db = SessionLocal()
    try:
        entity_id = uuid.UUID(company["X-Entity-Id"])

        def odisha():
            return db.query(SlabRule).filter_by(entity_id=entity_id, rule_type="PT", state="Odisha").all()

        for row in odisha():
            if row.applicable_months == [3]:
                db.delete(row)          # back to the catalog as it was before October 2026
        db.commit()
        _add_odisha_march_pt(db)
        _add_odisha_march_pt(db)        # idempotent
        assert sum(1 for r in odisha() if r.applicable_months == [3]) == 1
    finally:
        db.close()
    found = validate(client, company, "2027-03-01", [employee("OD3", "Odisha", 18000, pt=300)])
    assert "STAT-008" not in rules(found["OD3"])


# ---------------------------------------------------------------------------
# EPS: the pensionable-wage cap moves with the ceiling
# ---------------------------------------------------------------------------
def test_october_2026_eps_is_on_25000(client, company):
    found = validate(client, company, "2026-10-01", [
        employee("EP2", "Maharashtra", 30000, pt=200, eps=2083),                 # 8.33% × 25,000
        employee("EP3", "Maharashtra", 30000, pt=200, eps=1250),                 # still on 15,000
        employee("EP4", "Maharashtra", 20000, pt=200, eps=1666, doj="2026-10-05"),   # new entrant ≤ 25,000
        employee("EP5", "Maharashtra", 20000, pt=200, eps=0, doj="2020-06-01"),      # joined above 15,000
    ])
    assert "PF-004" not in rules(found["EP2"]), found["EP2"]
    assert "PF-004" in rules(found["EP3"])
    assert "PF-004" not in rules(found["EP4"]), found["EP4"]
    assert "PF-004" not in rules(found["EP5"]), found["EP5"]


def test_september_2026_eps_is_split_by_days(client, company):
    # 8.33% × (15,000 × 16/30 + 25,000 × 14/30) = 8.33% × 19,666.67 = 1,638
    found = validate(client, company, "2026-09-01", [
        employee("ES1", "Maharashtra", 40000, pf=2360, pt=200, eps=1638),
        employee("ES2", "Maharashtra", 40000, pf=2360, pt=200, eps=2083),
    ])
    assert "PF-004" not in rules(found["ES1"]), found["ES1"]
    assert "PF-004" in rules(found["ES2"])


# ---------------------------------------------------------------------------
# A state the catalog does not know is not a state that levies nothing
# ---------------------------------------------------------------------------
def test_an_unknown_lwf_state_is_reported_not_skipped(client, company):
    found = validate(client, company, "2026-10-01", [
        employee("US1", "Chandigarh", 20000),          # levies LWF; not in the bundled catalog
        employee("US2", "Maharastra", 20000),          # a typo
        employee("US3", "Uttar Pradesh", 20000),       # recorded as levying neither PT nor LWF
    ])
    assert "DATA-LWF-STATE" in rules(found["US1"])
    assert "DATA-LWF-STATE" in rules(found["US2"]) and "DATA-PT-STATE" in rules(found["US2"])
    assert not rules(found["US3"]) & {"DATA-LWF-STATE", "DATA-PT-STATE"}


# ---------------------------------------------------------------------------
# TDS risk: the employee's own regime, and arrears whatever was deducted
# ---------------------------------------------------------------------------
def _direct(client, headers, period: str, rows: list[dict]) -> dict[str, list[dict]]:
    r = client.post("/api/payroll/validate", headers=headers, json={"employees": rows, "period_month": period})
    assert r.status_code == 200, r.text
    return {row["employee_id"]: row.get("findings", []) for row in r.json()["data"]["results"]}


def test_tds_risk_follows_the_regime_and_arrears(client, company):
    base = {"state": "Maharashtra", "paid_days": 31, "lop_days": 0, "pan": "ABCPE1234K", "pt": 200}
    found = _direct(client, company, "2026-10-01", [
        # ₹6.1 lakh a year, nothing deducted: tax is due under the old regime, not the new.
        {**base, "employee_id": "TR1", "basic": 36000, "hra": 15000, "tds": 0, "tax_regime": "old"},
        {**base, "employee_id": "TR2", "basic": 36000, "hra": 15000, "tds": 0, "tax_regime": "new"},
        # ₹2 lakh of arrears bunched into the month, ₹5,000 deducted on regular pay only.
        {**base, "employee_id": "TR3", "basic": 80000, "hra": 32000, "basic_arrear": 200000, "tds": 5000},
        # The same pay with no arrears and tax deducted is not a risk month.
        {**base, "employee_id": "TR4", "basic": 80000, "hra": 32000, "tds": 5000},
    ])

    def risk(eid):
        return any(f["rule_id"] == "STAT-011" for f in found[eid])

    assert risk("TR1") and not risk("TR2")
    assert risk("TR3") and not risk("TR4")
