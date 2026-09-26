from fastapi import APIRouter

from app.routers import (
    admin,
    audit,
    auth,
    bi,
    budget,
    components,
    config_bundle,
    ctc,
    findings,
    income_tax,
    minimum_wage,
    org,
    payroll,
    reconciliation,
    reference,
    reports,
    rule_engine,
    rule_preferences,
    signoff,
    statutory,
    statutory_config,
    users,
    workforce,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(admin.router)
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(org.router, prefix="/org", tags=["org"])
api_router.include_router(components.router, prefix="/components", tags=["components"])
api_router.include_router(config_bundle.router, prefix="/config/bundle", tags=["configuration"])
api_router.include_router(statutory.router, prefix="/settings/statutory", tags=["statutory"])
api_router.include_router(reference.router, prefix="/reference", tags=["reference"])
api_router.include_router(ctc.router, prefix="/ctc", tags=["ctc"])
api_router.include_router(payroll.router, prefix="/payroll", tags=["payroll"])
api_router.include_router(findings.router, prefix="/findings", tags=["findings"])
api_router.include_router(bi.router, prefix="/bi", tags=["bi"])
api_router.include_router(budget.router, prefix="/budget", tags=["budget"])
api_router.include_router(
    reconciliation.router, prefix="/reconciliation", tags=["reconciliation"]
)
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(minimum_wage.router, prefix="/minimum-wage", tags=["minimum-wage"])
api_router.include_router(signoff.router, prefix="/signoff", tags=["signoff"])
api_router.include_router(workforce.router, prefix="/workforce", tags=["workforce"])
api_router.include_router(rule_engine.router, prefix="/rule-engine", tags=["rule-engine"])
api_router.include_router(income_tax.router, prefix="/income-tax", tags=["income-tax"])
# Config-Driven Statutory Engine (router has its own /api/config prefix)
api_router.include_router(statutory_config.router)
api_router.include_router(rule_preferences.router)
