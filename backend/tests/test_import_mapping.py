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
