from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field

from .base import ORMModel


class RegisterRequest(BaseModel):
    organization_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRead(ORMModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    is_active: bool


class RegisterResponse(BaseModel):
    user: UserRead
    organization_id: uuid.UUID
    organization_slug: str
    access_token: str
    token_type: str = "bearer"


class OrganizationSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan_key: str
    role: str


class MeResponse(BaseModel):
    user: UserRead
    organizations: list[OrganizationSummary]
    # Whether this user's email is in Settings.superadmin_emails -- gates
    # the /admin UI. Purely a UI convenience; the actual authorization check
    # is server-side on every /admin route (deps.require_superadmin).
    is_superadmin: bool
