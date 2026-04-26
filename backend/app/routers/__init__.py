from fastapi import APIRouter

from app.routers import (
    auth,
    components,
    ctc,
    payroll,
    reference,
    rule_engine,
    statutory,
    statutory_config,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(components.router, prefix="/components", tags=["components"])
api_router.include_router(statutory.router, prefix="/settings/statutory", tags=["statutory"])
api_router.include_router(reference.router, prefix="/reference", tags=["reference"])
api_router.include_router(ctc.router, prefix="/ctc", tags=["ctc"])
api_router.include_router(payroll.router, prefix="/payroll", tags=["payroll"])
api_router.include_router(rule_engine.router, prefix="/rule-engine", tags=["rule-engine"])
# Config-Driven Statutory Engine (router has its own /api/config prefix)
api_router.include_router(statutory_config.router)
