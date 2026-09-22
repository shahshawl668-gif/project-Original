"""
Reading a bank file through a profile.

The property this suite defends is that the parser never invents a number. A
column it cannot read is reported, not defaulted to zero; a required mapping
that is missing is an error, not a guess; a control total on the trailer is
recognised as a control total rather than counted as a payment. Each of those
failures would produce a reconciliation that agrees with itself and means
nothing, which is worse than no reconciliation at all.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services import bank_file as bf


def _parse(text: str, profile: dict, name: str = "bank.csv"):
    return bf.parse_bank_file(text.encode(), name, profile)


BASE = {
    "layout": "delimited", "delimiter": ",", "has_header": True,
    "skip_rows": 0, "trailer_rows": 0, "amount_unit": "rupees", "amount_sign": "as_is",
    "employee_id_transform": "trim",
    "column_map": {"employee_id": "code", "amount": "amount"},
}


# ---------------------------------------------------------------------------
# Amounts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("12345.67", Decimal("12345.67")),
        ("12,345.67", Decimal("12345.67")),
        ("₹ 12,345.67", Decimal("12345.67")),
        ("(500.00)", Decimal("-500.00")),
        ("500.00 DR", Decimal("-500.00")),
        ("500.00 CR", Decimal("500.00")),
        (" 42 ", Decimal("42.00")),
    ],
)
def test_the_shapes_an_indian_bank_file_writes_an_amount_in(raw, expected):
    assert bf.parse_amount(raw) == expected


def test_an_amount_that_is_not_a_number_is_refused_rather_than_zeroed():
    # The distinction the whole module rests on: a cell nobody can read is an
    # exception, and calling it zero would hide a payment.
    assert bf.parse_amount("N/A") is None
    assert bf.parse_amount("") is None
    assert bf.parse_amount(None) is None


def test_paise_are_divided_and_rupees_are_not():
    assert bf.parse_amount("1234567", unit="paise") == Decimal("12345.67")
    assert bf.parse_amount("1234567", unit="rupees") == Decimal("1234567.00")


def test_the_sign_convention_is_applied_as_configured():
    assert bf.parse_amount("-500", sign="absolute") == Decimal("500.00")
    assert bf.parse_amount("500", sign="negate") == Decimal("-500.00")
    assert bf.parse_amount("-500", sign="as_is") == Decimal("-500.00")


# ---------------------------------------------------------------------------
# Employee codes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "transform,raw,expected",
    [
        ("trim", "  EMP001  ", "EMP001"),
        ("upper", "emp001", "EMP001"),
        ("strip_leading_zeros", "000042", "42"),
        ("digits_only", "EMP0042", "0042"),
        ("alnum_upper", "emp-00/42", "EMP0042"),
    ],
)
def test_every_id_transform_a_profile_can_choose(transform, raw, expected):
    assert bf.normalise_employee_id(raw, transform) == expected


def test_matching_is_case_insensitive_without_being_fuzzy():
    # A register holding emp0042 must meet a bank file holding EMP0042 …
    assert bf.match_key("emp0042") == bf.match_key("EMP0042")
    # … but two genuinely different codes stay different.
    assert bf.match_key("EMP0042") != bf.match_key("EMP0043")


def test_an_id_that_is_only_zeros_survives_the_strip():
    # "0" is a real employee code somewhere. Stripping it to nothing would
    # silently drop that person from every reconciliation.
    assert bf.normalise_employee_id("000", "strip_leading_zeros") == "0"


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------
def test_a_header_row_maps_columns_by_name():
    result = _parse("code,amount\nE1,1000\nE2,2500.50\n", BASE)
    assert [r.employee_id for r in result.rows] == ["E1", "E2"]
    assert result.total == Decimal("3500.50")


def test_a_headerless_file_maps_columns_by_position():
    profile = {**BASE, "has_header": False,
               "column_map": {"employee_id": 2, "amount": 4, "employee_name": 3}}
    result = _parse("X,E1,Asha,1000\nX,E2,Ben,2000\n", profile)
    assert [(r.employee_id, r.employee_name) for r in result.rows] == [("E1", "Asha"), ("E2", "Ben")]
    assert result.total == Decimal("3000.00")


def test_a_fixed_width_file_is_sliced_by_start_and_length():
    profile = {
        **BASE, "layout": "fixed", "has_header": False,
        "column_map": {"employee_id": [1, 6], "amount": [7, 12]},
    }
    # Six characters of code, then the amount right-aligned in twelve.
    lines = "E00001" + "12345.67".rjust(12) + "\n" + "E00002" + "1000.00".rjust(12) + "\n"
    result = _parse(lines, profile)
    assert [r.employee_id for r in result.rows] == ["E00001", "E00002"]
    assert result.total == Decimal("13345.67")


def test_a_pipe_delimiter_is_honoured():
    profile = {**BASE, "delimiter": "|"}
    result = _parse("code|amount\nE1|900\n", profile)
    assert result.rows[0].amount == Decimal("900.00")


def test_rows_before_the_header_are_skipped():
    profile = {**BASE, "skip_rows": 2}
    result = _parse("Bank of Somewhere\nStatement\ncode,amount\nE1,100\n", profile)
    assert len(result.rows) == 1


# ---------------------------------------------------------------------------
# The trailer
# ---------------------------------------------------------------------------
def test_a_control_total_is_read_as_a_total_and_not_counted_as_a_payment():
    profile = {**BASE, "trailer_rows": 1}
    result = _parse("code,amount\nE1,1000\nE2,2000\nTOTAL,3000\n", profile)
    assert len(result.rows) == 2
    assert result.total == Decimal("3000.00")
    assert result.stated_total == Decimal("3000.00")


def test_a_trailer_that_disagrees_with_the_lines_is_left_for_reconciliation_to_report():
    # The parser records both figures rather than resolving them. Deciding
    # which one is wrong is not a parsing question.
    profile = {**BASE, "trailer_rows": 1}
    result = _parse("code,amount\nE1,1000\nE2,2000\nTOTAL,9999\n", profile)
    assert result.total == Decimal("3000.00")
    assert result.stated_total == Decimal("9999.00")


def test_dropping_more_trailer_rows_than_the_file_has_is_an_error():
    with pytest.raises(bf.ProfileError, match="trailer"):
        _parse("code,amount\nE1,100\n", {**BASE, "trailer_rows": 3})


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def test_a_row_filter_keeps_only_the_salary_lines_of_a_statement():
    profile = {
        **BASE,
        "column_map": {"employee_id": "code", "amount": "amount", "txn_type": "type"},
        "row_filter": {"column": "type", "in": ["SAL"]},
    }
    result = _parse(
        "code,amount,type\nE1,1000,SAL\nE2,50,FEE\nE3,2000,SAL\n", profile
    )
    assert [r.employee_id for r in result.rows] == ["E1", "E3"]
    assert result.skipped == 1


def test_a_contains_filter_matches_part_of_a_narration():
    profile = {
        **BASE,
        "column_map": {"employee_id": "code", "amount": "amount", "txn_type": "narration"},
        "row_filter": {"column": "narration", "contains": "salary"},
    }
    result = _parse(
        "code,amount,narration\nE1,1000,SALARY JUN\nE2,50,ATM WITHDRAWAL\n", profile
    )
    assert len(result.rows) == 1


# ---------------------------------------------------------------------------
# Refusing to guess
# ---------------------------------------------------------------------------
def test_a_profile_missing_a_required_mapping_is_refused_by_name():
    with pytest.raises(bf.ProfileError) as excinfo:
        _parse("code,amount\nE1,100\n", {**BASE, "column_map": {"employee_id": "code"}})
    assert "amount" in str(excinfo.value)


def test_an_unreadable_row_is_reported_and_left_out_of_the_total():
    result = _parse("code,amount\nE1,1000\nE2,n/a\nE3,500\n", BASE)
    assert len(result.rows) == 2
    assert result.total == Decimal("1500.00")
    assert any("Row 2" in p for p in result.problems)


def test_a_file_no_row_of_which_can_be_read_is_an_error_not_an_empty_result():
    with pytest.raises(bf.ProfileError):
        _parse("code,amount\nE1,n/a\nE2,n/a\n", BASE)


def test_column_names_that_appear_nowhere_in_the_header_are_reported():
    profile = {**BASE, "column_map": {"employee_id": "staff_no", "amount": "net"}}
    with pytest.raises(bf.ProfileError):
        _parse("code,amount\nE1,100\n", profile)


def test_rows_without_an_employee_code_are_counted_and_flagged():
    profile = {**BASE, "column_map": {"employee_id": "code", "amount": "amount"}}
    result = _parse("code,amount\nE1,1000\n,2000\n", profile)
    assert len(result.rows) == 2
    assert result.rows[1].employee_id is None
    assert any("no employee code" in p for p in result.problems)


# ---------------------------------------------------------------------------
# Dates and account numbers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [("15/06/2026", date(2026, 6, 15)), ("2026-06-15", date(2026, 6, 15)),
     ("15-Jun-2026", date(2026, 6, 15))],
)
def test_the_date_formats_indian_bank_files_use(raw, expected):
    assert bf.parse_bank_date(raw) == expected


def test_an_account_number_keeps_its_leading_zeros():
    profile = {**BASE, "column_map": {"employee_id": "code", "amount": "amount",
                                      "account_number": "acct"}}
    result = _parse("code,amount,acct\nE1,100,000123456789\n", profile)
    # Through a float this becomes 123456789 — a different account.
    assert result.rows[0].account_number == "000123456789"


# ---------------------------------------------------------------------------
# Suggestion is a proposal, never an application
# ---------------------------------------------------------------------------
def test_a_mapping_suggested_from_headers_names_what_it_matched_against():
    suggestion = bf.suggest_mapping(
        b"Employee Code,Beneficiary Name,Payee Account No,IFSC Code,Amount\n"
        b"E1,Asha,000123,HDFC0001,1000\n",
        "bank.csv",
    )
    assert suggestion["column_map"]["employee_id"] == "Employee Code"
    assert suggestion["column_map"]["amount"] == "Amount"
    assert suggestion["column_map"]["account_number"] == "Payee Account No"
    # The headers come back with it, so the person approving can see the basis.
    assert "IFSC Code" in suggestion["header"]


def test_a_suggestion_never_maps_one_column_to_two_fields():
    suggestion = bf.suggest_mapping(b"Amount,Net Amount\n1,2\n", "bank.csv")
    used = list(suggestion["column_map"].values())
    assert len(used) == len(set(used))


def test_every_preset_declares_the_fields_a_parse_requires():
    for preset in bf.PRESETS:
        missing = [f for f in bf.REQUIRED_FIELDS if not preset["column_map"].get(f)]
        assert not missing, f"{preset['key']} does not map {missing}"


def test_the_generic_preset_reads_a_file_written_to_its_own_shape():
    preset = bf.PRESET_BY_KEY["generic_csv"]
    result = _parse(
        "employee_id,employee_name,account_number,ifsc,amount,reference\n"
        "E1,Asha,000123456,HDFC0000001,45000.50,UTR1\n",
        preset,
    )
    assert result.rows[0].employee_id == "E1"
    assert result.rows[0].amount == Decimal("45000.50")
    assert result.rows[0].ifsc == "HDFC0000001"
