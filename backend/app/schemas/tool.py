from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from .base import ORMModel


class ToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    manufacturer: str | None = Field(default=None, max_length=200)
    sku: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    drawer_id: uuid.UUID | None = None
    quantity: int = Field(default=1, ge=0)
    insert_design_id: uuid.UUID | None = None
    insert_quantity: int | None = Field(default=None, ge=0)
    maintenance_interval_days: int | None = Field(default=None, ge=1)


class ToolUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    manufacturer: str | None = Field(default=None, max_length=200)
    sku: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    drawer_id: uuid.UUID | None = None
    quantity: int | None = Field(default=None, ge=0)
    insert_design_id: uuid.UUID | None = None
    insert_quantity: int | None = Field(default=None, ge=0)
    maintenance_interval_days: int | None = Field(default=None, ge=1)


class ToolLocationRead(ORMModel):
    shop_id: uuid.UUID
    shop_name: str
    toolbox_id: uuid.UUID
    toolbox_name: str
    drawer_id: uuid.UUID
    drawer_label: str


class ToolRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    category: str | None
    manufacturer: str | None
    sku: str | None
    notes: str | None
    drawer_id: uuid.UUID | None
    quantity: int
    insert_design_id: uuid.UUID | None
    insert_quantity: int | None
    location: ToolLocationRead | None
    # Derived from `photo_path` (never expose the raw filesystem path) --
    # see `_attach_locations`-style "compute, don't store" attribute pattern
    # in routers/tools.py.
    has_photo: bool
    checked_out_to: str | None
    checked_out_at: datetime | None
    checkout_due_at: datetime | None
    maintenance_interval_days: int | None
    last_maintained_at: datetime | None


class ToolCheckoutRequest(BaseModel):
    checked_out_to: str = Field(min_length=1, max_length=200)
    checkout_due_at: datetime | None = None


class ToolImportRowError(BaseModel):
    # `row` is 1-based counting only data rows (header excluded); null for
    # errors that apply to the whole file rather than one row (e.g. a
    # plan-limit rejection).
    row: int | None
    message: str


class ToolImportResult(BaseModel):
    imported: int
    tools: list[ToolRead]
