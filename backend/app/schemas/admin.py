from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from .base import ORMModel


class AdminOrganizationRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    plan_key: str
    plan_name: str
    # Every org has exactly one owner today (no member-invite/promote route
    # exists yet -- see ARCHITECTURE.md), so this is unambiguous.
    owner_email: str | None
    created_at: datetime


class AdminPlanUpdateRequest(BaseModel):
    plan_key: str = Field(min_length=1, max_length=50)
