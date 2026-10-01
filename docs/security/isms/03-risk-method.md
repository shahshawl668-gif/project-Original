# 03 — Risk assessment and treatment method

> **TEMPLATE — NOT APPROVED.** Drafted from the codebase on 30 September 2026. It is not a policy until the named approver signs it, and it is not evidence of an operating ISMS until the records it names exist. Text in _italics_ is for the business to decide.

- **Identify** risks per asset and trust boundary (`../../SECURITY.md` §2–4).
- **Rate** likelihood (1 rare – 5 almost certain) × impact (1 minor – 5 severe:
  cross-client exposure of personal data is always 5). Score ≥ 15 is
  unacceptable without treatment; 8–14 needs an owner and a date; ≤ 7 may be accepted.
- **Treat** by modify / avoid / share / accept. Acceptance is recorded with
  the name of the risk owner, the reason and a review date — the same shape as
  `security/dependency-exceptions.json`, which CI already enforces for
  dependency risks.
- **Register:** `../../SECURITY.md` §9 is the current register. _Move it to a
  controlled record once approved._
- **Records kept:** risk register versions, acceptance decisions, incident
  records, restore-drill records (`../../evidence/`), access reviews, training.
- **Frequency:** quarterly, and after any incident or significant change.
