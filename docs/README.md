# Architecture reference

`PayrollCheck-Architecture-Reference.docx` is the reference document for the
whole system: product framing, architecture, every database table and column,
every API endpoint, the rule catalogue, a module map, full source of the modules
that carry the product's logic, the test architecture, and the known limitations.

It is **generated**, not written by hand, so it cannot drift from the code. The
schema comes from the live ORM metadata, the endpoint table from the generated
OpenAPI spec, the module inventory from each file's own docstring, and the
source listings are read from the working tree at build time.

## Rebuilding

```bash
# 1. refresh the introspected inputs (needs the backend's Python environment)
./docs/data/regenerate.sh

# 2. build the document (needs the `docx` npm package)
cd frontend && npm install --no-save docx
node ../docs/build-architecture-doc.js
```

The document is written to `docs/PayrollCheck-Architecture-Reference.docx`.

## Which source is included in full

The listings in §7 cover the tenancy model and its migration, the four
ingestion paths, the register-versus-inputs rules, the findings lifecycle, the
analytics, minimum wage, and sign-off — about 3,800 lines.

The remaining modules are either pre-existing statutory engines
(`rule_engine_v2.py`, `validation.py`, the PF, ESIC and income-tax engines) or
presentation code. Every one of them is inventoried with its line count and
responsibility in §6; the source is in this repository.

Embedding all ~27,500 lines would run past 600 pages and stop being a reference.
