"""Entity-scoped configuration export and upload.

Only named configuration fields are portable. Identifiers, membership, uploaded
payroll data, approvals and audit history are never accepted from a file.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import JSON
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write
from app.envelope import ok
from app.models import (
    ComponentConfig, Entity, ImportProfile, MinimumWageApplicability, MinimumWageRate, SlabRule,
    StatutoryConfig, StatutorySettings, TenantRulePreference, User,
)
from app.services import audit, config_files, tenancy
from app.schemas.component import ComponentCreate
from app.schemas.exposure_config import ExposureConfig
from app.schemas.income_tax_config import IncomeTaxConfig
from app.schemas.minimum_wage import MinimumWageRateIn
from app.schemas.rule_engine import SlabRow
from app.schemas.rule_thresholds import RuleThresholdsConfig
from app.schemas.statutory_config import ComponentMappingConfig, ESICConfig, PFConfig

router = APIRouter()

# A field allowlist prevents a package from setting entity/user IDs, approvals,
# created timestamps, or any foreign key pointing at another client's data.
SECTIONS = {
    "components": (ComponentConfig, "component_name pf_applicable esic_applicable pt_applicable lwf_applicable bonus_applicable included_in_wages taxable tax_exemption_type"),
    "statutory_settings": (StatutorySettings, "pf_wage_ceiling pf_employee_rate pf_employer_rate pf_eps_rate pf_edli_rate pf_admin_rate pf_restrict_to_ceiling esic_wage_ceiling esic_employee_rate esic_employer_rate esic_round_mode pt_states lwf_states"),
    "statutory_engine": (StatutoryConfig, "pf_config esic_config component_mapping_config income_tax_config rule_thresholds_config exposure_config"),
    "pt_lwf_slabs": (SlabRule, "state rule_type min_salary max_salary deduction_amount employer_amount frequency gender applicable_months effective_from effective_to source_reference sort_order"),
    "minimum_wage_rates": (MinimumWageRate, "state zone scheduled_employment skill_category basic_per_month vda_per_month working_days_basis effective_from effective_to source_reference"),
    "minimum_wage_applicability": (MinimumWageApplicability, "effective_from applicable reason source_reference"),
    "rule_preferences": (TenantRulePreference, "rule_id suppressed"),
    "salary_import_profiles": (ImportProfile, "name column_mapping"),
}
SECTIONS = {key: (model, fields.split()) for key, (model, fields) in SECTIONS.items()}
MAX_BYTES = 5_000_000
MAX_ROWS = 10_000
CSV_COLUMNS = ["section", "record", "field", "type", "value"]


def _export(db: Session, entity_id):
    data = {}
    for key, (model, fields) in SECTIONS.items():
        rows = db.query(model).filter(model.entity_id == entity_id).all()
        data[key] = [jsonable_encoder({field: getattr(row, field) for field in fields}) for row in rows]
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
    if set(sections) - set(SECTIONS):
        raise ValueError("Unknown configuration category in file")
    if sum(len(rows) for rows in sections.values() if isinstance(rows, list)) > MAX_ROWS:
        raise ValueError("Configuration file has too many rows")
    cleaned = {}
    for key, rows in sections.items():
        if not isinstance(rows, list):
            raise ValueError(f"{key} must be an array")
        model, fields = SECTIONS[key]
        validated = []
        for index, row in enumerate(rows, 1):
            expected = set(fields)
            if not isinstance(row, dict) or set(row) != expected:
                raise ValueError(f"{key} row {index} must contain exactly the fields in the downloaded template")
            converted = {field: _convert(model, field, value) for field, value in row.items() if field in fields}
            if key == "minimum_wage_applicability" and converted.get("applicable") is False and not (converted.get("reason") or "").strip():
                raise ValueError(f"{key} row {index} needs a reason for No")
            validated.append(converted)
        if key in ("statutory_settings", "statutory_engine") and len(validated) > 1:
            raise ValueError(f"{key} accepts at most one row")
        try:
            if key == "components":
                for row in validated:
                    ComponentCreate.model_validate(row)
            elif key == "pt_lwf_slabs":
                for row in validated:
                    if row["rule_type"] not in ("PT", "LWF") or row["min_salary"] > row["max_salary"]:
                        raise ValueError("PT/LWF row has an invalid type or salary band")
                    SlabRow.model_validate(row)
            elif key == "minimum_wage_rates":
                for row in validated:
                    MinimumWageRateIn.model_validate(row)
            elif key == "statutory_engine":
                for row in validated:
                    for field, schema in (
                        ("pf_config", PFConfig), ("esic_config", ESICConfig),
                        ("component_mapping_config", ComponentMappingConfig),
                        ("income_tax_config", IncomeTaxConfig),
                        ("rule_thresholds_config", RuleThresholdsConfig),
                        ("exposure_config", ExposureConfig),
                    ):
                        if row[field] is not None:
                            schema.model_validate(row[field])
        except ValidationError as exc:
            raise ValueError(f"{key}: {exc}") from exc
        cleaned[key] = validated
    return cleaned


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _download(db: Session, entity: Entity, fmt: str) -> Response:
    tables = config_files.to_tables(db, entity, _export(db, entity.id))
    if fmt == "csv":
        body, media = config_files.tables_to_csv(tables), "text/csv; charset=utf-8"
    else:
        body, media = config_files.tables_to_xlsx(tables), XLSX
    return Response(body, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="configuration.{fmt}"'})


@router.get("/export.csv")
def export_bundle_csv(db: Session = Depends(get_db), user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    """The company's configuration as one CSV, also the template: empty tables show their columns."""
    return _download(db, entity, "csv")


@router.get("/export.xlsx")
def export_bundle_xlsx(db: Session = Depends(get_db), user: User = Depends(get_current_user), entity: Entity = Depends(get_current_entity)):
    """The same, as a workbook with one sheet per kind of setting."""
    return _download(db, entity, "xlsx")


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
    name = (file.filename or "").lower()
    try:
        if name.endswith(".xlsx"):
            tables = config_files.xlsx_to_tables(raw)
        elif name.endswith(".csv"):
            tables = config_files.csv_to_tables(raw)
        else:
            raise ValueError("Upload the configuration as a .csv or .xlsx file")
        payload = config_files.to_bundle(db, entity, tables)
        if not payload["sections"]:
            raise ValueError("The file has no filled rows to apply")
        sections = _validate(payload)
    except ValueError as exc:
        raise HTTPException(422, f"The configuration file cannot be used: {exc}") from exc
    counts = {key: len(rows) for key, rows in sections.items()}
    if dry_run:
        return ok({"preview": True, "replace_sections": counts})
    try:
        _replace(db, entity, user, sections)
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


def _replace(db: Session, entity: Entity, user: User, sections: dict) -> None:
    """Replace the named sections of ``entity``'s configuration with ``sections``."""
    for key in sections:
        model, _ = SECTIONS[key]
        db.query(model).filter(model.entity_id == entity.id).delete()
    db.flush()
    for key, rows in sections.items():
        model, _ = SECTIONS[key]
        for row in rows:
            extra = {"user_id": user.id} if "user_id" in model.__table__.columns else {}
            db.add(model(entity_id=entity.id, **extra, **row))
    db.flush()


class CopyRequest(BaseModel):
    source_entity_id: uuid.UUID
    sections: list[str] | None = None
    reason: str = Field(min_length=8, max_length=1000)
    dry_run: bool = True


@router.post("/copy")
def copy_bundle(
    body: CopyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    """
    Copy configuration from another company the caller can open into this one.

    The same allowlisted sections a file carries, validated the same way, with
    a preview of what each section holds here and there before anything is
    replaced. A company the caller cannot open answers 404, as if it did not
    exist. Both companies' audit trails record the copy.
    """
    source = db.get(Entity, body.source_entity_id)
    if source is None or source.id == entity.id or source.org_id != entity.org_id \
            or not tenancy.can_access_entity(db, user, source):
        raise HTTPException(404, "Company not found")
    bundle = _export(db, source.id)
    wanted = body.sections or [k for k, rows in bundle["sections"].items() if rows]
    unknown = set(wanted) - set(bundle["sections"])
    if unknown:
        raise HTTPException(400, f"Unknown configuration category: {', '.join(sorted(unknown))}")
    try:
        sections = _validate({"format": "peopleopslab-config", "version": 1,
                              "sections": {k: bundle["sections"][k] for k in wanted}})
    except ValueError as exc:
        raise HTTPException(422, f"The source configuration cannot be copied: {exc}") from exc
    here = _export(db, entity.id)["sections"]
    plan = {k: {"from_source": len(sections[k]), "replacing_here": len(here.get(k) or [])} for k in sections}
    if body.dry_run:
        return ok({"preview": True, "source": {"id": str(source.id), "name": source.name}, "sections": plan})
    try:
        _replace(db, entity, user, sections)
        detail = {"sections": plan, "reason": body.reason}
        audit.record(db, entity_id=entity.id, user=user, action="config.copied_in",
                     object_type="configuration", object_id=str(entity.id),
                     summary=f"Configuration copied from {source.name}: {', '.join(sorted(sections))}",
                     detail={**detail, "from_entity_id": str(source.id)})
        audit.record(db, entity_id=source.id, user=user, action="config.copied_out",
                     object_type="configuration", object_id=str(source.id),
                     summary=f"Configuration copied to {entity.name}: {', '.join(sorted(sections))}",
                     detail={**detail, "to_entity_id": str(entity.id)})
        db.commit()
    except (IntegrityError, ValueError) as exc:
        db.rollback()
        raise HTTPException(422, f"Configuration copy rejected: {exc}") from exc
    return ok({"preview": False, "source": {"id": str(source.id), "name": source.name}, "sections": plan})
