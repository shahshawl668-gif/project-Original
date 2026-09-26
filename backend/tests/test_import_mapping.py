"""A client format must map safely without rewriting its monthly register."""
import pytest

from app.services.payroll_parse import (
    apply_mapping,
    check_mapping,
    dataframe_to_employees,
    parse_payroll_file,
    suggested_mapping,
    validate_required_columns,
)


def test_darwinbox_style_headers_and_zeros_preserved():
    content = b"Employee Number,Employee Name,Basic,Basic Arrears,HRA,Location State,Total Deductions,Net Salary\n00123,Asha,15000,2000,7000,Karnataka,1800,20200\n"
    df = parse_payroll_file(content, "register.csv")
    mapping = suggested_mapping(list(df.columns), {"Basic", "HRA"})
    assert mapping["Employee Number"] == "employee_id"
    assert mapping["Basic Arrears"] == "basic_arrear"
    assert mapping["Total Deductions"] == "total_deductions"
    check_mapping(list(df.columns), mapping, {"Basic", "HRA"})
    cols, rows = dataframe_to_employees(apply_mapping(df, mapping))
    assert rows[0]["employee_id"] == "00123"
    assert rows[0]["state"] == "Karnataka"
    assert rows[0]["basic_arrear"] == 2000
    assert validate_required_columns(cols, {"Basic", "HRA"}, True)[0] == []


def test_mapping_rejects_duplicate_destinations_and_unconfigured_components():
    with pytest.raises(ValueError, match="Two source columns"):
        check_mapping(["EMP ID", "Employee Number"],
                      {"EMP ID": "employee_id", "Employee Number": "employee_id"}, {"Basic"})
    with pytest.raises(ValueError, match="not configured"):
        check_mapping(["EMP ID", "Mystery"],
                      {"EMP ID": "employee_id", "Mystery": "mystery_allowance"}, {"Basic"})


def test_unmapped_columns_are_not_inferred_as_earnings():
    df = parse_payroll_file(b"EMP ID,Basic,Loan Recovery\n17,1000,500\n", "register.csv")
    mapped = apply_mapping(df, {"EMP ID": "employee_id", "Basic": "basic"})
    assert "Loan Recovery" not in mapped.columns


def test_row_specific_arrear_window_and_increment_survive_auto_mapping():
    df = parse_payroll_file(
        b"Employee ID,Basic,Basic Arrear,Arrear From,Arrear Months,Increment Arrear\n"
        b"E003,25000,6000,01/06/2026,3,9000\n", "mixed.csv"
    )
    mapping = suggested_mapping(list(df.columns), {"Basic"})
    _, rows = dataframe_to_employees(apply_mapping(df, mapping))
    assert rows[0]["arrear_from"] == "01/06/2026"
    assert rows[0]["arrear_months"] == 3.0
    assert rows[0]["increment_arrear"] == 9000.0


def test_entity_template_preview_and_saved_profile(client):
    signup = client.post("/api/auth/signup", json={
        "email": "import-profile-example@example.com", "password": "Passw0rd!x",
        "company_name": "Import Example",
    })
    assert signup.status_code == 200, signup.text
    headers = {"Authorization": f"Bearer {signup.json()['data']['access_token']}"}
    entity = client.post("/api/org/entities", json={"name": "Payroll Client"}, headers=headers)
    assert entity.status_code == 200, entity.text
    headers["X-Entity-Id"] = entity.json()["data"]["id"]
    component = client.post("/api/components", json={"component_name": "Basic"}, headers=headers)
    assert component.status_code == 201, component.text

    template = client.get("/api/payroll/template.csv", headers=headers)
    assert template.status_code == 200
    assert "Basic" in template.text.splitlines()[0]
    source = b"Employee Number,Base Pay,Total Deductions,Gross,Net\n0007,20000,1800,20000,18200\n"
    preview = client.post("/api/payroll/preview", headers=headers,
                          files={"file": ("register.csv", source, "text/csv")})
    assert preview.status_code == 200, preview.text
    mapping = {"Employee Number": "employee_id", "Base Pay": "basic",
               "Total Deductions": "total_deductions", "Gross": "gross", "Net": "net"}
    saved = client.post("/api/payroll/import-profiles", headers=headers,
                        json={"name": "Client monthly", "column_mapping": mapping})
    assert saved.status_code == 200, saved.text
    assert client.get("/api/payroll/import-profiles", headers=headers).json()["data"][0]["name"] == "Client monthly"

    import json
    uploaded = client.post("/api/payroll/upload", headers=headers,
                           files={"file": ("register.csv", source, "text/csv")},
                           data={"meta": json.dumps({"period_month": "2026-08-01", "column_mapping": mapping})})
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["data"]["employees"][0]["employee_id"] == "0007"
