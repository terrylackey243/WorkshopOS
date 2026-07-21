from __future__ import annotations

import uuid
from datetime import datetime

from .base import ORMModel


class PlanRead(ORMModel):
    id: uuid.UUID
    key: str
    name: str
    max_shops: int | None
    max_toolboxes: int | None
    max_drawers: int | None
    max_tools: int | None
    max_users: int | None


class OrganizationRead(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    plan_id: uuid.UUID


class OrganizationDetailRead(OrganizationRead):
    plan: PlanRead
    # What the org's activated license claims (self-hosted only); distinct
    # from `plan.key`, which is also the Stripe-sync field on SaaS orgs.
    license_tier: str | None = None
    license_activated_at: datetime | None = None


class MembershipRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: str
