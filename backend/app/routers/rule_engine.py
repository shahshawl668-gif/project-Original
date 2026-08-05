from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.database import Database

from app.database import get_db
from app.deps import get_current_user
from app.envelope import ok
from app.models import Formula, SlabRule, User
from app.schemas.rule_engine import (
    FormulaCreate,
    FormulaOut,
    SlabRowOut,
    SlabsResponse,
    SlabSaveRequest,
    TestFormulaRequest,
    TestFormulaResponse,
)
from app.services.formula_eval import FormulaError, evaluate_conditions, evaluate_formula
from app.services.lwf_defaults import LWF_DEFAULTS
from app.services.lwf_defaults import get_defaults as get_lwf_default_slabs
from app.services.lwf_defaults import list_default_states as list_lwf_states
from app.services.pt_defaults import PT_DEFAULTS
from app.services.pt_defaults import get_defaults as get_pt_default_slabs
from app.services.pt_defaults import list_default_states as list_pt_states


def _defaults_for(rule_type: str):
    rt = rule_type.upper()
    if rt == "PT":
        return PT_DEFAULTS, get_pt_default_slabs, list_pt_states
    if rt == "LWF":
        return LWF_DEFAULTS, get_lwf_default_slabs, list_lwf_states
    raise HTTPException(status_code=400, detail=f"Unsupported rule_type: {rule_type}")


def _build_slabs_response(state: str, rule_type: str, db: Database, user: User) -> SlabsResponse:
    rt = rule_type.upper()
    rows = sorted(
        SlabRule.find_many(db, {"user_id": user.id, "state": state, "rule_type": rt}),
        key=lambda r: (r.sort_order, r.min_salary),
    )
    return SlabsResponse(
        state=state,
        rule_type=rt,
        slabs=[
            SlabRowOut(
                id=str(r.id),
                min_salary=r.min_salary,
                max_salary=r.max_salary,
                deduction_amount=r.deduction_amount,
                employer_amount=r.employer_amount,
                frequency=r.frequency,
                gender=(r.gender or "ALL"),
                applicable_months=r.applicable_months,
            )
            for r in rows
        ],
    )


router = APIRouter()


@router.get("/formulas")
def list_formulas(
    rule_type: str | None = Query(default=None),
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    filt: dict = {"user_id": user.id}
    if rule_type:
        filt["rule_type"] = rule_type.upper()
    rows = Formula.find_many(db, filt, sort=[("rule_type", 1), ("version", -1)])
    return ok([FormulaOut.model_validate(r).model_dump() for r in rows])


@router.post("/formula", status_code=201)
def create_formula(
    body: FormulaCreate,
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        evaluate_formula(body.expression, _sample_vars())
    except FormulaError as e:
        raise HTTPException(status_code=400, detail=f"Invalid formula: {e}")

    latest = Formula.find_one(
        db,
        {"user_id": user.id, "rule_type": body.rule_type},
        sort=[("version", -1)],
    )
    next_version = (latest.version if latest else 0) + 1

    if body.activate:
        Formula.update_many(
            db,
            {"user_id": user.id, "rule_type": body.rule_type, "is_active": True},
            {"$set": {"is_active": False}},
        )

    row = Formula(
        user_id=user.id,
        rule_type=body.rule_type,
        name=body.name,
        expression=body.expression,
        conditions=[c.model_dump() for c in body.conditions],
        version=next_version,
        is_active=body.activate,
    )
    row.insert(db)
    return ok(FormulaOut.model_validate(row).model_dump())


@router.post("/formula/{formula_id}/activate")
def activate_formula(
    formula_id: str,
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        fid = uuid.UUID(formula_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid id")
    target = Formula.find_one(db, {"_id": fid, "user_id": user.id})
    if not target:
        raise HTTPException(status_code=404, detail="Formula not found")
    Formula.update_many(
        db,
        {"user_id": user.id, "rule_type": target.rule_type, "is_active": True},
        {"$set": {"is_active": False}},
    )
    target.is_active = True
    target.save(db)
    return ok(FormulaOut.model_validate(target).model_dump())


@router.delete("/formula/{formula_id}")
def delete_formula(
    formula_id: str,
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        fid = uuid.UUID(formula_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid id")
    if Formula.delete_one(db, {"_id": fid, "user_id": user.id}) == 0:
        raise HTTPException(status_code=404, detail="Formula not found")
    return ok({"deleted": formula_id})


@router.post("/test-formula")
def test_formula(body: TestFormulaRequest, _user: User = Depends(get_current_user)):
    vars_ = {**_sample_vars(), **body.variables}
    try:
        cond_pass = evaluate_conditions(
            [c.model_dump() for c in body.conditions], vars_
        )
        if not cond_pass:
            return ok(TestFormulaResponse(ok=True, result=0.0, conditions_passed=False).model_dump())
        result = evaluate_formula(body.expression, vars_)
        return ok(TestFormulaResponse(ok=True, result=result, conditions_passed=True).model_dump())
    except FormulaError as e:
        return ok(TestFormulaResponse(ok=False, error=str(e)).model_dump())


def _sample_vars() -> dict[str, float]:
    return {
        "basic": 0.0,
        "da": 0.0,
        "hra": 0.0,
        "gross": 0.0,
        "pf_wage": 0.0,
        "esic_wage": 0.0,
        "ctc_monthly": 0.0,
        "paid_days": 30.0,
        "lop_days": 0.0,
        "total_days": 30.0,
    }


@router.get("/slabs")
def get_slabs_route(
    state: str = Query(...),
    rule_type: str = Query(...),
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return ok(_build_slabs_response(state, rule_type, db, user).model_dump())


@router.post("/slabs")
def save_slabs(
    body: SlabSaveRequest,
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):

    def _bucket(s) -> tuple:
        months = tuple(sorted(s.applicable_months)) if s.applicable_months else ()
        return ((s.gender or "ALL"), months)

    for idx, s in enumerate(body.slabs):
        if s.min_salary > s.max_salary:
            raise HTTPException(
                status_code=400,
                detail=f"Row {idx + 1}: min_salary ({s.min_salary}) must be <= max_salary ({s.max_salary}).",
            )

    by_bucket: dict[tuple, list] = {}
    for s in body.slabs:
        by_bucket.setdefault(_bucket(s), []).append(s)
    for bucket, slab_rows in by_bucket.items():
        rows_sorted = sorted(slab_rows, key=lambda r: r.min_salary)
        last_max = None
        for r in rows_sorted:
            if last_max is not None and r.min_salary <= last_max:
                gender, months = bucket
                tag = f"gender={gender}" + (f", months={list(months)}" if months else "")
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Slabs overlap within {tag}: row {r.min_salary}-{r.max_salary} "
                        f"<= prev max {last_max}."
                    ),
                )
            last_max = r.max_salary

    SlabRule.delete_many(
        db, {"user_id": user.id, "state": body.state, "rule_type": body.rule_type}
    )

    gender_rank = {"ALL": 0, "MALE": 1, "FEMALE": 2}

    def _sort_key(s):
        return (
            gender_rank.get((s.gender or "ALL"), 9),
            1 if s.applicable_months else 0,
            float(s.min_salary),
        )

    SlabRule.insert_many(
        db,
        [
            SlabRule(
                user_id=user.id,
                state=body.state,
                rule_type=body.rule_type,
                min_salary=s.min_salary,
                max_salary=s.max_salary,
                deduction_amount=s.deduction_amount,
                employer_amount=s.employer_amount,
                frequency=s.frequency,
                gender=(s.gender or "ALL"),
                applicable_months=s.applicable_months,
                sort_order=idx,
            )
            for idx, s in enumerate(sorted(body.slabs, key=_sort_key))
        ],
    )

    return ok(_build_slabs_response(body.state, body.rule_type, db, user).model_dump())


def _slab_kwargs(rule_type: str, state: str, idx: int, user_id, s: dict) -> dict:
    return dict(
        user_id=user_id,
        state=state,
        rule_type=rule_type,
        min_salary=s["min_salary"],
        max_salary=s["max_salary"],
        deduction_amount=s["deduction_amount"],
        employer_amount=s.get("employer_amount"),
        frequency=s["frequency"],
        gender=s.get("gender", "ALL"),
        applicable_months=s.get("applicable_months"),
        sort_order=idx,
    )


@router.get("/defaults/pt-states")
def get_pt_default_states(_user: User = Depends(get_current_user)):
    return ok({"states": list_pt_states()})


@router.get("/defaults/lwf-states")
def get_lwf_default_states(_user: User = Depends(get_current_user)):
    return ok({"states": list_lwf_states()})


@router.get("/defaults/states")
def get_all_default_states(_user: User = Depends(get_current_user)):
    return ok({"PT": list_pt_states(), "LWF": list_lwf_states()})


@router.post("/slabs/import-defaults")
def import_default_slabs(
    state: str = Query(...),
    rule_type: str = Query(default="PT"),
    overwrite: bool = Query(default=True),
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rt = rule_type.upper()
    catalog, get_state, list_states = _defaults_for(rt)
    defaults = get_state(state)
    if not defaults:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No {rt} defaults available for state '{state}'. "
                f"Available: {', '.join(list_states())}"
            ),
        )

    if overwrite:
        SlabRule.delete_many(db, {"user_id": user.id, "state": state, "rule_type": rt})

    SlabRule.insert_many(
        db,
        [SlabRule(**_slab_kwargs(rt, state, idx, user.id, s)) for idx, s in enumerate(defaults)],
    )
    return ok(_build_slabs_response(state, rt, db, user).model_dump())


@router.post("/slabs/reset-defaults")
def reset_default_slabs(
    rule_type: str = Query(default="PT"),
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rt = rule_type.upper()
    catalog, _get, _list = _defaults_for(rt)

    deleted = SlabRule.delete_many(db, {"user_id": user.id, "rule_type": rt})
    imported: dict[str, int] = {}
    for state, rows in catalog.items():
        SlabRule.insert_many(
            db,
            [SlabRule(**_slab_kwargs(rt, state, idx, user.id, s)) for idx, s in enumerate(rows)],
        )
        imported[state] = len(rows)
    return ok(
        {
            "rule_type": rt,
            "deleted_rows": int(deleted or 0),
            "imported": imported,
            "total_states": len(imported),
        }
    )


@router.post("/slabs/import-defaults/all")
def import_all_default_slabs(
    rule_type: str = Query(default="PT"),
    overwrite: bool = Query(default=False),
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rt = rule_type.upper()
    catalog, _get, _list = _defaults_for(rt)

    imported: dict[str, int] = {}
    for state, rows in catalog.items():
        if overwrite:
            SlabRule.delete_many(db, {"user_id": user.id, "state": state, "rule_type": rt})
        elif SlabRule.count(db, {"user_id": user.id, "state": state, "rule_type": rt}):
            imported[state] = 0
            continue
        SlabRule.insert_many(
            db,
            [SlabRule(**_slab_kwargs(rt, state, idx, user.id, s)) for idx, s in enumerate(rows)],
        )
        imported[state] = len(rows)
    return ok(
        {
            "rule_type": rt,
            "imported": imported,
            "total_states": len([k for k, v in imported.items() if v]),
        }
    )
