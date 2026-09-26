"""Entity-scoped configuration export and upload.

Only named configuration fields are portable. Identifiers, membership, uploaded
payroll data, approvals and audit history are never accepted from a file.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from sqlalchemy import JSON
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write
from app.envelope import ok
from app.models import (
    BankFileProfile, ComponentConfig, Entity, Formula, ImportProfile, JvRule,
    JvTemplate, MinimumWageApplicability, MinimumWageRate, SlabRule,
    StatutoryConfig, StatutorySettings, TenantRulePreference, User,
)
from app.services import audit

router = APIRouter()

# A field allowlist prevents a package from setting entity/user IDs, approvals,
# created timestamps, or any foreign key pointing at another client's data.
SECTIONS = {
    "components": (ComponentConfig, "component_name pf_applicable esic_applicable pt_applicable lwf_applicable bonus_applicable included_in_wages taxable tax_exemption_type"),
    "statutory_settings": (StatutorySettings, "pf_wage_ceiling pf_employee_rate pf_employer_rate pf_eps_rate pf_edli_rate pf_admin_rate pf_restrict_to_ceiling esic_wage_ceiling esic_employee_rate esic_employer_rate esic_round_mode pt_states lwf_states"),
    "statutory_engine": (StatutoryConfig, "pf_config esic_config component_mapping_config income_tax_config rule_thresholds_config exposure_config"),
    "formulas": (Formula, "rule_type name expression conditions version is_active"),
    "pt_lwf_slabs": (SlabRule, "state rule_type min_salary max_salary deduction_amount employer_amount frequency gender applicable_months sort_order"),
    "minimum_wage_rates": (MinimumWageRate, "state zone scheduled_employment skill_category basic_per_month vda_per_month working_days_basis effective_from effective_to source_reference"),
    "minimum_wage_applicability": (MinimumWageApplicability, "effective_from applicable reason source_reference"),
    "rule_preferences": (TenantRulePreference, "rule_id suppressed"),
    "salary_import_profiles": (ImportProfile, "name column_mapping"),
    "bank_file_profiles": (BankFileProfile, "name bank_label note kind layout delimiter encoding has_header skip_rows trailer_rows column_map amount_unit amount_sign date_format employee_id_transform row_filter is_default"),
    "jv_templates": (JvTemplate, "name note posting_basis split_mode group_by detail_level sign_convention net_pay_source voucher_date_rule voucher_type narration_template export_format balance_tolerance rounding_mode rounding_account"),
}
SECTIONS = {key: (model, fields.split()) for key, (model, fields) in SECTIONS.items()}
MAX_BYTES = 5_000_000
MAX_ROWS = 10_000


def _export(db: Session, entity_id):
    data = {}
    for key, (model, fields) in SECTIONS.items():
        rows = db.query(model).filter(model.entity_id == entity_id).all()
        data[key] = [jsonable_encoder({field: getattr(row, field) for field in fields}) for row in rows]
    data["jv_rules"] = [
        jsonable_encoder({
            "template_name": rule.template.name,
            **{field: getattr(rule, field) for field in (
                "sequence", "label", "account_code", "account_name", "side", "measures",
                "filters", "cost_center_from", "active", "note",
            )},
        })
        for rule in db.query(JvRule).filter(JvRule.entity_id == entity_id).all()
    ]
    return {"format": "peopleopslab-config", "version": 1, "sections": data}


def _convert(model, field: str, value):
    if value is None:
        return None
    column = model.__table__.columns[field]
    if isinstance(column.type, JSON):
        if not isinstance(value, (dict, list)):
            raise ValueError(f"{field}: an object or array is required")
        return value
    typ = column.type.python_type
    try:
        if typ is Decimal:
            if isinstance(value, bool):
                raise ValueError("a number is required")
            converted = Decimal(str(value))
            if not converted.is_finite():
                raise ValueError("number must be finite")
            return converted
        if typ is date:
            return date.fromisoformat(value)
        if typ is bool:
            if not isinstance(value, bool):
                raise ValueError("a boolean is required")
            return value
        if typ is int:
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError("an integer is required")
            return value
        if typ is str:
            if not isinstance(value, str) or (column.type.length and len(value) > column.type.length):
                raise ValueError("a string within the column limit is required")
            return value
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError(f"{field}: {exc}") from exc
    raise ValueError(f"Unsupported configuration field {field}")


def _validate(payload: dict) -> dict:
    if payload.get("format") != "peopleopslab-config" or payload.get("version") != 1:
        raise ValueError("Download a version 1 configuration file before uploading.")
    sections = payload.get("sections")
    if not isinstance(sections, dict) or not sections:
        raise ValueError("sections must contain at least one configuration category")
    if set(sections) - (set(SECTIONS) | {"jv_rules"}):
        raise ValueError("Unknown configuration category in file")
    if "jv_rules" in sections and "jv_templates" not in sections:
        raise ValueError("JV rules require jv_templates in the same file")
    if "jv_templates" in sections and "jv_rules" not in sections:
        raise ValueError("JV templates require jv_rules in the same file")
    if sum(len(rows) for rows in sections.values() if isinstance(rows, list)) > MAX_ROWS:
        raise ValueError("Configuration file has too many rows")
    cleaned = {}
    for key, rows in sections.items():
        if not isinstance(rows, list):
            raise ValueError(f"{key} must be an array")
        model, fields = SECTIONS.get(key, (JvRule, [
            "sequence", "label", "account_code", "account_name", "side", "measures",
            "filters", "cost_center_from", "active", "note",
        ]))
        validated = []
        for index, row in enumerate(rows, 1):
            expected = set(fields) | ({"template_name"} if key == "jv_rules" else set())
            if not isinstance(row, dict) or set(row) != expected:
                raise ValueError(f"{key} row {index} must contain exactly the fields in the downloaded template")
            converted = {field: _convert(model, field, value) for field, value in row.items() if field in fields}
            if key == "jv_rules":
                name = row.get("template_name")
                if not isinstance(name, str) or not name.strip():
                    raise ValueError(f"{key} row {index} needs a template_name")
                converted["template_name"] = name
            if key == "minimum_wage_applicability" and converted.get("applicable") is False and not (converted.get("reason") or "").strip():
                raise ValueError(f"{key} row {index} needs a reason for No")
            validated.append(converted)
        if key in ("statutory_settings", "statutory_engine") and len(validated) > 1:
            raise ValueError(f"{key} accepts at most one row")
        cleaned[key] = validated
    return cleaned


@router.get("/export")
def export_bundle(db: Session = Depends(get_db), user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    return ok(_export(db, entity.id))


@router.post("/import")
async def import_bundle(
    file: UploadFile,
    dry_run: bool = Query(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    raw = await file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "Configuration file exceeds 5 MB")
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Root must be a JSON object")
        sections = _validate(payload)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(422, f"Invalid configuration file: {exc}") from exc
    counts = {key: len(rows) for key, rows in sections.items()}
    if dry_run:
        return ok({"preview": True, "replace_sections": counts})
    if "jv_templates" in sections and db.query(JvTemplate).filter(
        JvTemplate.entity_id == entity.id, JvTemplate.state == "approved"
    ).first():
        raise HTTPException(409, "Approved JV templates cannot be replaced by a file; retain the approved version and create new draft mappings in the JV editor.")
    try:
        if "jv_rules" in sections:
            db.query(JvRule).filter(JvRule.entity_id == entity.id).delete()
        for key in sections:
            if key == "jv_rules":
                continue
            model, _ = SECTIONS[key]
            db.query(model).filter(model.entity_id == entity.id).delete()
        db.flush()
        templates = {}
        for key, rows in sections.items():
            if key == "jv_rules":
                continue
            model, _ = SECTIONS[key]
            for row in rows:
                extra = {"user_id": user.id} if "user_id" in model.__table__.columns else {}
                if key == "jv_templates":
                    # Imported JV mappings must be approved for this entity.
                    extra.update(state="draft", is_current=False, created_by_user_id=user.id)
                item = model(entity_id=entity.id, **extra, **row)
                db.add(item)
                if key == "jv_templates":
                    templates[row["name"]] = item
        db.flush()
        for row in sections.get("jv_rules", []):
            data = row.copy()
            name = data.pop("template_name")
            if name not in templates:
                raise ValueError(f"JV rule refers to unknown template {name}")
            db.add(JvRule(entity_id=entity.id, template_id=templates[name].id, **data))
        db.flush()
        audit.record(
            db, entity_id=entity.id, user=user, action="config.bundle_import",
            object_type="configuration", object_id=str(entity.id),
            summary="Uploaded configuration sections", detail={"sections": counts},
        )
        db.commit()
    except (IntegrityError, ValueError) as exc:
        db.rollback()
        raise HTTPException(422, f"Configuration import rejected: {exc}") from exc
    return ok({"preview": False, "replaced_sections": counts})
