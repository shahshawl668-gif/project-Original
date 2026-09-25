"""Fail when the handbook stops describing the code.

Documentation rots quietly. A route gets added, an environment variable gets
renamed, and the handbook keeps saying the old thing until someone acts on it
and is wrong. Nobody notices, because nothing checks.

This checks. It reads the facts out of the codebase — the pages that exist, the
admin endpoints, the settings the API reads, the health endpoints — and asserts
that docs/handbook.html still names the same ones. Drift in either direction is
an error: a route missing from the handbook is undocumented, and a route the
handbook names that no longer exists sends someone to a 404.

    python docs/tools/check_docs_current.py

Exits non-zero with a list of what moved, so CI can hold the line rather than
relying on anyone remembering.

It deliberately does not check prose. Whether an explanation is still *true* is
a judgement no script makes; whether it still names the right things is not.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent
REPO = DOCS.parent
HANDBOOK = DOCS / "handbook.html"

#: Routes that exist but are intentionally absent from the route table: they
#: are reached through another page rather than typed, or they are a redirect.
ROUTE_EXEMPT: set[str] = set()

#: Settings that exist but are not worth a reader's attention — internal knobs
#: with no operational meaning.
ENV_EXEMPT = {
    "env_file", "env_file_encoding", "extra", "case_sensitive",
    "jwt_algorithm", "access_token_expire_minutes", "refresh_token_expire_days",
    "cors_origin_regex",
}


def frontend_routes() -> set[str]:
    """Every page the Next.js app serves, as a URL path."""
    app = REPO / "frontend" / "src" / "app"
    routes = set()
    for page in app.rglob("page.tsx"):
        rel = page.relative_to(app).parent
        parts = [p for p in rel.parts if not (p.startswith("(") and p.endswith(")"))]
        path = "/" + "/".join(parts)
        routes.add("/" if path == "/" else path)
    # The API relay is not a page.
    return {r for r in routes if not r.startswith("/api")}


def admin_endpoints() -> set[str]:
    """Method and path for everything under /api/admin."""
    src = (REPO / "backend" / "app" / "routers" / "admin.py").read_text()
    out = set()
    for method, path in re.findall(r'@router\.(get|post|put|patch|delete)\("([^"]*)"\)', src):
        out.add(f"{method.upper()} /api/admin{path}")
    return out


def settings_fields() -> set[str]:
    """Every environment variable app/config.py reads."""
    src = (REPO / "backend" / "app" / "config.py").read_text()
    body = src.split("class Settings", 1)[1].split("\n    # ------", 1)[0]
    fields = set(re.findall(r"^\s{4}([a-z_]+):\s", body, flags=re.M))
    return {f for f in fields if f not in ENV_EXEMPT}


def handbook_text() -> str:
    if not HANDBOOK.is_file():
        sys.exit(f"{HANDBOOK} is missing — the handbook is part of the repo, not a copy elsewhere.")
    return HANDBOOK.read_text()


def check() -> list[str]:
    html = handbook_text()
    problems: list[str] = []

    # --- routes ----------------------------------------------------------
    # Scope to the routes section: the health-endpoint table further down uses
    # the same markup, and counting those as pages produced three phantom
    # "route no longer exists" errors on the first run.
    section = re.search(r'<section id="routes">(.*?)</section>', html, flags=re.S)
    if section is None:
        return ['the handbook has no <section id="routes"> to check against']
    documented = set(re.findall(r'<td class="mono">(/[a-z0-9\[\]/._-]*)</td>',
                                section.group(1)))
    actual = frontend_routes() - ROUTE_EXEMPT
    for missing in sorted(actual - documented):
        problems.append(f"route {missing} exists but the handbook's route table does not list it")
    for stale in sorted(documented - actual):
        problems.append(f"the handbook lists route {stale}, which no longer exists")

    # --- admin endpoints --------------------------------------------------
    for endpoint in sorted(admin_endpoints()):
        method, path = endpoint.split(" ", 1)
        if path not in html:
            problems.append(f"admin endpoint {endpoint} is not in the handbook")

    # --- environment variables -------------------------------------------
    for field in sorted(settings_fields()):
        if field.upper() not in html:
            problems.append(
                f"config.py reads {field.upper()} but the handbook does not mention it")

    # --- health endpoints -------------------------------------------------
    main = (REPO / "backend" / "app" / "main.py").read_text()
    for path in sorted(set(re.findall(r'@app\.get\("(/[a-z0-9/]*health)"', main))):
        if f"<td class=\"mono\">{path}</td>" not in html:
            problems.append(f"health endpoint {path} is not in the handbook")

    # --- organisation roles ------------------------------------------------
    for role in ("owner", "manager", "analyst", "viewer"):
        if f"<td>{role}</td>" not in html:
            problems.append(f"role '{role}' is missing from the handbook's role table")

    return problems


if __name__ == "__main__":
    found = check()
    if found:
        print("The handbook no longer describes the code:\n")
        for p in found:
            print(f"  - {p}")
        print(f"\n{len(found)} problem(s). Update docs/handbook.html, then re-run this.")
        sys.exit(1)
    print("docs/handbook.html matches the code: routes, admin endpoints, "
          "settings, health endpoints and roles all agree.")
