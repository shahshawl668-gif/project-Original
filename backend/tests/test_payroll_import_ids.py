"""Employee identifiers survive register upload without numeric coercion."""
import io

import pandas as pd
import pytest

from app.services.payroll_parse import dataframe_to_employees, parse_payroll_file


@pytest.mark.parametrize("header", ["Employee ID", "Emp ID", "Employee Code"])
@pytest.mark.parametrize("extension", ["csv", "xlsx"])
def test_upload_preserves_text_employee_ids(header, extension):
    frame = pd.DataFrame({header: ["00123", "00007"], "Basic": [15000, 12000]})
    if extension == "csv":
        content = frame.to_csv(index=False).encode()
    else:
        buffer = io.BytesIO()
        frame.to_excel(buffer, index=False)
        content = buffer.getvalue()

    columns, records = dataframe_to_employees(
        parse_payroll_file(content, f"register.{extension}")
    )

    key = header.lower().replace(" ", "_")
    assert key in columns
    assert [row[key] for row in records] == ["00123", "00007"]
    assert records[0]["basic"] == 15000.0


def test_numeric_excel_employee_id_is_string():
    buffer = io.BytesIO()
    pd.DataFrame({"Employee ID": [123], "Basic": [15000]}).to_excel(buffer, index=False)
    _, records = dataframe_to_employees(parse_payroll_file(buffer.getvalue(), "register.xlsx"))
    assert records[0]["employee_id"] == "123"
