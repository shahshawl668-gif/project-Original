# Client register import

The import format is a saved translation, not a new payroll export specification.
Each entity keeps its own salary components and its own named import profiles.

1. Set up Basic, HRA, Special Allowance and other components under Salary Components, including their PF, ESIC, PT, LWF and wage flags.
2. Optionally download the CSV template on Payroll → Upload. Its header contains the entity's current components and standard payroll fields. Fill the rows and upload it.
3. Or upload the CSV/XLSX exported by the client's HRMS directly. The preview proposes matches such as `EMP ID` → `employee_id`, `Basic Arrears` → `basic_arrear`, `Location State` → `state` and `Total Deductions` → `total_deductions`.
4. Review **every** source column. Map each earning to its configured component, arrears to the component's arrear field, and totals/statutory deductions to standard fields. Ignored columns are shown as warnings. Two source columns cannot target the same field.
5. Give the mapping a name (for example, `Darwinbox monthly payroll`) to reuse it for future exports. A changed HRMS layout can be reviewed and the profile updated.
6. Preview the translated data, correct missing required components, then validate the period.

The CSV template is header-only to avoid creating plausible looking payroll for real employees. Excel source identifiers must be stored as text if leading zeros are significant. A numeric Excel cell that already lost its leading zeros cannot be repaired by import.

## Statutory configuration

PF and ESIC central settings are editable at entity level. PT/LWF depend on the employee's mapped work state; an unknown state now creates a finding instead of silently borrowing another state's rates. Validation uses the end of the selected payroll month as the reference date unless an explicit date is supplied.

Minimum wage schedules are entity-maintained and effective dated because the applicable rate also depends on zone, scheduled employment, skill classification, and revised VDA. A missing rate must remain visible. Do not mark a state as fully covered by copying a generic rate. Review the official notification and record its source reference when creating or revising a schedule.

Minimum-wage applicability is an explicit Yes/No selection for each entity, effective from a stated date. Until it is selected, the minimum-wage check returns a setup error. No skips that check for the selected period and requires a recorded reason; it is a product workflow choice, not a legal determination that an employer is exempt from minimum-wage law. Yes enables the check and displays missing rate/classification findings. Review the applicable government notification and obtain client/legal signoff before marking a schedule covered.

Official starting points: [EPFO](https://www.epfindia.gov.in/), [ESIC contribution](https://esic.gov.in/contribution), [ESIC coverage](https://esic.gov.in/coverage), [Chief Labour Commissioner minimum wages](https://clc.gov.in/clc/min-wages), plus each state's labour and local tax authority for PT, LWF and state minimum wages.
