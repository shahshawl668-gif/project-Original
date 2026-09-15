# Architecture reference

`PayrollCheck-Architecture-Reference.docx` is the reference document for the
whole system: product framing, architecture, every database table and column,
every API endpoint, the rule catalogue, a module map, full source of the modules
that carry the product's logic, the test architecture, and the known limitations.

## Rebuilding

```bash
cd docs
npm install          # once
npm run build        # regenerate inputs, build, validate
```

`npm run build:only` skips regeneration when the code has not changed;
`npm run validate` checks an already-built document.

Regeneration needs the backend's Python environment on the path, because the
schema and endpoint list come from the live application rather than a parsed
copy of it. If it is not active, the script says so and stops. Point it
elsewhere with `PYTHON=/path/to/python npm run build`.

## Why the figures can be trusted

Nothing the document asserts about the codebase is typed by hand:

| In the document | Derived from |
|---|---|
| Schema, every column and constraint | live SQLAlchemy metadata |
| Endpoint table | the generated OpenAPI spec |
| Rule catalogue | rule identifiers scanned from the service source |
| Test inventory and counts | `pytest --collect-only` |
| Module map, line counts | the files themselves, and their docstrings |
| Cover provenance and all totals | `git`, and the inputs above |
| Source listings | read from the working tree at build time |

Prose — what a rule family checks, what a suite pins down, the architecture
narrative, the limitations — is written by hand, because that is judgement
rather than fact.

### Four guards, so the document cannot quietly go wrong

A generated document that is merely *out of date* is a nuisance. One that is
**confidently wrong** is worse than none, so each of these fails the build
rather than rendering something plausible:

1. **Stale inputs.** A digest of `backend/app` and `frontend/src` is recorded
   when the inputs are generated and recomputed at build time. If the source has
   moved, the build stops and tells you to regenerate.
2. **An unclassified table.** A new table with no group in `regenerate.sh` fails,
   rather than being filed under a catch-all nobody reads.
3. **An undocumented rule family.** A rule id in the source with no entry in
   `RULE_FAMILIES` fails — this is what stops a new rule from silently vanishing
   from the catalogue. A description for a family no longer in the source fails
   too.
4. **An undocumented test suite.** A suite pytest collects with no entry in
   `SUITE_NOTES` fails, rather than appearing as a blank row.

`validate-doc.js` then checks the built file: that it is a well-formed OOXML
package, that every embedded listing is present from first line to last, and
that the cover's figures match the inputs.

The build is deterministic — timestamps are pinned to the commit date — so
rebuilding without a code change produces an identical file and no git diff.

## Which source is included in full

Section 7 embeds the tenancy model and its migration, the four ingestion paths,
the register-versus-inputs rules, the findings lifecycle, the analytics, minimum
wage, and sign-off — about 3,800 lines. The file list is `LISTINGS` in
`build-architecture-doc.js`; a path that no longer exists fails the build by
name rather than throwing a bare `ENOENT`.

Everything else is either a pre-existing statutory engine (`rule_engine_v2.py`,
`validation.py`, the PF, ESIC and income-tax engines) or presentation code. Each
is inventoried in section 6 with its line count and responsibility. Embedding all
~27,500 lines would run past 600 pages and stop being a reference.
