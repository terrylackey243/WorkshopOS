from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .base import ORMModel

RoadmapStatus = Literal["planned", "in_progress", "done"]


class RoadmapItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    status: RoadmapStatus = "planned"


class RoadmapItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: RoadmapStatus | None = None


class RoadmapItemRead(ORMModel):
    id: uuid.UUID
    title: str
    description: str | None
    status: str
    position: int
    created_at: datetime
    updated_at: datetime
