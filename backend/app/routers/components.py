import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.envelope import ok
from app.models import ComponentConfig, User
from app.schemas.component import ComponentCreate, ComponentOut, ComponentUpdate

router = APIRouter()


@router.get("")
def list_components(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        db.query(ComponentConfig)
        .filter(ComponentConfig.user_id == user.id)
        .order_by(ComponentConfig.component_name)
        .all()
    )
    return ok([ComponentOut.model_validate(r).model_dump() for r in rows])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_component(
    body: ComponentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    exists = (
        db.query(ComponentConfig)
        .filter(
            ComponentConfig.user_id == user.id,
            ComponentConfig.component_name.ilike(body.component_name.strip()),
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="Component name already exists")
    row = ComponentConfig(user_id=user.id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(ComponentOut.model_validate(row).model_dump())


@router.patch("/{component_id}")
def update_component(
    component_id: uuid.UUID,
    body: ComponentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(ComponentConfig)
        .filter(ComponentConfig.id == component_id, ComponentConfig.user_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    data = body.model_dump(exclude_unset=True)
    if "component_name" in data and data["component_name"]:
        clash = (
            db.query(ComponentConfig)
            .filter(
                ComponentConfig.user_id == user.id,
                ComponentConfig.component_name.ilike(data["component_name"].strip()),
                ComponentConfig.id != component_id,
            )
            .first()
        )
        if clash:
            raise HTTPException(status_code=400, detail="Component name already exists")
    for k, v in data.items():
        setattr(row, k, v)
    db.add(row)
    db.commit()
    db.refresh(row)
    return ok(ComponentOut.model_validate(row).model_dump())


@router.delete("/{component_id}")
def delete_component(
    component_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(ComponentConfig)
        .filter(ComponentConfig.id == component_id, ComponentConfig.user_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(row)
    db.commit()
    return ok({"deleted": str(component_id)})
