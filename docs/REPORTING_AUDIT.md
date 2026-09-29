# Reporting architecture audit — 29 September 2026

This inventory reflects the repository at the start of the reporting work. “Implemented” means code exists; it does not certify business acceptance or deployment. Payroll statutory rates remain configured by customers and are not represented as official filing formats.

| Capability | Status | Evidence and next work |
| --- | --- | --- |
| Eleven Excel reports | Implemented | `services/reporting.py` catalogue: management summary, dimension cost, headcount, compensation, statutory cost, budget variance, components, findings reconciliation, bank/JV reconciliation, employee cost, pay equity. |
| BI metric reuse | Partial | Reporting calls `analytics.py`, `cost_model.py`, and reconciliation services. Define one versioned metric contract for all new datasets and test control totals across each surface. |
| Company isolation and masking | Partial | Entity-scoped router and identity masking exist. Saved definitions, output files, schedule execution, and download-time revocation need separate checks. |
| Provenance | Partial | Excel includes entity, dates, filters, requester, data freshness and basis. It does not persist an immutable report definition/version, run ID, signed snapshot, input/rule references or artifact history. Current-state findings cannot reconstruct historical status. |
| Spreadsheet export | Partial | Workbook creation, typed numeric cells, freeze panes, filters and basis exist. This branch hardens formula-like text, identifier columns, width scanning and row splitting. Streaming, download history and retention remain. |
| CSV and PDF | Missing | No reporting routes or output generators. |
| Report Centre | Partial | Existing report page is a catalogue and immediate download. No saved, favourites, recent, jobs or status distinctions. |
| Report Builder | Missing | No approved dataset registry, safe expression language, join/grain planner, saved definitions or pivot preview. |
| Report schedules | Missing | Studio has workflow scheduling, but its report action links to a page rather than generating a report. No report prerequisites, artifact delivery or idempotency. |
| Background generation | Missing | Validation and Studio workers exist; report generation is synchronous in the request. Queue, cancellation, progress, retention and benchmarks remain. |
| Permissions | Partial | Router checks report rights and pay-equity authorization. Field-level and artifact-level access and company-shared publication need design and tests. |

## Existing metric contract to preserve

- Register row grain is employee within a payroll month. Component rows and findings have different grains; do not join them into a cost total without reducing to the employee-month grain first.
- Gross is payroll earnings; deductions are employee deductions; net is gross minus deductions; employer cost is employer contributions; CTC is gross plus employer contributions. The `cost_model.py` register values take precedence where provided, with calculated fallback.
- Payroll headcount is distinct employees with a regular payroll register row; person-months are the sum of monthly register counts. Average monthly cost per head is total CTC divided by person-months.
- Dimensions come from register snapshots and retain an Unassigned bucket. Missing months are absent, not zero. Currency rounding and comparison periods must be explicit in each future definition.
- Finding financial impact is not automatically additive across rules or runs. A financial-impact report needs a deduplication policy and stated impact grain before a management total is published.

## Standard report input inventory

| Existing report | Minimum input | Grain / caveat |
| --- | --- | --- |
| Management summary, dimension cost, component breakdown, employee cost | Salary register and mapped component values | Employee-month source; component breakdown expands to component grain. |
| Headcount, compensation | Salary register | Register population, not HR employment chronology. |
| Statutory cost | Salary register, configured statutory rules for exposure | Analytical validation; no official filing claim. |
| Budget variance | Register and approved budget | Missing budget must be stated. |
| Reconciliation | Findings/current state | Current state only; historical finding comparison needs run snapshots. |
| Bank/JV reconciliation | Register, bank and JV imports | Missing external source must be stated. |
| Pay equity | Register, authorised protected-attribute analysis | Aggregate with small-group suppression. |

## Implementation sequence and gates

1. Stabilise existing totals, spreadsheet safety and date scoping; keep these tests in CI.
2. Add report definitions with explicit grain and required-data metadata; create persisted jobs/artifacts and CSV/PDF generators, then expand verified standard reports.
3. Add approved datasets and a safe builder with scoped preview and versioned saved definitions.
4. Integrate report jobs with Studio schedules and notifications, followed by synthetic 8,000/20,000 employee benchmarks and visual export checks.

A downloadable workbook is generated from current data. Until immutable inputs and output retention are implemented, it is **not** a signed, reproducible historical snapshot.