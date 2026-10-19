from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_entity, get_current_user, require_entity_write
from app.envelope import ok
from app.models import Entity, SlabRule, StatutorySettings, User
from app.schemas.rule_engine import (
    SlabRowOut,
    SlabsResponse,
    SlabSaveRequest,
    TestFormulaRequest,
    TestFormulaResponse,
)
from app.services.formula_eval import FormulaError, evaluate_conditions, evaluate_formula
from app.services.saved_formulas import BUILT_IN_INPUTS, component_inputs, explain, sample_variables
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


def _build_slabs_response(state: str, rule_type: str, db: Session, entity: Entity) -> SlabsResponse:
    rt = rule_type.upper()
    rows = (
        db.query(SlabRule)
        .filter(
            SlabRule.entity_id == entity.id,
            SlabRule.state == state,
            SlabRule.rule_type == rt,
        )
        .order_by(SlabRule.sort_order, SlabRule.min_salary)
        .all()
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
                effective_from=r.effective_from,
                effective_to=r.effective_to,
                source_reference=r.source_reference,
            )
            for r in rows
        ],
    )


router = APIRouter()

@router.get("/variables")
def formula_variables(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """What a formula may refer to: the built-in inputs and this company's salary components."""
    return ok({
        "inputs": [{"key": k, "label": label} for k, label in BUILT_IN_INPUTS],
        "components": component_inputs(db, entity),
    })


@router.post("/test-formula")
def test_formula(
    body: TestFormulaRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    vars_ = {**sample_variables(db, entity), **body.variables}
    try:
        cond_pass = evaluate_conditions(
            [c.model_dump() for c in body.conditions], vars_
        )
        if not cond_pass:
            return ok(TestFormulaResponse(ok=True, result=0.0, conditions_passed=False).model_dump())
        result = evaluate_formula(body.expression, vars_)
        return ok(TestFormulaResponse(ok=True, result=result, conditions_passed=True).model_dump())
    except FormulaError as e:
        return ok(TestFormulaResponse(ok=False, error=explain(e)).model_dump())
    except ZeroDivisionError:
        return ok(TestFormulaResponse(
            ok=False, error="Division by zero — a value you divide by is 0 in the test values").model_dump())


@router.get("/slabs")
def get_slabs_route(
    state: str = Query(...),
    rule_type: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    return ok(_build_slabs_response(state, rule_type, db, entity).model_dump())


@router.post("/slabs")
def save_slabs(
    body: SlabSaveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):

    def _bucket(s) -> tuple:
        months = tuple(sorted(s.applicable_months)) if s.applicable_months else ()
        return ((s.gender or "ALL"), months, s.effective_from, s.effective_to)

    for idx, s in enumerate(body.slabs):
        if s.effective_from and s.effective_to and s.effective_to < s.effective_from:
            raise HTTPException(status_code=400, detail=f"Row {idx + 1}: effective_to precedes effective_from.")
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
                gender, months, effective_from, _effective_to = bucket
                tag = f"gender={gender}" + (f", months={list(months)}" if months else "")
                tag += f", from={effective_from}" if effective_from else ""
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Slabs overlap within {tag}: row {r.min_salary}-{r.max_salary} "
                        f"<= prev max {last_max}."
                    ),
                )
            last_max = r.max_salary

    db.query(SlabRule).filter(
        SlabRule.entity_id == entity.id,
        SlabRule.state == body.state,
        SlabRule.rule_type == body.rule_type,
    ).delete()

    gender_rank = {"ALL": 0, "MALE": 1, "FEMALE": 2}

    def _sort_key(s):
        return (
            gender_rank.get((s.gender or "ALL"), 9),
            1 if s.applicable_months else 0,
            s.effective_from.isoformat() if s.effective_from else "",
            float(s.min_salary),
        )

    for idx, s in enumerate(sorted(body.slabs, key=_sort_key)):
        db.add(
            SlabRule(
                user_id=user.id,
        entity_id=entity.id,
                state=body.state,
                rule_type=body.rule_type,
                min_salary=s.min_salary,
                max_salary=s.max_salary,
                deduction_amount=s.deduction_amount,
                employer_amount=s.employer_amount,
                frequency=s.frequency,
                gender=(s.gender or "ALL"),
                applicable_months=s.applicable_months,
                effective_from=s.effective_from,
                effective_to=s.effective_to,
                source_reference=s.source_reference,
                sort_order=idx,
            )
        )
    db.commit()

    return ok(_build_slabs_response(body.state, body.rule_type, db, entity).model_dump())


def _slab_kwargs(rule_type: str, state: str, idx: int, user_id, entity_id, s: dict) -> dict:
    return {
        "user_id": user_id,
        "entity_id": entity_id,
        "state": state,
        "rule_type": rule_type,
        "min_salary": s["min_salary"],
        "max_salary": s["max_salary"],
        "deduction_amount": s["deduction_amount"],
        "employer_amount": s.get("employer_amount"),
        "frequency": s["frequency"],
        "gender": s.get("gender", "ALL"),
        "applicable_months": s.get("applicable_months"),
        "effective_from": s.get("effective_from"),
        "effective_to": s.get("effective_to"),
        "source_reference": s.get("source_reference"),
        "sort_order": idx,
    }


@router.get("/slabs/configured-states")
def get_configured_states(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
    entity: Entity = Depends(get_current_entity),
):
    """The states PT and LWF are checked in for this company: the settings' state
    lists together with every state whose slabs have been saved."""
    settings = db.query(StatutorySettings).filter(StatutorySettings.entity_id == entity.id).first()
    out: dict[str, list[str]] = {
        "PT": list((settings.pt_states if settings else None) or []),
        "LWF": list((settings.lwf_states if settings else None) or []),
    }
    for rule_type, state in db.query(SlabRule.rule_type, SlabRule.state).filter(
            SlabRule.entity_id == entity.id).distinct():
        bucket = out.setdefault(rule_type, [])
        if state.casefold() not in {s.casefold() for s in bucket}:
            bucket.append(state)
    return ok({key: sorted(values) for key, values in out.items()})


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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
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
        db.query(SlabRule).filter(
            SlabRule.entity_id == entity.id,
            SlabRule.state == state,
            SlabRule.rule_type == rt,
        ).delete()

    for idx, s in enumerate(defaults):
        db.add(SlabRule(**_slab_kwargs(rt, state, idx, user.id, entity.id, s)))
    db.commit()
    return ok(_build_slabs_response(state, rt, db, entity).model_dump())


@router.post("/slabs/reset-defaults")
def reset_default_slabs(
    rule_type: str = Query(default="PT"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    rt = rule_type.upper()
    catalog, _get, _list = _defaults_for(rt)

    deleted = (
        db.query(SlabRule)
        .filter(SlabRule.entity_id == entity.id, SlabRule.rule_type == rt)
        .delete()
    )
    imported: dict[str, int] = {}
    for state, rows in catalog.items():
        for idx, s in enumerate(rows):
            db.add(SlabRule(**_slab_kwargs(rt, state, idx, user.id, entity.id, s)))
        imported[state] = len(rows)
    db.commit()
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    entity: Entity = Depends(require_entity_write),
):
    rt = rule_type.upper()
    catalog, _get, _list = _defaults_for(rt)

    imported: dict[str, int] = {}
    for state, rows in catalog.items():
        if overwrite:
            db.query(SlabRule).filter(
                SlabRule.entity_id == entity.id,
                SlabRule.state == state,
                SlabRule.rule_type == rt,
            ).delete()
        else:
            existing = (
                db.query(SlabRule)
                .filter(
                    SlabRule.entity_id == entity.id,
                    SlabRule.state == state,
                    SlabRule.rule_type == rt,
                )
                .count()
            )
            if existing:
                imported[state] = 0
                continue
        for idx, s in enumerate(rows):
            db.add(SlabRule(**_slab_kwargs(rt, state, idx, user.id, entity.id, s)))
        imported[state] = len(rows)
    db.commit()
    return ok(
        {
            "rule_type": rt,
            "imported": imported,
            "total_states": len([k for k, v in imported.items() if v]),
        }
    )
