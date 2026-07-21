from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_membership, get_current_user
from ..models import Membership, Organization, Plan, User
from ..schemas.org import OrganizationDetailRead, OrganizationRead, PlanRead

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationRead])
async def list_my_organizations(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Organization]:
    rows = await session.execute(
        select(Organization)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == current_user.id)
    )
    return list(rows.scalars())


@router.get("/{organization_id}", response_model=OrganizationDetailRead)
async def get_organization(
    organization_id: uuid.UUID,
    # Presence of this dependency is the auth check: it 403s unless the
    # authenticated caller has a real Membership row for organization_id.
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> OrganizationDetailRead:
    organization = await session.get(Organization, organization_id)
    plan = await session.get(Plan, organization.plan_id)
    return OrganizationDetailRead(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        plan_id=organization.plan_id,
        plan=PlanRead.model_validate(plan),
        license_tier=organization.license_tier,
        license_activated_at=organization.license_activated_at,
    )
