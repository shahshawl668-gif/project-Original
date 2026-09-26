# Configuration CSV upload

Download **Settings → Configuration upload → Download configuration CSV template** for the selected entity. Edit a copy as UTF-8 CSV, preview the upload, check the section counts, and apply. The downloaded file is a complete backup and an upload template. Upload accepts CSV, up to 5 MB and 10,000 configuration records. It never imports users, permissions, payroll registers, approvals, or audit history.

## Columns

| Column | Meaning | Example |
| --- | --- | --- |
| `section` | Configuration category. Keep the exact identifier. | `components` |
| `record` | Positive integer identifying one item within a section. Start at 1 without gaps. | `1` |
| `field` | Setting name. Each item needs all fields in the downloaded template. | `pf_applicable` |
| `type` | `text`, `escaped_text`, `number`, `boolean`, `json`, `null`, or `empty`. | `boolean` |
| `value` | Setting value; leave blank only for `null` or `empty`. | `true` |

Each CSV line sets one field. Lines with the same `section` and `record` make one item. Preserve the header exactly. CSV quoting is required for JSON values containing commas or quotation marks; spreadsheet exports usually do this automatically. The download includes a UTF-8 BOM so spreadsheet software reads it correctly. Dates are `YYYY-MM-DD` in `text` cells. `boolean` is lowercase `true` or `false`. `number` uses a dot decimal separator with no currency symbol. `json` holds an object or array in a single CSV cell (for example, a salary register column mapping). A leading apostrophe in `escaped_text` protects strings starting with a spreadsheet formula character; the apostrophe is removed on import. Do not change `type` without changing the value accordingly.

```csv
section,record,field,type,value
components,1,component_name,text,Basic
components,1,pf_applicable,boolean,true
components,1,esic_applicable,boolean,true
components,1,pt_applicable,boolean,true
components,1,lwf_applicable,boolean,true
components,1,bonus_applicable,boolean,false
components,1,included_in_wages,boolean,true
components,1,taxable,boolean,true
components,1,tax_exemption_type,text,none
```

This example defines one component. The actual download supplies every field for every existing record and lists all categories. To add a component, copy all fields from an existing component, change `record` to the next integer, and edit its values. For a category with no records, the download has `section,0,,empty,`. Replace this line with the new item's complete field lines. You can get field names from an existing item or the category table below; the application checks required fields on preview.

## Categories and fields

| `section` | Fields for each record | Purpose |
| --- | --- | --- |
| `components` | `component_name`, `pf_applicable`, `esic_applicable`, `pt_applicable`, `lwf_applicable`, `bonus_applicable`, `included_in_wages`, `taxable`, `tax_exemption_type` | Salary component names and statutory tags. |
| `statutory_settings` | `pf_wage_ceiling`, `pf_employee_rate`, `pf_employer_rate`, `pf_eps_rate`, `pf_edli_rate`, `pf_admin_rate`, `pf_restrict_to_ceiling`, `esic_wage_ceiling`, `esic_employee_rate`, `esic_employer_rate`, `esic_round_mode`, `pt_states`, `lwf_states` | Entity PF/ESIC parameters and enabled states. |
| `statutory_engine` | `pf_config`, `esic_config`, `component_mapping_config`, `income_tax_config`, `rule_thresholds_config`, `exposure_config` | Nested engine policies; keep the downloaded JSON structure. |
| `formulas` | `rule_type`, `name`, `expression`, `conditions`, `version`, `is_active` | Validation formulas. |
| `pt_lwf_slabs` | `state`, `rule_type`, `min_salary`, `max_salary`, `deduction_amount`, `employer_amount`, `frequency`, `gender`, `applicable_months`, `sort_order` | PT/LWF slabs. Verify the governing notification before editing. |
| `minimum_wage_rates` | `state`, `zone`, `scheduled_employment`, `skill_category`, `basic_per_month`, `vda_per_month`, `working_days_basis`, `effective_from`, `effective_to`, `source_reference` | Dated minimum wage schedules. |
| `minimum_wage_applicability` | `effective_from`, `applicable`, `reason`, `source_reference` | Dated Yes/No decision; No requires a reason. |
| `rule_preferences` | `rule_id`, `suppressed` | Per-entity validation rule preferences. |
| `salary_import_profiles` | `name`, `column_mapping` | Named mapping from a client's register headings to canonical payroll fields. `column_mapping` is JSON. |
| `bank_file_profiles` | `name`, `bank_label`, `note`, `kind`, `layout`, `delimiter`, `encoding`, `has_header`, `skip_rows`, `trailer_rows`, `column_map`, `amount_unit`, `amount_sign`, `date_format`, `employee_id_transform`, `row_filter`, `is_default` | Bank file parsing settings. |
| `jv_templates` | `name`, `note`, `posting_basis`, `split_mode`, `group_by`, `detail_level`, `sign_convention`, `net_pay_source`, `voucher_date_rule`, `voucher_type`, `narration_template`, `export_format`, `balance_tolerance`, `rounding_mode`, `rounding_account` | Journal voucher template settings. |
| `jv_rules` | `template_name`, `sequence`, `label`, `account_code`, `account_name`, `side`, `measures`, `filters`, `cost_center_from`, `active`, `note` | Rules linked by exact `template_name` to a template in the same file. |

## Replacement and safety

Each included section **replaces all existing records** in that category for the selected entity. To leave a section unchanged, remove *all* its lines. An `empty` line intentionally clears the section. `jv_templates` and `jv_rules` must both be included or both omitted. An approved JV template blocks replacement; imported JV templates require review and approval. The preview validates names, values, JSON shapes, foreign references, and record numbering without saving; applying is transactional. The file cannot set entity IDs or another client's configuration.

Configuration upload is separate from salary register upload. A `salary_import_profiles` mapping lets the register importer recognize client column headings, while `components` defines how named salary columns are treated for PF, ESIC, PT, LWF and other checks. Download the register's own sample CSV from its upload screen; this configuration CSV is for setup, not payroll rows.

PT/LWF and minimum wage notifications change by state, locality, employment and effective date. A CSV edit does not verify a legal rate; check the source notification and effective period before applying statutory values.
