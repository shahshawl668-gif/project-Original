#!/usr/bin/env bash
# Regenerate the inputs the architecture document is built from.
#
# These are derived from the live application rather than maintained by hand, so
# the document cannot drift from the code: the schema comes from the ORM
# metadata, the endpoint list from the generated OpenAPI spec, and the module
# inventory from each file's own docstring.
set -euo pipefail
cd "$(dirname "$0")/../.."
HERE="docs/data"

export DATABASE_URL="sqlite:///$(mktemp -d)/introspect.db"
export JWT_SECRET="introspection-only"

# --- database schema -------------------------------------------------------
(cd backend && python - <<'PY' > "../$HERE/schema.json"
import warnings, json; warnings.filterwarnings("ignore")
import app.models  # registers every table on Base.metadata
from app.database import Base

GROUPS = {
    "Tenancy": ["organizations", "entities", "org_memberships", "entity_access"],
    "Identity": ["users", "refresh_tokens", "password_reset_tokens"],
    "Configuration": ["components_config", "statutory_settings", "statutory_config",
                      "rule_formulas", "slab_rules", "tenant_rule_preferences",
                      "pt_slabs", "lwf_rates", "minimum_wage_rates"],
    "Payroll inputs": ["salary_registers", "salary_register_rows", "ctc_uploads", "ctc_records",
                       "employee_master_uploads", "employee_records",
                       "attendance_registers", "attendance_rows", "payroll_runs"],
    "Findings & assurance": ["validation_runs", "finding_records", "finding_states",
                             "finding_state_events", "period_signoffs", "signoff_events"],
}
out = {}
for name, t in Base.metadata.tables.items():
    cols = []
    for c in t.columns:
        f = []
        if c.primary_key: f.append("PK")
        if c.foreign_keys: f.append("FK → " + list(c.foreign_keys)[0].target_fullname)
        if not c.nullable and not c.primary_key: f.append("NOT NULL")
        if c.index: f.append("indexed")
        cols.append({"name": c.name, "type": str(c.type), "flags": ", ".join(f)})
    uq = ["UNIQUE (" + ", ".join(x.columns.keys()) + ")"
          for x in t.constraints if x.__class__.__name__ == "UniqueConstraint"]
    grp = next((g for g, ts in GROUPS.items() if name in ts), "Other")
    out[name] = {"group": grp, "columns": cols, "unique": uq}
print(json.dumps(out, indent=1))
PY
)

# --- endpoints -------------------------------------------------------------
(cd backend && python - <<'PY' > "../$HERE/api.tsv"
import warnings; warnings.filterwarnings("ignore")
from app.main import app
rows = []
for path, ops in app.openapi()["paths"].items():
    if path.startswith("/api/v1"):
        continue  # versioned alias of the same routes
    for method, op in ops.items():
        rows.append((
            (op.get("tags") or ["-"])[0],
            path,
            method.upper(),
            (op.get("summary") or "").strip(),
            (op.get("description") or "").strip().split("\n")[0],
        ))
for r in sorted(rows):
    print("\t".join(r))
PY
)

# --- module inventories ----------------------------------------------------
for f in $(find backend/app -name "*.py" | sort); do
  n=$(wc -l < "$f")
  d=$(python3 -c "
import ast
try:
    m = ast.parse(open('$f').read()); d = ast.get_docstring(m)
    print((d or '').strip().split('\n')[0][:95] if d else '')
except Exception:
    print('')
")
  printf "%-46s %5s  %s\n" "$f" "$n" "$d"
done > "$HERE/inventory.txt"

for f in $(find frontend/src -type f \( -name "*.tsx" -o -name "*.ts" \) | sort); do
  printf "%-58s %5s\n" "$f" "$(wc -l < "$f")"
done > "$HERE/fe.txt"

echo "Regenerated $HERE/{schema.json,api.tsv,inventory.txt,fe.txt}"
