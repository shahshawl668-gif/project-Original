"""Company validation rule drafts, simulation and approval."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, require_entity_admin
from app.envelope import ok
from app.models import ComponentConfig, Entity, SalaryRegister, SalaryRegisterRow, User, ValidationRuleVersion
from app.schemas.validation_matrix import RuleCreate, SimulationRequest
from app.services import audit, tenancy, validation_matrix
from app.services.validation_catalog import BUILTIN_RULES, rule_family
from app.services.payroll_parse import normalize_col

router = APIRouter()

BUILTIN_CATALOG = [
    {"family": "Payroll integrity", "examples": ["Gross and net reconciliation", "Duplicate employee", "Missing mandatory data", "Arrears and LOP"]},
    {"family": "Statutory", "examples": ["PF", "ESIC", "PT", "LWF", "TDS", "Minimum wage"]},
    {"family": "Cross-register", "examples": ["Attendance versus payroll", "Employee master", "Prior period variance"]},
]
TEMPLATES = [
    {"key": "amount_comparison", "label": "Compare two amounts", "description": "Compare a mapped component, deduction or field against a value or another field."},
    {"key": "required_value", "label": "Required value", "description": "Flag missing mapped inputs rather than silently passing."},
    {"key": "conditional_check", "label": "Conditional check", "description": "Run a comparison only when an optional condition matches."},
    {"key": "required_input", "label": "Mandatory payroll input", "description": "Flag a missing mapped field such as bank account, IFSC, work state or PAN."},
    {"key": "allowed_values", "label": "Allowed values", "description": "Check a field against a company-approved list separated by |."},
]


def _out(rule: ValidationRuleVersion) -> dict:
    return {
        "id": str(rule.id), "rule_key": rule.rule_key, "version": rule.version,
        "name": rule.name, "category": rule.category, "status": rule.status,
        "effective_from": rule.effective_from.isoformat(),
        "effective_to": rule.effective_to.isoformat() if rule.effective_to else None,
        "state": rule.state, "condition": rule.condition, "assertion": rule.assertion,
        "severity": rule.severity, "blocks_signoff": rule.blocks_signoff,
        "responsible_team": rule.responsible_team, "suggested_fix": rule.suggested_fix,
        "source_reference": rule.source_reference, "change_reason": rule.change_reason,
        "created_by": str(rule.created_by), "approved_by": str(rule.approved_by) if rule.approved_by else None,
        "approved_at": rule.approved_at.isoformat() if rule.approved_at else None,
    }


def _load(db: Session, entity: Entity, rule_id: uuid.UUID) -> ValidationRuleVersion:
    rule = db.query(ValidationRuleVersion).filter(
        ValidationRuleVersion.id == rule_id, ValidationRuleVersion.entity_id == entity.id
    ).first()
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule version not found")
    return rule


@router.get("/catalog")
def catalog(db: Session = Depends(get_db), entity: Entity = Depends(get_current_entity)):
    components = db.query(ComponentConfig.component_name).filter(ComponentConfig.entity_id == entity.id).all()
    return ok({
        "built_in": BUILTIN_CATALOG, "templates": TEMPLATES,
        "built_in_rules": [
            {"rule_id": rule_id, "name": name, "family": rule_family(rule_id)}
            for rule_id, name in BUILTIN_RULES
        ],
        "fields": sorted(validation_matrix.FIELDS),
        "deductions": sorted(validation_matrix.DEDUCTIONS),
        "components": [name for (name,) in components],
        "operators": sorted(validation_matrix.OPS),
    })


@router.get("")
def list_rules(db: Session = Depends(get_db), entity: Entity = Depends(get_current_entity)):
    rows = db.query(ValidationRuleVersion).filter(
        ValidationRuleVersion.entity_id == entity.id
    ).order_by(ValidationRuleVersion.rule_key, ValidationRuleVersion.version.desc()).all()
    return ok([_out(row) for row in rows])


@router.post("")
def create_rule(
    body: RuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    if not body.rule_key.startswith(("CUST-", "STATX-")):
        raise HTTPException(status_code=400, detail="Rule key must start with CUST- or STATX-")
    if (body.category == "statutory") != body.rule_key.startswith("STATX-"):
        raise HTTPException(status_code=400, detail="Statutory rules must use STATX-; custom rules use CUST-")
    configured = {
        normalize_col(name) for (name,) in db.query(ComponentConfig.component_name).filter(
            ComponentConfig.entity_id == entity.id
        ).all()
    }
    try:
        validation_matrix.validate_comparison(body.assertion.model_dump(), configured)
        if body.condition:
            validation_matrix.validate_comparison(body.condition.model_dump(), configured)
        for condition in body.conditions:
            validation_matrix.validate_comparison(condition.model_dump(), configured)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    version = (db.query(func.max(ValidationRuleVersion.version)).filter(
        ValidationRuleVersion.entity_id == entity.id,
        ValidationRuleVersion.rule_key == body.rule_key,
    ).scalar() or 0) + 1
    rule = ValidationRuleVersion(
        org_id=entity.org_id, entity_id=entity.id, rule_key=body.rule_key,
        version=version, created_by=user.id, **body.model_dump(exclude={"rule_key", "conditions", "condition_mode"}),
    )
    rule.condition = (
        {"mode": body.condition_mode, "items": [item.model_dump() for item in body.conditions]}
        if body.conditions else body.condition.model_dump() if body.condition else None
    )
    rule.assertion = body.assertion.model_dump()
    db.add(rule)
    db.flush()
    audit.record(db, entity_id=entity.id, org_id=entity.org_id, user=user,
                 action="validation_rule.drafted", object_type="validation_rule",
                 object_id=str(rule.id), summary=f"Drafted {rule.rule_key} v{version}")
    db.commit()
    return ok(_out(rule))


@router.post("/{rule_id}/simulate")
def simulate(
    rule_id: uuid.UUID, body: SimulationRequest,
    db: Session = Depends(get_db), user: User = Depends(require_entity_admin),
    entity: Entity = Depends(get_current_entity),
):
    rule = _load(db, entity, rule_id)
    period = body.period_month.replace(day=1)
    register = db.query(SalaryRegister).filter(
        SalaryRegister.entity_id == entity.id, SalaryRegister.period_month == period
    ).first()
    if register is None:
        raise HTTPException(status_code=404, detail="No saved salary register for this month")
    rows = db.query(SalaryRegisterRow).filter(
        SalaryRegisterRow.entity_id == entity.id, SalaryRegisterRow.register_id == register.id
    ).order_by(SalaryRegisterRow.employee_id).limit(body.limit).all()
    findings = [
        result for row in rows
        if (result := validation_matrix.evaluate(rule, validation_matrix.stored_row(row))) is not None
    ]
    return ok({"period_month": period.isoformat(), "sampled": len(rows),
               "findings": findings, "truncated": len(rows) == body.limit})


@router.post("/{rule_id}/submit")
def submit(rule_id: uuid.UUID, db: Session = Depends(get_db),
           user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    rule = _load(db, entity, rule_id)
    if rule.status != "draft":
        raise HTTPException(status_code=409, detail="Only drafts can be submitted")
    rule.status = "pending"
    audit.record(db, entity_id=entity.id, org_id=entity.org_id, user=user,
                 action="validation_rule.submitted", object_type="validation_rule",
                 object_id=str(rule.id), summary=f"Submitted {rule.rule_key} v{rule.version}")
    db.commit()
    return ok(_out(rule))


@router.post("/{rule_id}/publish")
def publish(rule_id: uuid.UUID, db: Session = Depends(get_db),
            user: User = Depends(require_entity_admin), entity: Entity = Depends(get_current_entity)):
    rule = _load(db, entity, rule_id)
    if rule.status != "pending":
        raise HTTPException(status_code=409, detail="Submit a draft before publishing")
    membership = tenancy.get_membership(db, user)
    if rule.category == "statutory" and (membership is None or membership.role != "owner"):
        raise HTTPException(status_code=403, detail="A group owner must approve statutory rules")
    from app.services import approvals

    try:
        approvals.require_independent(
            db, entity.org_id, "matrix_publish_requires_independent_approver",
            preparer_id=rule.created_by, approver_id=user.id, what="a validation rule",
        )
    except approvals.ApprovalRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    clash = db.query(ValidationRuleVersion).filter(
        ValidationRuleVersion.entity_id == entity.id,
        ValidationRuleVersion.rule_key == rule.rule_key,
        ValidationRuleVersion.effective_from == rule.effective_from,
        ValidationRuleVersion.status == "published",
    ).first()
    if clash:
        raise HTTPException(status_code=409, detail="A published version already starts on this date")
    rule.status = "published"
    rule.approved_by = user.id
    rule.approved_at = datetime.now(UTC)
    audit.record(db, entity_id=entity.id, org_id=entity.org_id, user=user,
                 action="validation_rule.published", object_type="validation_rule",
                 object_id=str(rule.id), summary=f"Published {rule.rule_key} v{rule.version}")
    db.commit()
    return ok(_out(rule))
