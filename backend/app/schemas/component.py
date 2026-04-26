import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ComponentBase(BaseModel):
    component_name: str = Field(max_length=100)
    pf_applicable: bool = False
    esic_applicable: bool = False
    pt_applicable: bool = False
    lwf_applicable: bool = False
    bonus_applicable: bool = False
    included_in_wages: bool = False
    taxable: bool = False
    tax_exemption_type: str = Field(default="none", max_length=20)


class ComponentCreate(ComponentBase):
    pass


class ComponentUpdate(BaseModel):
    component_name: str | None = Field(default=None, max_length=100)
    pf_applicable: bool | None = None
    esic_applicable: bool | None = None
    pt_applicable: bool | None = None
    lwf_applicable: bool | None = None
    bonus_applicable: bool | None = None
    included_in_wages: bool | None = None
    taxable: bool | None = None
    tax_exemption_type: str | None = Field(default=None, max_length=20)


class ComponentOut(ComponentBase):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
