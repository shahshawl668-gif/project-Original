"""
ConfigService — reads, writes, and caches per-tenant statutory configs.

Usage
-----
    from app.services.config_service import ConfigService

    # In a FastAPI endpoint or validation function:
    svc = ConfigService(db)
    pf_cfg  = svc.get_pf_config(user.id)
    esic_cfg = svc.get_esic_config(user.id)
    full_cfg = svc.get_full_config(user.id)

    # To update:
    svc.save_pf_config(user.id, new_pf_cfg)

Expression evaluation
---------------------
PFEligibilityConfig.expression and ESICEligibilityConfig.expression are
evaluated with the safe AST-based evaluator.  Supported variables depend on
context (see eval_pf_eligibility / eval_esic_eligibility below).
"""
from __future__ import annotations

import ast
import math
import operator as _op
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.statutory_config import StatutoryConfig
from app.schemas.statutory_config import (
    ComponentMappingConfig,
    ESICConfig,
    PFConfig,
    TenantStatutoryConfig,
)


# ─── Safe expression evaluator ───────────────────────────────────────────────

_SAFE_OPS: dict[type, Any] = {
    ast.Add: _op.add,
    ast.Sub: _op.sub,
    ast.Mult: _op.mul,
    ast.Div: _op.truediv,
    ast.FloorDiv: _op.floordiv,
    ast.Mod: _op.mod,
    ast.Pow: _op.pow,
    ast.UAdd: _op.pos,
    ast.USub: _op.neg,
    ast.And: None,
    ast.Or: None,
    ast.Not: None,
    ast.Eq: _op.eq,
    ast.NotEq: _op.ne,
    ast.Lt: _op.lt,
    ast.LtE: _op.le,
    ast.Gt: _op.gt,
    ast.GtE: _op.ge,
}

_SAFE_FUNCS: dict[str, Any] = {
    "abs": abs, "min": min, "max": max, "round": round,
    "ceil": math.ceil, "floor": math.floor,
    "int": int, "float": float, "bool": bool, "str": str,
    "True": True, "False": False,
}


def _safe_eval(node: ast.AST, ctx: dict[str, Any]) -> Any:
    """Recursively evaluate a safe AST node — no imports, no attribute access."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body, ctx)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        key = node.id
        if key in _SAFE_FUNCS:
            return _SAFE_FUNCS[key]
        if key in ctx:
            return ctx[key]
        raise NameError(f"Undefined variable '{key}' in expression")
    if isinstance(node, ast.BinOp):
        fn = _SAFE_OPS.get(type(node.op))
        if fn is None:
            raise ValueError(f"Unsupported binary op {node.op!r}")
        return fn(_safe_eval(node.left, ctx), _safe_eval(node.right, ctx))
    if isinstance(node, ast.UnaryOp):
        fn = _SAFE_OPS.get(type(node.op))
        if fn is None:
            raise ValueError(f"Unsupported unary op {node.op!r}")
        return fn(_safe_eval(node.operand, ctx))
    if isinstance(node, ast.Compare):
        left = _safe_eval(node.left, ctx)
        for op_node, comp in zip(node.ops, node.comparators):
            fn = _SAFE_OPS.get(type(op_node))
            if fn is None:
                raise ValueError(f"Unsupported compare op {op_node!r}")
            right = _safe_eval(comp, ctx)
            if not fn(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_safe_eval(v, ctx) for v in node.values)
        if isinstance(node.op, ast.Or):
            return any(_safe_eval(v, ctx) for v in node.values)
    if isinstance(node, ast.IfExp):
        test = _safe_eval(node.test, ctx)
        return _safe_eval(node.body, ctx) if test else _safe_eval(node.orelse, ctx)
    if isinstance(node, ast.Call):
        func = _safe_eval(node.func, ctx)
        args = [_safe_eval(a, ctx) for a in node.args]
        return func(*args)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _safe_eval(node.operand, ctx)
    raise TypeError(f"Unsupported AST node {type(node).__name__}")


def safe_eval_expr(expression: str, context: dict[str, Any]) -> Any:
    """
    Evaluate *expression* in a restricted Python environment.

    * No imports, no attribute access, no function calls except allow-listed.
    * Returns the evaluated result; raises ValueError on parse/eval error.
    """
    if not expression or not expression.strip():
        return True
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Expression syntax error: {e}") from e
    try:
        return _safe_eval(tree, context)
    except Exception as e:
        raise ValueError(f"Expression evaluation error: {e}") from e


# ─── ConfigService ────────────────────────────────────────────────────────────

class ConfigService:
    """
    Tenant-isolated config loader for PF, ESIC, and component mapping.

    One instance per request (share the db Session).
    Results are memoised for the lifetime of the instance.
    """

    def __init__(self, db: Session):
        self._db = db
        self._cache: dict[str, TenantStatutoryConfig] = {}

    # ── private helpers ───────────────────────────────────────────────────────

    def _load_row(self, tenant_id: uuid.UUID) -> StatutoryConfig:
        key = str(tenant_id)
        row = (
            self._db.query(StatutoryConfig)
            .filter(StatutoryConfig.user_id == tenant_id)
            .first()
        )
        if row is None:
            row = StatutoryConfig(user_id=tenant_id, pf_config={}, esic_config={}, component_mapping_config={})
            self._db.add(row)
            self._db.commit()
            self._db.refresh(row)
        return row

    def _load_full(self, tenant_id: uuid.UUID) -> TenantStatutoryConfig:
        key = str(tenant_id)
        if key in self._cache:
            return self._cache[key]
        row = self._load_row(tenant_id)
        cfg = TenantStatutoryConfig(
            pf=PFConfig.model_validate(row.pf_config or {}),
            esic=ESICConfig.model_validate(row.esic_config or {}),
            component_mapping=ComponentMappingConfig.model_validate(row.component_mapping_config or {}),
        )
        self._cache[key] = cfg
        return cfg

    # ── public API ────────────────────────────────────────────────────────────

    def get_pf_config(self, tenant_id: uuid.UUID) -> PFConfig:
        """Return the PFConfig for this tenant (with defaults if not yet saved)."""
        return self._load_full(tenant_id).pf

    def get_esic_config(self, tenant_id: uuid.UUID) -> ESICConfig:
        """Return the ESICConfig for this tenant."""
        return self._load_full(tenant_id).esic

    def get_component_mapping(self, tenant_id: uuid.UUID) -> ComponentMappingConfig:
        """Return the ComponentMappingConfig for this tenant."""
        return self._load_full(tenant_id).component_mapping

    def get_full_config(self, tenant_id: uuid.UUID) -> TenantStatutoryConfig:
        """Return the full TenantStatutoryConfig."""
        return self._load_full(tenant_id)

    def save_pf_config(self, tenant_id: uuid.UUID, pf_cfg: PFConfig) -> None:
        row = self._load_row(tenant_id)
        row.pf_config = pf_cfg.model_dump(mode="json")
        self._db.commit()
        self._cache.pop(str(tenant_id), None)

    def save_esic_config(self, tenant_id: uuid.UUID, esic_cfg: ESICConfig) -> None:
        row = self._load_row(tenant_id)
        row.esic_config = esic_cfg.model_dump(mode="json")
        self._db.commit()
        self._cache.pop(str(tenant_id), None)

    def save_component_mapping(self, tenant_id: uuid.UUID, mapping: ComponentMappingConfig) -> None:
        row = self._load_row(tenant_id)
        row.component_mapping_config = mapping.model_dump(mode="json")
        self._db.commit()
        self._cache.pop(str(tenant_id), None)

    def save_full_config(self, tenant_id: uuid.UUID, cfg: TenantStatutoryConfig) -> None:
        row = self._load_row(tenant_id)
        row.pf_config = cfg.pf.model_dump(mode="json")
        row.esic_config = cfg.esic.model_dump(mode="json")
        row.component_mapping_config = cfg.component_mapping.model_dump(mode="json")
        self._db.commit()
        self._cache.pop(str(tenant_id), None)

    def reset_to_defaults(self, tenant_id: uuid.UUID) -> TenantStatutoryConfig:
        defaults = TenantStatutoryConfig()
        self.save_full_config(tenant_id, defaults)
        return defaults

    # ── Eligibility evaluators ────────────────────────────────────────────────

    def eval_pf_eligibility(
        self,
        tenant_id: uuid.UUID,
        pf_wage: Decimal,
        gross: Decimal,
        employment_type: str = "employee",
    ) -> bool:
        """Evaluate PF eligibility expression for given employee context."""
        pf_cfg = self.get_pf_config(tenant_id)
        elig = pf_cfg.eligibility

        if employment_type.lower() in [e.lower() for e in elig.exempt_employment_types]:
            return False

        ctx: dict[str, Any] = {
            "pf_wage": float(pf_wage),
            "gross": float(gross),
            "employee_type": employment_type,
        }
        try:
            return bool(safe_eval_expr(elig.expression, ctx))
        except Exception:
            return pf_wage > 0

    def eval_esic_eligibility(
        self,
        tenant_id: uuid.UUID,
        esic_wage: Decimal,
        employment_type: str = "employee",
    ) -> bool:
        """Evaluate ESIC eligibility expression for given employee context."""
        esic_cfg = self.get_esic_config(tenant_id)
        elig = esic_cfg.eligibility

        if employment_type.lower() in [e.lower() for e in elig.exempt_employment_types]:
            return False

        ceiling = float(esic_cfg.wage.wage_ceiling)
        ctx: dict[str, Any] = {
            "esic_wage": float(esic_wage),
            "esic_ceiling": ceiling,
            "employee_type": employment_type,
        }
        try:
            return bool(safe_eval_expr(elig.expression, ctx))
        except Exception:
            return 0 < float(esic_wage) <= ceiling
