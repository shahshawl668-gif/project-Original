#!/usr/bin/env bash
#
# Regenerate everything the architecture document is built from.
#
# The document asserts facts about this codebase, so every one of those facts is
# derived here rather than typed by hand: the schema from live ORM metadata, the
# endpoint list from the generated OpenAPI spec, the module inventory from each
# file's own docstring, the rule catalogue from the rule ids in the source, and
# the test inventory from pytest's own collection.
#
# A fingerprint of the source tree is recorded alongside. The builder compares it
# against the tree it is building from and refuses to run if they differ, so a
# document can never be produced from stale inputs.
#
# Usage:  ./docs/data/regenerate.sh          (from anywhere)
#
set -euo pipefail

cd "$(dirname "$0")/../.."
HERE="docs/data"
PY="${PYTHON:-python3}"

# The backend's dependencies must be importable — the schema and endpoint lists
# come from the live application, not from a parsed copy of it.
if ! (cd backend && "$PY" -c "import fastapi, sqlalchemy" 2>/dev/null); then
  echo "error: the backend's Python environment is not active." >&2
  echo "       activate it, or set PYTHON=/path/to/python, then re-run." >&2
  echo "       e.g.  cd backend && python -m venv .venv && . .venv/bin/activate" >&2
  echo "             pip install -r requirements.txt" >&2
  exit 1
fi

TMPDB="$(mktemp -d)/introspect.db"
export DATABASE_URL="sqlite:///$TMPDB"
export JWT_SECRET="introspection-only-never-used-to-sign-anything"
trap 'rm -f "$TMPDB"' EXIT

echo "→ schema"
(cd backend && "$PY" - <<'PY' > "../$HERE/schema.json"
import warnings, json; warnings.filterwarnings("ignore")
import app.models  # importing the package registers every table on Base.metadata
from app.database import Base

# Tables are grouped for the reader's benefit. A table missing from this map is
# reported by the builder rather than silently filed under "Other" — a new table
# nobody classified is a documentation gap, not a rendering detail.
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
    out[name] = {
        "group": next((g for g, ts in GROUPS.items() if name in ts), None),
        "columns": cols,
        "unique": uq,
    }
print(json.dumps(out, indent=1, sort_keys=True))
PY
)

echo "→ endpoints"
(cd backend && "$PY" - <<'PY' > "../$HERE/api.tsv"
import warnings; warnings.filterwarnings("ignore")
from app.main import app
rows = []
for path, ops in app.openapi()["paths"].items():
    if path.startswith("/api/v1"):
        continue  # a versioned alias of the same routes; listing both doubles the table
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

echo "→ rule catalogue"
(cd backend && "$PY" - <<'PY' > "../$HERE/rules.json"
import json, pathlib, re
from collections import defaultdict

# Rule ids are declared as string literals at the point a finding is raised, so
# scanning the source is the only reading that cannot drift from what the engine
# actually emits.
PATTERN = re.compile(r'"([A-Z]{2,6})-(\d{3})"')
found = defaultdict(set)
for path in sorted(pathlib.Path("app/services").rglob("*.py")):
    for family, number in PATTERN.findall(path.read_text()):
        found[family].add(number)

print(json.dumps(
    {f: sorted(n) for f, n in sorted(found.items())},
    indent=1,
))
PY
)

echo "→ test inventory"
(cd backend && "$PY" - <<'PY' > "../$HERE/tests.json"
import json, subprocess, sys
from collections import Counter

# pytest's own collection, so the counts cannot disagree with what runs.
proc = subprocess.run(
    [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q", "--no-header"],
    capture_output=True, text=True,
)
if proc.returncode not in (0, 5):
    sys.stderr.write(proc.stdout + proc.stderr)
    sys.stderr.write("\nerror: pytest collection failed; fix the suite before regenerating\n")
    sys.exit(1)

counts = Counter()
for line in proc.stdout.splitlines():
    if "::" in line and line.startswith("tests/"):
        counts[line.split("::")[0].replace("tests/", "")] += 1

print(json.dumps({"suites": dict(sorted(counts.items())), "total": sum(counts.values())}, indent=1))
PY
)

echo "→ module inventory"
for f in $(find backend/app -name "*.py" -not -path "*/__pycache__/*" | sort); do
  n=$(wc -l < "$f")
  d=$("$PY" -c "
import ast
try:
    m = ast.parse(open('$f').read()); d = ast.get_docstring(m)
    print((d or '').strip().split('\n')[0][:95] if d else '')
except Exception:
    print('')
")
  printf "%s\t%s\t%s\n" "$f" "$n" "$d"
done > "$HERE/inventory.tsv"

for f in $(find frontend/src -type f \( -name "*.tsx" -o -name "*.ts" \) | sort); do
  printf "%s\t%s\n" "$f" "$(wc -l < "$f")"
done > "$HERE/frontend.tsv"

echo "→ provenance"
"$PY" - <<PY > "$HERE/meta.json"
import json, subprocess, hashlib, pathlib

def git(*args, default=""):
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return default

# A digest of the sources these inputs were derived from. The builder recomputes
# it and refuses to build if it has moved, which is what makes stale data
# impossible rather than merely unlikely.
# One flat, sorted list of repo-relative paths — the builder recomputes this
# with the same recipe, so the two must agree on ordering exactly. Grouping by
# extension here would silently diverge from a single sort there.
paths = []
for root, exts in (("backend/app", (".py",)), ("frontend/src", (".ts", ".tsx"))):
    for path in pathlib.Path(root).rglob("*"):
        if not path.is_file() or path.suffix not in exts:
            continue
        if "__pycache__" in path.parts:
            continue
        paths.append(path.as_posix())

digest = hashlib.sha256()
for rel in sorted(paths):
    digest.update(rel.encode())
    digest.update(pathlib.Path(rel).read_bytes())

remote = git("config", "--get", "remote.origin.url")
slug = remote.replace("https://github.com/", "").replace("git@github.com:", "").removesuffix(".git")

print(json.dumps({
    "repository": slug or "(no remote configured)",
    "branch": git("rev-parse", "--abbrev-ref", "HEAD", default="(detached)"),
    "commit": git("rev-parse", "--short", "HEAD", default="(uncommitted)"),
    "commit_full": git("rev-parse", "HEAD"),
    "commit_date": git("log", "-1", "--format=%cI"),
    "dirty": bool(git("status", "--porcelain")),
    "source_digest": digest.hexdigest(),
}, indent=1))
PY

echo
echo "Regenerated in $HERE:"
echo "  schema.json  api.tsv  rules.json  tests.json  inventory.tsv  frontend.tsv  meta.json"
if "$PY" -c "import json,sys; sys.exit(0 if json.load(open('$HERE/meta.json'))['dirty'] else 1)"; then
  echo
  echo "note: the working tree has uncommitted changes, so the document will be"
  echo "      marked as built from a modified tree."
fi
