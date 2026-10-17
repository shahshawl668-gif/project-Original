# Statutory rate audit (26 September 2026)

A bundled default is not evidence that a state rate is current. Review each official gazette/notification, its effective date, covered establishment/worker, wage basis, location/zone, contribution period, deduction month and supersession before marking it verified. Historical rates must remain queryable.

| Rule | State | Official text reviewed | Effective date | Existing default | Action | Status |
| --- | --- | --- | --- | --- | --- | --- |
| LWF | Karnataka | [Karnataka Act 05 of 2025, section 7A(2)](https://www.indiacode.nic.in/bitstream/123456789/7601/1/15_of_1965_%28e%29.pdf), Gazette 10 Jan 2025 | 10 Jan 2025 (commences at once) | ₹20 employee / ₹40 employer yearly | Current bundled rate ₹50 / ₹100 | Annual December deduction and January remittance verified against [section 7A of the Karnataka Act](https://www.indiacode.nic.in/bitstream/123456789/7601/1/15_of_1965_%28e%29.pdf); December validation, effective date and source implemented. Historical version and worker/establishment scope still need review |
| LWF | Maharashtra | [Maharashtra Act XXV of 2024, section 6BB(2)](https://bombayhighcourt.gov.in/bhc/libweb/legislation/acts/Stateact/2024acts/2024.25.pdf), Gazette 18 Mar 2024 | 18 Mar 2024 | ₹6/₹18 and ₹12/₹36 half-yearly bands | Current bundled rate ₹25 employee / ₹75 employer per six months; no wage band | Rate and June/December due-month validation implemented; historical versions must be supplied for older periods |
| PT | Karnataka | [2026 Amendment Act](https://gst.karnataka.gov.in/latestupdates/PTRules01426.pdf), effective 1 Apr 2026 | 1 Apr 2026 | Existing 2025 wage slabs | 2026 amendment changes enrolled-person return rules, not employee wage slabs | No rate change from this instrument; earlier and later rate notifications still require review |
| PT | Tamil Nadu local bodies | [Greater Chennai Corporation schedule](https://chennaicorporation.gov.in/gcc/department/revenue/) and [Coimbatore Corporation schedule](https://ccmc.gov.in/index.php/cat-department/revenue) | Chennai II/2024-25; Coimbatore 1 Oct 2018 page | One generic Tamil Nadu half-yearly table | Chennai and Coimbatore differ in middle bands; add local-body identity and effective-dated schedule before statewide use | Blocked by location model |
| LWF | Haryana | [Government press release quoting 8 May 2026 notification](https://prms.prharyana.gov.in/press-release/4736); primary notification still to obtain | Reported 2026, precise commencement requires notification | Fixed ₹31 / ₹62 monthly | 0.2% of wages capped at ₹35 employee; employer twice employee; model lacks percentage/cap | Pending primary notification and calculation model |
| LWF | Tamil Nadu | [Labour Department policy note 2025-26](https://labour.tn.gov.in/pdf/policy_note_lwsd_e_pn_2025_26.pdf) | 2025-26 publication | ₹20 / ₹40 annually | Figure agrees with policy note; worker coverage and any later notification still need review | Provisional |

## 17 October 2026 — checked against registers built from the law

A correct October 2026 register (six employees, payroll done right) came back with six critical findings and
₹4,320 of exposure, all false, while a register still deducting PF on the old ceiling passed. 1,317 tests were
green because they encoded the same assumptions as the engine. `backend/tests/test_law_scenarios.py` now holds
registers written from the sources below: clean employees must raise nothing above INFO, planted errors must be
caught. When a law changes, that file changes first.

| Rule | Source | Effective | Before | Now | Status |
| --- | --- | --- | --- | --- | --- |
| EPF/EPS/EDLI wage ceiling | S.O. 5109(E), 17 Sep 2026; EPS amended by G.S.R. 847(E), 25 Sep 2026 (as summarised by [SGCMS](https://www.sgcms.com/regulatory-updates/epfo-wage-ceiling-increased-from-15000-to-25000/)) | 17 Sep 2026 | ₹15,000 for every month | `services/statutory_calendar.py`: ₹15,000 to 16 Sep, ₹25,000 from 17 Sep; September 2026 split by days (1–16 / 17–30). Follows the law whenever configuration holds a statutory figure; any other figure is used as set | CONFIRMED from secondary summaries; obtain the gazette PDF for the file |
| EPS cap and new-entrant limit (PF-004) | As above; SGCMS summary: new entrants join EPS only on wages (Basic + DA) up to ₹25,000 | 17 Sep 2026 | ₹15,000 cap and joiner limit for every month | Cap follows the PF ceiling, September split by days (`rule_thresholds.pf_deep.eps_wage_cap`, default ₹25,000, follows the law when statutory). Post-2014 joiner limit is the ceiling in force on the joining date | CONFIRMED from secondary summary; gazette text of G.S.R. 847(E) still to obtain |
| PF administration charges | EPF scheme | — | 0.5% of wages capped at the ceiling | 0.5% of the wages contributions are paid on (uncapped for full-wage contributors); EDLI stays capped | CONFIRMED |
| ESIC coverage continuity | ESI Act s.2(9) proviso | — | Coverage decided on each month's wage alone | Coverage gained in a contribution period (Apr–Sep, Oct–Mar) lasts to its end. Proven from the employee's wages in the period's earlier stored months — never from what those registers deducted, so a wrong deduction cannot vouch for the next month. Missing months: an `esic_covered` column, else *cannot validate* (deducted or not). April/October: the month's own wage decides. A company eligibility rule (trainees excluded, say) still applies | CONFIRMED |
| TDS risk hint (STAT-011) | Tax-year configuration (87A rebate limit + standard deduction) | FY 2026-27 | ₹5 lakh for everyone | The employee's own regime's nil-tax limit (₹12.75 lakh new, ₹5.5 lakh old), capped by `tds.annual_income_threshold`; flagged with no TDS deducted, or with arrears in the month | CONFIRMED (figures from `tax_year_defaults.py`) |
| No-PAN TDS (TDS-001) | CBDT salary-TDS circular | — | 20% of taxable pay for every employee without a PAN | Only where tax is due at all (projection, or annualised taxable pay above `identity.no_pan_min_annual_income`, default ₹12.75 lakh) | CONFIRMED; section number to update for the Income-tax Act, 2025 |
| PT — Odisha top slab | [odishatax.gov.in rate chart](https://odishatax.gov.in/professional_tax.php) | current | ₹2,400 a year spread monthly | ₹200 a month and ₹300 in March (₹2,500 a year); companies holding the old bundled row get the March row at startup (`seed._add_odisha_march_pt`) | CONFIRMED (official site) |
| LWF due months | State schedules as tabulated by [Zoho Payroll](https://www.zoho.com/in/payroll/academy/taxes-and-compliance/guide-to-lwf.html) | current | Monthly equivalent everywhere except Maharashtra and Karnataka | June and December for half-yearly states, December for yearly states; rows without months fall back to the state's schedule | VERIFY against each state's Act |
| PT/LWF state selection | Product behaviour | — | Not checked at all unless the state was also ticked in settings, with no finding | Loaded schedules decide when no states are ticked; a PT/LWF state with no schedule is reported (*Schedule Not Loaded*); states recorded as levying no PT (`pt_defaults.NO_PT_STATES`) or no LWF (`lwf_defaults.NO_LWF_STATES`) are not applicable; any other state not in the catalog — Chandigarh, Tripura, a misspelling — is reported (*State Not Mapped*), never assumed to levy nothing | — |

An independent review of this change before it was merged found four errors the scenarios had missed — EPS still
capped at ₹15,000; an unconfirmable ESIC month passing when nothing was deducted; the register's own ESIC flag
trusted over the April/October rule; an LWF state missing from the catalog treated as levying nothing — and four
smaller ones. All are fixed, each with a scenario in `test_law_scenarios.py` that fails on the old code.

Disagreements found but **not** changed, because the secondary source may be the stale one: Odisha LWF (catalog
₹20/₹40 half-yearly, Zoho ₹10/₹20), Kerala LWF (catalog ₹50/₹50 monthly, Zoho ₹20/₹20). Both stay VERIFY.

## Open audit

- PT: all bundled states and local body schedules require official current schedule and supersession checks; there are 22 state entries in `pt_defaults.py`. City-specific taxes cannot be inferred from state names.
- LWF: other bundled states and statutory establishment/worker exclusions require official review; there are 15 state entries in `lwf_defaults.py`. The two corrected rates above do not prove all-state coverage.
- Minimum wages: there is no nationwide tenant rate seed. Appropriate-government schedules vary by employment, zone, skill and revision date. The [Chief Labour Commissioner minimum wages page](https://clc.gov.in/clc/min-wages) publishes central-sphere VDA orders; these cannot stand in for every state's schedules.
- The `slab_rules` PT/LWF table now accepts effective-from/effective-to dates and source references, and lookup selects the applicable version for the payroll period. Legacy undated rows still apply as fallback; importing defaults with overwrite or resetting can delete historical rows. Existing tenant imports are not automatically rewritten. The LWF validator applies contribution months as full deductions; every catalog state now carries its due months (status VERIFY, see 17 October 2026 above), and a tenant row without months falls back to its state's schedule. Historical versions remain unavailable.
- Do not run `reset-defaults` or `import-defaults/all?overwrite=true` as a compliance update until each state and historical version has been checked. Existing tenant imports are not automatically changed by edits to bundled defaults.

Two LWF current-rate corrections and the Maharashtra and Karnataka due-month checks are implemented in this audit. They do not make the complete product ready for release.
