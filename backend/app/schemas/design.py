from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from .base import ORMModel


class DesignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=500)
    label_style_profile_id: uuid.UUID
    # If omitted, falls back to the label style's own `default_magnet_profile_id`.
    magnet_profile_id: uuid.UUID | None = None
    shop_id: uuid.UUID | None = None
    # Optional -- when set, generation also produces a QR-code body encoding
    # a deep link to that tool's page. See workshop_geometry.label_engine.
    tool_id: uuid.UUID | None = None


class DesignRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    shop_id: uuid.UUID | None
    tool_id: uuid.UUID | None
    name: str
    text: str
    label_style_profile_id: uuid.UUID | None
    magnet_profile_id: uuid.UUID | None
    parameters_json: dict
    engine_version: str
    content_hash: str
    status: str
    error_message: str | None
    outline_stl_path: str | None
    text_stl_path: str | None
    qr_stl_path: str | None
    threemf_path: str | None
    generated_at: datetime | None
    created_at: datetime
    updated_at: datetime
