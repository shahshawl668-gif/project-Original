# Statutory rate audit (26 September 2026)

A bundled default is not evidence that a state rate is current. Review each official gazette/notification, its effective date, covered establishment/worker, wage basis, location/zone, contribution period, deduction month and supersession before marking it verified. Historical rates must remain queryable.

| Rule | State | Official text reviewed | Effective date | Existing default | Action | Status |
| --- | --- | --- | --- | --- | --- | --- |
| LWF | Karnataka | [Karnataka Act 05 of 2025, section 7A(2)](https://www.indiacode.nic.in/bitstream/123456789/7601/1/15_of_1965_%28e%29.pdf), Gazette 10 Jan 2025 | 10 Jan 2025 (commences at once) | ₹20 employee / ₹40 employer yearly | Current bundled rate ₹50 / ₹100 | Rate checked; deduction timing and historical version still need implementation |
| LWF | Maharashtra | [Maharashtra Act XXV of 2024, section 6BB(2)](https://bombayhighcourt.gov.in/bhc/libweb/legislation/acts/Stateact/2024acts/2024.25.pdf), Gazette 18 Mar 2024 | 18 Mar 2024 | ₹6/₹18 and ₹12/₹36 half-yearly bands | Current bundled rate ₹25 employee / ₹75 employer per six months; no wage band | Rate checked; June/December event logic and historical version still need implementation |
| PT | Karnataka | [2026 Amendment Act](https://gst.karnataka.gov.in/latestupdates/PTRules01426.pdf), effective 1 Apr 2026 | 1 Apr 2026 | Existing 2025 wage slabs | 2026 amendment changes enrolled-person return rules, not employee wage slabs | No rate change from this instrument; earlier and later rate notifications still require review |

| PT | Tamil Nadu local bodies | [Greater Chennai Corporation schedule](https://chennaicorporation.gov.in/gcc/department/revenue/) and [Coimbatore Corporation schedule](https://ccmc.gov.in/index.php/cat-department/revenue) | Chennai II/2024-25; Coimbatore 1 Oct 2018 page | One generic Tamil Nadu half-yearly table | Chennai and Coimbatore differ in middle bands; add local-body identity and effective-dated schedule before statewide use | Blocked by location model |
| LWF | Haryana | [Government press release quoting 8 May 2026 notification](https://prms.prharyana.gov.in/press-release/4736); primary notification still to obtain | Reported 2026, precise commencement requires notification | Fixed ₹31 / ₹62 monthly | 0.2% of wages capped at ₹35 employee; employer twice employee; model lacks percentage/cap | Pending primary notification and calculation model |
| LWF | Tamil Nadu | [Labour Department policy note 2025-26](https://labour.tn.gov.in/pdf/policy_note_lwsd_e_pn_2025_26.pdf) | 2025-26 publication | ₹20 / ₹40 annually | Figure agrees with policy note; worker coverage and any later notification still need review | Provisional |

## Open audit

- PT: all bundled states and local body schedules require official current schedule and supersession checks; there are 22 state entries in `pt_defaults.py`. City-specific taxes cannot be inferred from state names.
- LWF: other bundled states and statutory establishment/worker exclusions require official review; there are 15 state entries in `lwf_defaults.py`. The two corrected rates above do not prove all-state coverage.
- Minimum wages: there is no nationwide tenant rate seed. Appropriate-government schedules vary by employment, zone, skill and revision date. The [Chief Labour Commissioner minimum wages page](https://clc.gov.in/clc/min-wages) publishes central-sphere VDA orders; these cannot stand in for every state's schedules.
- The `slab_rules` PT/LWF table lacks effective-from/effective-to dates and source references. A default import overwrites a tenant's state rows, so updated defaults alone cannot safely validate an older payroll period. The LWF validator currently prorates annual/half-yearly contributions to a monthly equivalent; it needs deduction-period rules for exact register comparison.
- Do not run `reset-defaults` or `import-defaults/all?overwrite=true` as a compliance update until each state and historical version has been checked. Existing tenant imports are not automatically changed by edits to bundled defaults.

Only the two LWF current-rate corrections are implemented in this audit. They do not make the complete product ready for release.
