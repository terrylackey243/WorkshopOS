from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from .base import ORMModel


class ShopCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=120)
    location: str | None = Field(default=None, max_length=300)


class ShopUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=120)
    location: str | None = Field(default=None, max_length=300)


class ShopRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    location: str | None


class ToolboxCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class ToolboxUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class ToolboxRead(ORMModel):
    id: uuid.UUID
    shop_id: uuid.UUID
    name: str
    kind: str | None
    notes: str | None


class DrawerCreate(BaseModel):
    drawer_profile_id: uuid.UUID
    name: str | None = Field(default=None, max_length=200)
    position_label: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class DrawerUpdate(BaseModel):
    drawer_profile_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=200)
    position_label: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class DrawerRead(ORMModel):
    id: uuid.UUID
    toolbox_id: uuid.UUID
    drawer_profile_id: uuid.UUID
    name: str | None
    position_label: str | None
    notes: str | None
