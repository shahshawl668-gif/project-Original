"""
/api/config/statutory  — CRUD for the Config-Driven Statutory Engine.

All endpoints are tenant-scoped — get_current_user() provides isolation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.envelope import ok
from app.models import User
from app.schemas.statutory_config import (
    ComponentMappingConfig,
    ESICConfig,
    PFConfig,
    StatutoryConfigResponse,
    TenantStatutoryConfig,
)
from app.services.config_service import ConfigService, safe_eval_expr

router = APIRouter(prefix="/config/statutory", tags=["Statutory Config"])


def _svc(db: Session = Depends(get_db)) -> ConfigService:
    return ConfigService(db)


@router.get("")
def get_statutory_config(
    user: User = Depends(get_current_user),
    svc: ConfigService = Depends(_svc),
):
    cfg = svc.get_full_config(user.id)
    db_row = svc._load_row(user.id)
    resp = StatutoryConfigResponse(
        tenant_id=str(user.id),
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
    svc: ConfigService = Depends(_svc),
):
    svc.save_full_config(user.id, body)
    db_row = svc._load_row(user.id)
    resp = StatutoryConfigResponse(
        tenant_id=str(user.id),
        pf=body.pf,
        esic=body.esic,
        component_mapping=body.component_mapping,
        updated_at=db_row.updated_at.isoformat() if db_row.updated_at else None,
    )
    return ok(resp.model_dump())


@router.get("/pf")
def get_pf_config(
    user: User = Depends(get_current_user),
    svc: ConfigService = Depends(_svc),
):
    return ok(svc.get_pf_config(user.id).model_dump())


@router.put("/pf")
def save_pf_config(
    body: PFConfig,
    user: User = Depends(get_current_user),
    svc: ConfigService = Depends(_svc),
):
    svc.save_pf_config(user.id, body)
    return ok(body.model_dump())


@router.get("/esic")
def get_esic_config(
    user: User = Depends(get_current_user),
    svc: ConfigService = Depends(_svc),
):
    return ok(svc.get_esic_config(user.id).model_dump())


@router.put("/esic")
def save_esic_config(
    body: ESICConfig,
    user: User = Depends(get_current_user),
    svc: ConfigService = Depends(_svc),
):
    svc.save_esic_config(user.id, body)
    return ok(body.model_dump())


@router.get("/component-mapping")
def get_component_mapping(
    user: User = Depends(get_current_user),
    svc: ConfigService = Depends(_svc),
):
    return ok(svc.get_component_mapping(user.id).model_dump())


@router.put("/component-mapping")
def save_component_mapping(
    body: ComponentMappingConfig,
    user: User = Depends(get_current_user),
    svc: ConfigService = Depends(_svc),
):
    svc.save_component_mapping(user.id, body)
    return ok(body.model_dump())


@router.post("/reset")
def reset_to_defaults(
    user: User = Depends(get_current_user),
    svc: ConfigService = Depends(_svc),
):
    cfg = svc.reset_to_defaults(user.id)
    db_row = svc._load_row(user.id)
    resp = StatutoryConfigResponse(
        tenant_id=str(user.id),
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


@router.get("/summary")
def config_summary(
    user: User = Depends(get_current_user),
    svc: ConfigService = Depends(_svc),
):
    pf = svc.get_pf_config(user.id)
    esic = svc.get_esic_config(user.id)
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
