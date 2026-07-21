from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from .base import ORMModel


class BinCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    grid_width_units: int = Field(ge=1)
    grid_depth_units: int = Field(ge=1)
    height_units: int = Field(ge=1)
    compartments_x: int = Field(default=1, ge=1)
    compartments_y: int = Field(default=1, ge=1)
    include_stacking_lip: bool = True
    magnet_profile_id: uuid.UUID | None = None


class InsertDesignRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    source: str
    source_reference: str | None
    parameters_json: dict | None
    engine_version: str | None
    content_hash: str | None
    status: str
    error_message: str | None
    stl_path: str | None
    bounds_json: dict | None
    generated_at: datetime | None
    created_at: datetime
    updated_at: datetime
