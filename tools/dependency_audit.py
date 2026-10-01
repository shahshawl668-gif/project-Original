"""
Fail on any known-vulnerable dependency that nobody has assessed.

    pip-audit -r backend/requirements-postgres.txt -f json -o pip-audit.json
    (cd frontend && npm audit --omit=dev --json > ../npm-audit.json)
    python tools/dependency_audit.py pip-audit.json npm-audit.json

Every advisory either appears in security/dependency-exceptions.json — with
its assessment and a review date — or fails the build. An exception past its
``review_by`` date fails too: "we looked at this once" is not an assessment
that lasts forever. The script reads the scanners' JSON; it does not decide
what is exploitable. People do, in the exceptions file.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCEPTIONS = ROOT / "security" / "dependency-exceptions.json"


def _pip(report: dict) -> list[tuple[str, str, set[str]]]:
    found = []
    for dep in report.get("dependencies", []):
        for v in dep.get("vulns", []):
            found.append((dep["name"], v["id"], {v["id"], *v.get("aliases", [])}))
    return found


def _npm(report: dict) -> list[tuple[str, str, set[str]]]:
    found = []
    for name, vuln in (report.get("vulnerabilities") or {}).items():
        for via in vuln.get("via", []):
            if isinstance(via, dict) and via.get("url"):
                ghsa = via["url"].rstrip("/").split("/")[-1]
                found.append((name, ghsa, {ghsa}))
    return found


def main(paths: list[str]) -> int:
    doc = json.loads(EXCEPTIONS.read_text())
    known: dict[str, dict] = {}
    for e in doc["exceptions"]:
        for ident in (e["id"], *e.get("aliases", [])):
            known[ident] = e
    today = date.today()
    unassessed, expired, seen = [], [], 0
    for path in paths:
        report = json.loads(Path(path).read_text() or "{}")
        for package, ident, ids in (_npm(report) if "vulnerabilities" in report or "auditReportVersion" in report
                                    else _pip(report)):
            seen += 1
            match = next((known[i] for i in ids if i in known), None)
            if match is None:
                unassessed.append(f"{package}: {ident}")
            elif date.fromisoformat(match["review_by"]) < today:
                expired.append(f"{package}: {ident} (review was due {match['review_by']})")
    print(f"{seen} advisories reported; {len(unassessed)} unassessed; {len(expired)} past review.")
    for line in unassessed:
        print(f"UNASSESSED  {line}")
    for line in expired:
        print(f"EXPIRED     {line}")
    if unassessed or expired:
        print(f"Assess each in {EXCEPTIONS.relative_to(ROOT)} (or upgrade), with the reason in the commit.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
