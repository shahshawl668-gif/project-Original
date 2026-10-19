# Configuration upload (CSV or Excel)

**Company & access → Configuration upload.** Download the current configuration as CSV or Excel, change what you
want, preview, then apply. The download is also the template: kinds of setting with nothing saved yet show their
columns. It never carries users, permissions, payroll registers, approvals or audit history, and nothing in it is
code — only plain tables.

## The two formats

* **Excel (.xlsx):** a *Read me* sheet, then one sheet per kind of setting, with one row per record and one column
  per setting. Sheets you do not touch are ignored.
* **CSV:** the same tables in one file, as lines of `section, record, field, value`. Lines with the same section and
  record belong to one row.

```csv
section,record,field,value
components,1,component_name,Basic
components,1,pf_applicable,Yes
components,1,esic_applicable,Yes
statutory,1,pf_wage_ceiling,25000
statutory,1,pt_states,"Karnataka, Maharashtra"
```

Use **Yes / No** for switches, **YYYY-MM-DD** for dates, plain numbers (no currency symbol) and commas between list
items such as states or months. A kind of setting is applied when it has **at least one filled row**, and replaces
that kind of setting for the selected company; leave a sheet (or all of a section's lines) out to keep it as it is.
The preview lists what would be replaced before anything is saved, and applying is all-or-nothing.

## What each section holds

| Section | Columns |
| --- | --- |
| `components` | `component_name`, `pf_applicable`, `esic_applicable`, `pt_applicable`, `lwf_applicable`, `bonus_applicable`, `included_in_wages`, `taxable`, `tax_exemption_type` |
| `statutory` (one row) | `pf_employee_rate`, `pf_wage_ceiling`, `pf_restrict_to_ceiling`, `pf_employee_formula`, `esic_employee_rate`, `esic_wage_ceiling`, `esic_rounding` (up / down / nearest), `esic_employee_formula`, `esic_full_month_on_entry`, `esic_continue_month_on_exit`, `pt_states`, `lwf_states` |
| `pt_lwf_slabs` | `state`, `rule_type` (PT or LWF), `min_salary`, `max_salary`, `deduction_amount`, `employer_amount`, `frequency`, `gender`, `applicable_months`, `effective_from`, `effective_to`, `source_reference`, `sort_order` |
| `minimum_wage_rates` | `state`, `zone`, `scheduled_employment`, `skill_category`, `basic_per_month`, `vda_per_month`, `working_days_basis`, `effective_from`, `effective_to`, `source_reference` |
| `minimum_wage_applicability` | `effective_from`, `applicable`, `reason`, `source_reference` (a *No* needs a reason) |
| `rule_preferences` | `rule_id`, `suppressed` |
| `import_mappings` | `profile`, `file_column`, `product_field` — one row per column of your own file |

A PF or ESIC *formula* is written the way you would in Excel, for example `MIN((basic + special_allowance) * 12%, 3000)`.
What the file does not carry — employer, EPS, EDLI and admin rates, income-tax settings, thresholds and the rest of
the engine — is left exactly as it is.

Files in the earlier layout (with a `type` column and JSON cells) are not accepted; download the current file and
copy your values across.

## Other imports

The salary register, CTC, attendance and employee master are imported from CSV or Excel too. Their templates are
downloaded from the same screens as CSV or Excel and follow your salary components.

## A ready-made file for trying the product

`testdata/payroll-validation/1_configuration.csv` (and `.xlsx`) is a complete example for validation: five salary
components, PF and ESIC settings with formulas, Karnataka and Maharashtra professional tax slabs and a minimum-wage
decision. The slab and wage values are test data; do not use them for a real company.

PT/LWF and minimum wage notifications change by state, locality, employment and effective date. A file edit does not
verify a legal rate; check the source notification and effective period before applying statutory values.
