"""
Rule packs: the built-in checks grouped by what they protect, with what each
needs to run.

A pack is a view over the coverage registry, not a second list of rules — a
check added to the engine and the registry appears in its pack without being
listed twice. Switching a pack off suppresses every check in it for this
company (the same per-rule suppression the matrix page sets, recorded as one
audit entry naming the pack, its checks and the reason), and a suppressed check
reports **Disabled** in every run, never Passed.

Packs also say where coverage stops. Bank and journal reconciliation are
checked on their own pages from their own files, so the pack says so rather
than implying validation covered them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models import Entity, TenantRulePreference, User, ValidationRun
from app.services import audit
from app.services.coverage import BY_ID, OUTCOMES, REGISTRY


@dataclass(frozen=True)
class Pack:
    key: str
    name: str
    purpose: str
    rule_ids: tuple[str, ...]
    #: Checks performed somewhere other than register validation.
    elsewhere: str | None = None


def _ids(prefixes: tuple[str, ...] = (), families: tuple[str, ...] = (), exact: tuple[str, ...] = ()) -> tuple[str, ...]:
    out = []
    for r in REGISTRY:
        if r.rule_id in exact or r.family in families or r.rule_id.startswith(prefixes):
            out.append(r.rule_id)
    return tuple(out)


PACKS: tuple[Pack, ...] = (
    Pack("import_integrity", "Import integrity",
         "The register is complete and internally consistent: IDs present and unique, no negative pay, identities not shared.",
         _ids(families=("Import integrity",))),
    Pack("configuration_integrity", "Configuration integrity",
         "Every employee maps to a PT and LWF state that has a dated schedule.",
         _ids(families=("Configuration integrity",))),
    Pack("employee_lifecycle", "Employee lifecycle and identity",
         "Paid only between joining and exit; PAN, Aadhaar, UAN, ESI number and IFSC present and well-formed.",
         _ids(families=("Employee lifecycle",))),
    Pack("salary_structure", "Salary structure and totals",
         "Gross and net add up; structures are not engineered to avoid PF.",
         _ids(families=("Salary structure",))),
    Pack("pf", "Provident Fund",
         "Employee and employer PF, EPS, the wage ceiling and restricted basis, international workers.",
         _ids(exact=("STAT-001", "STAT-002", "STAT-003", "STAT-004", "PF-004", "PF-008", "PF-009"))),
    Pack("esic", "ESIC",
         "Eligibility, employee and employer contributions, exempt daily wages, disability coverage.",
         _ids(exact=("STAT-005", "STAT-006", "STAT-007", "ESI-005", "ESI-006"))),
    Pack("pt_lwf", "Professional Tax and LWF",
         "PT by state slab and annual cap; LWF by state schedule.",
         _ids(exact=("STAT-008", "STAT-009", "STAT-010", "PT-002", "PT-003"))),
    Pack("tds", "Income tax (TDS)",
         "Sec 206AA rate without PAN, and monthly TDS against the projection.",
         _ids(exact=("STAT-011", "TDS-001", "TDS-002"))),
    Pack("minimum_wage", "Minimum wage",
         "Pay at or above the dated state rate for the employee's skill category.",
         _ids(prefixes=("MW-",))),
    Pack("bonus_gratuity", "Bonus and gratuity",
         "Statutory bonus band and eligibility; gratuity service, formula and cap.",
         _ids(exact=("BON-001", "BON-002", "STAT-014"), prefixes=("GRAT-",))),
    Pack("attendance", "Attendance",
         "Paid days and loss of pay agree with the attendance register and the calendar; overtime is paid as recorded.",
         _ids(families=("Attendance",))),
    Pack("arrears", "Arrears",
         "Arrear periods stated and valid; increment arrears match the CTC revision.",
         _ids(prefixes=("ARR-",), exact=("MOM-006",))),
    Pack("period_comparison", "Period comparison",
         "Joiners, spikes, drops, new and missing components against last month.",
         tuple(r for r in _ids(families=("Period comparison",)) if r != "MOM-006")),
    Pack("reconciliation", "Bank and ledger reconciliation",
         "Net pay reached the right accounts; the journal voucher balances and agrees with payroll cost.",
         (),
         elsewhere="Checked on Bank payments and Journal voucher from the bank file and the voucher, not during register validation."),
)
BY_KEY = {p.key: p for p in PACKS}


def required_inputs(pack: Pack) -> list[dict[str, Any]]:
    """What the pack's checks need, and how many checks each input unlocks."""
    needs: dict[str, list[str]] = {}
    for rid in pack.rule_ids:
        for label, _ in BY_ID[rid].requires:
            needs.setdefault(label, []).append(rid)
    return [{"input": label, "checks": rules} for label, rules in sorted(needs.items(), key=lambda kv: -len(kv[1]))]


def describe(db: Session, entity: Entity) -> list[dict[str, Any]]:
    suppressed = {
        rid for (rid,) in db.query(TenantRulePreference.rule_id).filter(
            TenantRulePreference.entity_id == entity.id, TenantRulePreference.suppressed.is_(True),
        )
    }
    latest = (
        db.query(ValidationRun)
        .filter(ValidationRun.entity_id == entity.id, ValidationRun.status == "current")
        .order_by(ValidationRun.period_month.desc())
        .first()
    )
    by_rule = {
        r["rule_id"]: r["counts"]
        for r in (((latest.summary or {}).get("coverage") or {}).get("rules") or [])
    } if latest else {}

    out = []
    for pack in PACKS:
        totals = dict.fromkeys(OUTCOMES, 0)
        for rid in pack.rule_ids:
            for outcome, n in (by_rule.get(rid) or {}).items():
                totals[outcome] = totals.get(outcome, 0) + n
        assessed = totals["passed"] + totals["failed"]
        applicable = assessed + totals["cannot_validate"]
        off = [rid for rid in pack.rule_ids if rid in suppressed]
        out.append({
            "key": pack.key,
            "name": pack.name,
            "purpose": pack.purpose,
            "elsewhere": pack.elsewhere,
            "checks": [
                {"rule_id": rid, "name": BY_ID[rid].name, "material": BY_ID[rid].material,
                 "enabled": rid not in suppressed, "runs_in_validation": BY_ID[rid].runs_in_validation,
                 "requires": [label for label, _ in BY_ID[rid].requires],
                 "last_run": by_rule.get(rid)}
                for rid in pack.rule_ids
            ],
            "required_inputs": required_inputs(pack),
            "state": "not_applicable" if not pack.rule_ids else (
                "off" if len(off) == len(pack.rule_ids) else "partial" if off else "on"
            ),
            "last_run": {
                "period_month": latest.period_month.isoformat(),
                "run_number": latest.run_number,
                "totals": totals,
                "coverage_pct": round(assessed * 100 / applicable, 1) if applicable else None,
            } if latest and by_rule and pack.rule_ids else None,
        })
    return out


def set_enabled(db: Session, entity: Entity, user: User, key: str, enabled: bool, reason: str) -> int:
    """Switch every check in a pack on or off; returns how many changed."""
    pack = BY_KEY.get(key)
    if pack is None or not pack.rule_ids:
        raise KeyError(key)
    existing = {
        p.rule_id: p for p in db.query(TenantRulePreference).filter(
            TenantRulePreference.entity_id == entity.id, TenantRulePreference.rule_id.in_(pack.rule_ids),
        )
    }
    changed = 0
    for rid in pack.rule_ids:
        pref = existing.get(rid)
        currently_off = bool(pref and pref.suppressed)
        if currently_off == (not enabled):
            continue
        if pref is None:
            pref = TenantRulePreference(user_id=user.id, entity_id=entity.id, rule_id=rid, suppressed=not enabled)
        else:
            pref.suppressed = not enabled
        db.add(pref)
        changed += 1
    audit.record(
        db, entity_id=entity.id, org_id=entity.org_id, user=user,
        action="rule_pack.enabled" if enabled else "rule_pack.disabled",
        object_type="rule_pack", object_id=key,
        summary=f"{'Enabled' if enabled else 'Disabled'} the {pack.name} pack ({changed} check(s) changed): {reason}",
        detail={"rule_ids": list(pack.rule_ids), "reason": reason},
    )
    db.flush()
    return changed
