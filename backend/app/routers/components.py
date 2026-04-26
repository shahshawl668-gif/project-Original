import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import ComponentConfig, User
from app.schemas.component import ComponentCreate, ComponentOut, ComponentUpdate

router = APIRouter()


@router.get("", response_model=list[ComponentOut])
def list_components(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return (
        db.query(ComponentConfig)
        .filter(ComponentConfig.user_id == user.id)
        .order_by(ComponentConfig.component_name)
        .all()
    )


@router.post("", response_model=ComponentOut, status_code=status.HTTP_201_CREATED)
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
    return row


@router.patch("/{component_id}", response_model=ComponentOut)
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
    return row


@router.delete("/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_component(
    component_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    row = (
        db.query(ComponentConfig)
        .filter(ComponentConfig.id == component_id, ComponentConfig.user_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
