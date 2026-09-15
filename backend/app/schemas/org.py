from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EntityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    code: str | None = Field(default=None, max_length=64)
    pf_establishment_code: str | None = Field(default=None, max_length=64)
    esic_employer_code: str | None = Field(default=None, max_length=64)
    tan: str | None = Field(default=None, max_length=16)
    pan: str | None = Field(default=None, max_length=16)
    cin: str | None = Field(default=None, max_length=32)
    primary_state: str | None = Field(default=None, max_length=100)


class EntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    pf_establishment_code: str | None = Field(default=None, max_length=64)
    esic_employer_code: str | None = Field(default=None, max_length=64)
    tan: str | None = Field(default=None, max_length=16)
    pan: str | None = Field(default=None, max_length=16)
    cin: str | None = Field(default=None, max_length=32)
    primary_state: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class EntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    legal_name: str | None
    code: str
    pf_establishment_code: str | None
    esic_employer_code: str | None
    tan: str | None
    pan: str | None
    cin: str | None
    primary_state: str | None
    is_active: bool
    created_at: datetime | None


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    org_type: str
    created_at: datetime | None


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    org_type: str | None = Field(default=None, pattern="^(practice|enterprise)$")


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    role: str
    email: str | None = None


class ContextOut(BaseModel):
    """Everything the client needs to render the entity switcher on first load."""

    organization: OrganizationOut | None
    role: str | None
    active_entity: EntityOut | None
    entities: list[EntityOut]
