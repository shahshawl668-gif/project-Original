from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.auth import UserOut

router = APIRouter()


class UserProfileUpdate(BaseModel):
    company_name: str | None = None


@router.patch("/me", response_model=UserOut)
def update_me(
    body: UserProfileUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.company_name is not None:
        user.company_name = body.company_name
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
