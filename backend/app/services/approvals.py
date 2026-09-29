"""
Maker–checker controls and month readiness.

Two questions every approval must answer, and that the product used to leave
to trust:

**Is there anything to approve?** A month with no validation run, a run older
than its inputs, or a run whose material checks could not execute is not
"ready" — it is unexamined. Approving it would put a signature on a record
that says nothing was checked. ``readiness`` lists what stands in the way;
submit and sign refuse while anything does, and the month status shows it.

**Is the approver independent?** When the organisation requires it, the person
who prepared a month cannot approve it, and the person who drafted a rule
cannot publish it. The policy is the owner's decision, recorded in the audit
trail, and captured in every sign-off snapshot so the record says whether the
approval was independent.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models import Entity, Organization, ValidationRun
from app.services import run_inputs
from app.services.finding_store import current_run

#: Defaults are permissive so a one-person practice can still close a month;
#: the owner turns independence on, and every snapshot records which applied.
DEFAULT_POLICY: dict[str, bool] = {
    "signoff_requires_independent_approver": False,
    "matrix_publish_requires_independent_approver": False,
    "studio_publish_requires_independent_approver": False,
}


class ApprovalRefused(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def policy_for(db: Session, org_id: Any) -> dict[str, bool]:
    org = db.get(Organization, org_id)
    stored = (getattr(org, "approval_policy", None) or {}) if org else {}
    return {key: bool(stored.get(key, default)) for key, default in DEFAULT_POLICY.items()}


def set_policy(db: Session, org: Organization, updates: dict[str, bool]) -> dict[str, bool]:
    current = policy_for(db, org.id)
    for key, value in updates.items():
        if key not in DEFAULT_POLICY:
            raise ValueError(f"Unknown approval setting: {key}")
        current[key] = bool(value)
    org.approval_policy = current
    db.add(org)
    db.flush()
    return current


def require_independent(
    db: Session, org_id: Any, setting: str, *, preparer_id: Any, approver_id: Any, what: str
) -> None:
    """Refuse self-approval where the organisation requires independence."""
    if policy_for(db, org_id).get(setting) and preparer_id is not None and preparer_id == approver_id:
        raise ApprovalRefused(
            f"Your organisation requires {what} to be approved by someone other than the person who "
            "prepared it. Ask another owner or manager to approve.",
            "independent_approval_required",
        )


def readiness(db: Session, entity: Entity, period_month: date) -> dict[str, Any]:
    """What stands between this month and approval.

    Each blocker says what to do. ``acceptable`` blockers may be accepted with
    a stated reason (recorded in the snapshot); the others must be fixed.
    """
    period_month = period_month.replace(day=1)
    run: ValidationRun | None = current_run(db, entity.id, period_month)
    blockers: list[dict[str, Any]] = []
    fresh = None
    coverage = None
    if run is None:
        blockers.append({
            "code": "not_validated",
            "message": "This month has not been validated. Upload the register and validate it first.",
            "acceptable": False,
        })
    else:
        fresh = run_inputs.run_freshness(db, entity, run)
        if fresh["revalidation_required"]:
            blockers.append({
                "code": "revalidation_required",
                "message": "Inputs changed since the last validation: "
                + "; ".join(c["label"] for c in fresh["changes"])
                + ". Revalidate before approving.",
                "acceptable": False,
            })
        coverage = (run.summary or {}).get("coverage")
        material = (coverage or {}).get("material_cannot_validate") or 0
        if material:
            blockers.append({
                "code": "incomplete_coverage",
                "message": (
                    f"{material} statutory check(s) could not be performed for want of an input "
                    "(see coverage). Supply the inputs and revalidate, or approve stating why "
                    "the gap is acceptable."
                ),
                "acceptable": True,
            })
    return {
        "period_month": period_month.isoformat(),
        "ready": not blockers,
        "blockers": blockers,
        "run_id": str(run.id) if run else None,
        "run_number": run.run_number if run else None,
        "freshness": fresh,
        "coverage": {
            "coverage_pct": (coverage or {}).get("coverage_pct"),
            "material_cannot_validate": (coverage or {}).get("material_cannot_validate"),
            "totals": (coverage or {}).get("totals"),
        } if coverage else None,
    }


def assert_ready(
    db: Session, entity: Entity, period_month: date, accept_incomplete_reason: str | None
) -> dict[str, Any]:
    state = readiness(db, entity, period_month)
    hard = [b for b in state["blockers"] if not b["acceptable"]]
    if hard:
        raise ApprovalRefused(hard[0]["message"], hard[0]["code"])
    soft = [b for b in state["blockers"] if b["acceptable"]]
    if soft and not (accept_incomplete_reason or "").strip():
        raise ApprovalRefused(soft[0]["message"], soft[0]["code"])
    state["accepted_gaps"] = (
        {"reason": accept_incomplete_reason.strip(), "blockers": soft} if soft else None
    )
    return state
