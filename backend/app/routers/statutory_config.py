"""
/api/config/statutory  — CRUD for the Config-Driven Statutory Engine.

All endpoints are entity-scoped — get_current_entity() provides isolation.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write
from app.envelope import ok
from app.models import Entity, User
from app.schemas.income_tax_config import IncomeTaxConfig, TaxYearUpsert
from app.schemas.rule_thresholds import RuleThresholdsConfig
from app.schemas.statutory_config import (
    ComponentMappingConfig,
    ESICConfig,
    PFConfig,
    StatutoryConfigResponse,
    TenantStatutoryConfig,
)
from app.services import audit
from app.services.config_service import ConfigService, safe_eval_expr

router = APIRouter(prefix="/config/statutory", tags=["Statutory Config"])


def _svc(db: Session = Depends(get_db)) -> ConfigService:
    return ConfigService(db)


def _changes(before: object, after: object, path: str = "", out: list | None = None) -> list[dict]:
    """Every leaf that differs, as ``{field, before, after}`` — what an auditor reads."""
    out = [] if out is None else out
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            _changes(before.get(key), after.get(key), f"{path}.{key}" if path else str(key), out)
    elif before != after and not _same_number(before, after):
        out.append({"field": path, "before": before, "after": after})
    return out


def _same_number(a: object, b: object) -> bool:
    """'0.0050' and '0.005' are one rate written two ways, not a change."""
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except (InvalidOperation, ValueError):
        return False


def _keep_stored_form(before: object, after: object) -> object:
    """
    The configuration as submitted, except that any value numerically equal
    to what is stored keeps its stored text.

    A save travels through the browser, which returns ``0.0050`` as ``0.005``.
    Runs are fingerprinted on the configuration's text, so without this an
    unchanged save — or a change to one field — marked every validated month
    "revalidation required" for fields nobody touched.
    """
    if isinstance(before, dict) and isinstance(after, dict):
        return {k: _keep_stored_form(before.get(k), v) if k in before else v for k, v in after.items()}
    if before != after and _same_number(before, after):
        return before
    return after


def _record_change(svc: ConfigService, entity: Entity, user: User, after: TenantStatutoryConfig, action: str) -> None:
    """
    Rates, ceilings and rounding decide every statutory check, so a change to
    them is recorded — who, when, and each field before and after — in the
    same transaction as the save. Runs already made keep the configuration
    they were validated with; this is the record of when it moved.
    """
    before = svc.get_full_config(entity.id).model_dump(mode="json")
    changes = _changes(before, after.model_dump(mode="json"))
    if not changes and action == "statutory_config.saved":
        return
    audit.record(
        svc._db, entity_id=entity.id, user=user, action=action, object_type="statutory_config",
        object_id=str(entity.id),
        summary=(f"Reset the statutory configuration to the shipped defaults ({len(changes)} field(s) changed)"
                 if action == "statutory_config.reset"
                 else f"Changed the statutory configuration: {', '.join(c['field'] for c in changes[:4])}"
                      + (f" and {len(changes) - 4} more" if len(changes) > 4 else "")),
        detail={"changes": changes[:100], "changed": len(changes)},
    )


@router.get("")
def get_statutory_config(
    entity: Entity = Depends(get_current_entity),
    svc: ConfigService = Depends(_svc),
):
    cfg = svc.get_full_config(entity.id)
    db_row = svc._load_row(entity.id)
    resp = StatutoryConfigResponse(
        tenant_id=str(entity.id),
        pf=cfg.pf,
        esic=cfg.esic,
        component_mapping=cfg.component_mapping,
        updated_at=db_row.updated_at.isoformat() if db_row.updated_at else None,
    )
    return ok(resp.model_dump())


@router.put("")
def save_statutory_config(
    body: TenantStatutoryConfig,
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
    svc: ConfigService = Depends(_svc),
):
    stored = svc.get_full_config(entity.id).model_dump(mode="json")
    body = TenantStatutoryConfig.model_validate(_keep_stored_form(stored, body.model_dump(mode="json")))
    if _changes(stored, body.model_dump(mode="json")):
        _record_change(svc, entity, user, body, "statutory_config.saved")
        svc.save_full_config(entity.id, body)
    # Nothing changed: nothing is written, so no run is made stale by a save.
    db_row = svc._load_row(entity.id)
    resp = StatutoryConfigResponse(
        tenant_id=str(entity.id),
        pf=body.pf,
        esic=body.esic,
        component_mapping=body.component_mapping,
        updated_at=db_row.updated_at.isoformat() if db_row.updated_at else None,
    )
    return ok(resp.model_dump())


@router.get("/pf")
def get_pf_config(
    entity: Entity = Depends(get_current_entity),
    svc: ConfigService = Depends(_svc),
):
    return ok(svc.get_pf_config(entity.id).model_dump())


@router.put("/pf")
def save_pf_config(
    body: PFConfig,
    entity: Entity = Depends(require_entity_write),
    svc: ConfigService = Depends(_svc),
):
    svc.save_pf_config(entity.id, body)
    return ok(body.model_dump())


@router.get("/esic")
def get_esic_config(
    entity: Entity = Depends(get_current_entity),
    svc: ConfigService = Depends(_svc),
):
    return ok(svc.get_esic_config(entity.id).model_dump())


@router.put("/esic")
def save_esic_config(
    body: ESICConfig,
    entity: Entity = Depends(require_entity_write),
    svc: ConfigService = Depends(_svc),
):
    svc.save_esic_config(entity.id, body)
    return ok(body.model_dump())


@router.get("/component-mapping")
def get_component_mapping(
    entity: Entity = Depends(get_current_entity),
    svc: ConfigService = Depends(_svc),
):
    return ok(svc.get_component_mapping(entity.id).model_dump())


@router.put("/component-mapping")
def save_component_mapping(
    body: ComponentMappingConfig,
    entity: Entity = Depends(require_entity_write),
    svc: ConfigService = Depends(_svc),
):
    svc.save_component_mapping(entity.id, body)
    return ok(body.model_dump())


@router.post("/reset")
def reset_to_defaults(
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
    svc: ConfigService = Depends(_svc),
):
    _record_change(svc, entity, user, TenantStatutoryConfig(), "statutory_config.reset")
    cfg = svc.reset_to_defaults(entity.id)
    db_row = svc._load_row(entity.id)
    resp = StatutoryConfigResponse(
        tenant_id=str(entity.id),
        pf=cfg.pf,
        esic=cfg.esic,
        component_mapping=cfg.component_mapping,
        updated_at=db_row.updated_at.isoformat() if db_row.updated_at else None,
    )
    return ok(resp.model_dump())


@router.post("/test-expression")
def test_expression(body: dict, user: User = Depends(get_current_user)):
    expression = body.get("expression", "")
    context = body.get("context", {})
    if not expression:
        raise HTTPException(status_code=400, detail="expression is required")
    try:
        result = safe_eval_expr(expression, context)
        return ok({"result": result, "result_type": type(result).__name__, "eval_ok": True})
    except Exception as e:
        return ok({"error": str(e), "eval_ok": False})


# ─── Income tax (FY-versioned) ────────────────────────────────────────────────

@router.get("/income-tax")
def get_income_tax_config(
    entity: Entity = Depends(get_current_entity),
    svc: ConfigService = Depends(_svc),
):
    return ok(svc.get_income_tax_config(entity.id).model_dump(mode="json"))


@router.put("/income-tax")
def save_income_tax_config(
    body: IncomeTaxConfig,
    entity: Entity = Depends(require_entity_write),
    svc: ConfigService = Depends(_svc),
):
    if body.default_year and body.default_year not in body.years:
        raise HTTPException(status_code=422, detail=f"default_year '{body.default_year}' has no entry in years.")
    svc.save_income_tax_config(entity.id, body)
    return ok(body.model_dump(mode="json"))


@router.put("/income-tax/years/{financial_year}")
def upsert_tax_year(
    financial_year: str,
    body: TaxYearUpsert,
    entity: Entity = Depends(require_entity_write),
    svc: ConfigService = Depends(_svc),
):
    """Add or replace one financial year's parameters."""
    cfg = svc.get_income_tax_config(entity.id)
    year = body.year.model_copy(update={"financial_year": financial_year})
    cfg.years[financial_year] = year
    if body.make_default or not cfg.default_year:
        cfg.default_year = financial_year
    svc.save_income_tax_config(entity.id, cfg)
    return ok(cfg.model_dump(mode="json"))


@router.delete("/income-tax/years/{financial_year}")
def delete_tax_year(
    financial_year: str,
    entity: Entity = Depends(require_entity_write),
    svc: ConfigService = Depends(_svc),
):
    cfg = svc.get_income_tax_config(entity.id)
    if financial_year not in cfg.years:
        raise HTTPException(status_code=404, detail=f"No config for FY {financial_year}.")
    if len(cfg.years) == 1:
        raise HTTPException(status_code=422, detail="Cannot delete the only financial year.")
    del cfg.years[financial_year]
    if cfg.default_year == financial_year:
        cfg.default_year = sorted(cfg.years)[-1]
    svc.save_income_tax_config(entity.id, cfg)
    return ok(cfg.model_dump(mode="json"))


@router.post("/income-tax/reset")
def reset_income_tax_config(
    entity: Entity = Depends(require_entity_write),
    svc: ConfigService = Depends(_svc),
):
    return ok(svc.reset_income_tax_config(entity.id).model_dump(mode="json"))


# ─── Rule-engine thresholds ───────────────────────────────────────────────────

@router.get("/rule-thresholds")
def get_rule_thresholds(
    entity: Entity = Depends(get_current_entity),
    svc: ConfigService = Depends(_svc),
):
    return ok(svc.get_rule_thresholds(entity.id).model_dump(mode="json"))


@router.put("/rule-thresholds")
def save_rule_thresholds(
    body: RuleThresholdsConfig,
    entity: Entity = Depends(require_entity_write),
    svc: ConfigService = Depends(_svc),
):
    svc.save_rule_thresholds(entity.id, body)
    return ok(body.model_dump(mode="json"))


@router.post("/rule-thresholds/reset")
def reset_rule_thresholds(
    entity: Entity = Depends(require_entity_write),
    svc: ConfigService = Depends(_svc),
):
    return ok(svc.reset_rule_thresholds(entity.id).model_dump(mode="json"))


@router.get("/summary")
def config_summary(
    entity: Entity = Depends(get_current_entity),
    svc: ConfigService = Depends(_svc),
):
    pf = svc.get_pf_config(entity.id)
    esic = svc.get_esic_config(entity.id)
    return ok(
        {
            "pf": {
                "wage_ceiling": str(pf.wage.wage_ceiling),
                "restrict_to_ceiling": pf.wage.restrict_to_ceiling,
                "employee_rate": f"{float(pf.rates.employee_rate)*100:.2f}%",
                "employer_rate": f"{float(pf.rates.employer_rate)*100:.2f}%",
                "eps_rate": f"{float(pf.rates.eps_rate)*100:.4f}%",
                "edli_rate": f"{float(pf.rates.edli_rate)*100:.4f}%",
                "admin_rate": f"{float(pf.rates.admin_rate)*100:.4f}%",
                "wage_mode": "pf_applicable flag" if pf.wage.use_pf_applicable_flag else "explicit list",
                "voluntary_pf": pf.voluntary.enabled,
                "above_ceiling_mode": pf.above_ceiling_mode,
                "eligibility_expression": pf.eligibility.expression,
            },
            "esic": {
                "wage_ceiling": str(esic.wage.wage_ceiling),
                "employee_rate": f"{float(esic.rates.employee_rate)*100:.4f}%",
                "employer_rate": f"{float(esic.rates.employer_rate)*100:.4f}%",
                "rounding_mode": esic.rounding.mode,
                "wage_mode": "esic_applicable flag"
                if esic.wage.use_esic_applicable_flag
                else "explicit list",
                "eligibility_expression": esic.eligibility.expression,
            },
        }
    )
