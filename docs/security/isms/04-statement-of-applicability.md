# 04 — Statement of Applicability (partial draft)

> **TEMPLATE — NOT APPROVED.** Drafted from the codebase on 30 September 2026. It is not a policy until the named approver signs it, and it is not evidence of an operating ISMS until the records it names exist. Text in _italics_ is for the business to decide.

**This is not a complete SoA.** ISO/IEC 27001:2022 Annex A has 93 controls.
This draft lists only those the control register (`../CONTROL_REGISTER.md`)
addresses, using control numbers and titles from the standard. The remainder
must be completed from the purchased text, each with an inclusion decision and
justification.

| Control | Applicable | Status (from evidence) | Register |
|---|---|---|---|
| 5.1 Policies for information security | Yes | Template only | GV-01 |
| 5.9 Inventory of information and other associated assets | Yes | Draft; SBOM implemented | GV-02, SD-03 |
| 5.15 Access control | Yes | Implemented — verified | AC-01, AC-03 |
| 5.17 Authentication information | Yes | Partial | AU-03, DS-01 |
| 5.18 Access rights | Yes | Implemented — verified (code); reviews not yet | AC-02 |
| 5.19 / 5.23 Suppliers; cloud services | Yes | Not implemented | GV-03 |
| 5.24–5.26 Incident management | Yes | Draft runbook | GV-04 |
| 5.28 Collection of evidence | Yes | Partial | LG-02 |
| 5.29 / 5.30 Disruption; ICT readiness | Yes | Not implemented for production | BC-01 |
| 5.31 Legal, statutory, regulatory and contractual requirements | Yes | Not implemented | GV-05 |
| 5.33 Protection of records | Yes | Partial | LG-02 |
| 5.34 Privacy and protection of PII | Yes | Partial | DS-03, GV-05 |
| 5.35 Independent review of information security | Yes | Not implemented | GV-06 |
| 6.3 Information security awareness, education and training | Yes | Not verifiable here | GV-07 |
| 8.2 Privileged access rights | Yes | Implemented — verified | AC-02 |
| 8.3 Information access restriction | Yes | Implemented — verified | AC-01 |
| 8.5 Secure authentication | Yes | Implemented — verified (capability) | AU-01, AU-04, AU-05 |
| 8.8 Management of technical vulnerabilities | Yes | Partial | SD-02 |
| 8.11 Data masking | Yes | Implemented — verified | AC-03 |
| 8.12 Data leakage prevention | Yes | Implemented — verified (exports) | EX-01 |
| 8.13 Information backup | Yes | Not implemented for production | BC-01 |
| 8.15 Logging / 8.16 Monitoring activities | Yes | Partial | LG-01 |
| 8.24 Use of cryptography | Yes | Implemented — verified | DS-01 |
| 8.25–8.29 Secure development and testing | Yes | Partial | SD-01 |
| 8.31 / 8.33 Environments; test information | Yes | Implemented for this work | SD-04 |
