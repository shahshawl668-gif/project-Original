# 08 — Supplier register

> **TEMPLATE — NOT APPROVED.** Drafted from the codebase on 30 September 2026. It is not a policy until the named approver signs it, and it is not evidence of an operating ISMS until the records it names exist. Text in _italics_ is for the business to decide.

| Supplier | Service | Data it holds | Assurance to obtain | Contract / DPA | Reviewed |
|---|---|---|---|---|---|
| Render | Hosting: web, API, PostgreSQL (Singapore region) | All client payroll data, logs, secrets | _Their security documentation / audit reports_ | _to locate_ | _date_ |
| GitHub | Source, CI, Dependabot | Source code; no client data | _Their security documentation_ | _to locate_ | _date_ |
| GoDaddy | Domain registrar for peopleopslab.in, and its DNS unless the nameservers point elsewhere (_confirm_) | None, but controls where users are sent | Account security: two-step verification on, transfer lock on, _named owner_ | GoDaddy's standard terms (_confirm the account holder_) | _date_ |

GoDaddy never receives client data, so it is not a sub-processor; it is on
this register because control of the domain is control of where users sign in.
Other hosting accounts the business holds, such as Hostinger, have no part in
this product and are not listed.

Sub-processor list for clients: Render (hosting, Singapore). _Confirm with
counsel what clients must be told and when this list changes._
