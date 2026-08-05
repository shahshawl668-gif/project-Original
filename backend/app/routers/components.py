import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.database import Database

from app.database import get_db
from app.deps import get_current_user
from app.envelope import ok
from app.models import ComponentConfig, User
from app.schemas.component import ComponentCreate, ComponentOut, ComponentUpdate

router = APIRouter()


def _name_matches(name: str) -> dict:
    """Case-insensitive exact-name filter (replaces SQL ILIKE)."""
    return {"$regex": f"^{re.escape(name.strip())}$", "$options": "i"}


@router.get("")
def list_components(db: Database = Depends(get_db), user: User = Depends(get_current_user)):
    rows = ComponentConfig.find_many(
        db, {"user_id": user.id}, sort=[("component_name", 1)]
    )
    return ok([ComponentOut.model_validate(r).model_dump() for r in rows])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_component(
    body: ComponentCreate,
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    exists = ComponentConfig.find_one(
        db, {"user_id": user.id, "component_name": _name_matches(body.component_name)}
    )
    if exists:
        raise HTTPException(status_code=400, detail="Component name already exists")
    row = ComponentConfig(user_id=user.id, **body.model_dump())
    row.insert(db)
    return ok(ComponentOut.model_validate(row).model_dump())


@router.patch("/{component_id}")
def update_component(
    component_id: uuid.UUID,
    body: ComponentUpdate,
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = ComponentConfig.find_one(db, {"_id": component_id, "user_id": user.id})
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    data = body.model_dump(exclude_unset=True)
    if data.get("component_name"):
        clash = ComponentConfig.find_one(
            db,
            {
                "user_id": user.id,
                "component_name": _name_matches(data["component_name"]),
                "_id": {"$ne": component_id},
            },
        )
        if clash:
            raise HTTPException(status_code=400, detail="Component name already exists")
    for k, v in data.items():
        setattr(row, k, v)
    row.save(db)
    return ok(ComponentOut.model_validate(row).model_dump())


@router.delete("/{component_id}")
def delete_component(
    component_id: uuid.UUID,
    db: Database = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deleted = ComponentConfig.delete_one(db, {"_id": component_id, "user_id": user.id})
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found")
    return ok({"deleted": str(component_id)})
