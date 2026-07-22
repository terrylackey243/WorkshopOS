from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import require_superadmin
from ..models import Membership, Organization, Plan, User
from ..schemas.admin import AdminOrganizationRead, AdminPlanUpdateRequest

# Platform-operator-only routes: bypass the org-membership/tenant-isolation
# model entirely (see deps.require_superadmin) so a small, explicitly
# allow-listed set of emails can grant a plan directly -- e.g. comping a
# friend/tester, or covering an org manually while Stripe webhooks are still
# being finished. This never touches stripe_customer_id/stripe_subscription_id,
# so it can't be silently reverted by a later webhook: the subscription
# webhooks only ever act on orgs that already have a stripe_customer_id from
# a real checkout, which a comped org never gets.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_superadmin)])


async def _to_admin_read(session: AsyncSession, organization: Organization, plan: Plan) -> AdminOrganizationRead:
    owner_email = await session.scalar(
        select(User.email)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.organization_id == organization.id, Membership.role == "owner")
    )
    return AdminOrganizationRead(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        plan_key=plan.key,
        plan_name=plan.name,
        owner_email=owner_email,
        created_at=organization.created_at,
    )


@router.get("/organizations", response_model=list[AdminOrganizationRead])
async def list_organizations(
    search: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[AdminOrganizationRead]:
    stmt = (
        select(Organization, Plan, User.email)
        .join(Plan, Organization.plan_id == Plan.id)
        .outerjoin(
            Membership,
            (Membership.organization_id == Organization.id) & (Membership.role == "owner"),
        )
        .outerjoin(User, User.id == Membership.user_id)
        .order_by(Organization.name)
    )
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            Organization.name.ilike(pattern) | Organization.slug.ilike(pattern) | User.email.ilike(pattern)
        )

    rows = (await session.execute(stmt)).all()
    return [
        AdminOrganizationRead(
            id=organization.id,
            name=organization.name,
            slug=organization.slug,
            plan_key=plan.key,
            plan_name=plan.name,
            owner_email=owner_email,
            created_at=organization.created_at,
        )
        for organization, plan, owner_email in rows
    ]


@router.post("/organizations/{organization_id}/plan", response_model=AdminOrganizationRead)
async def set_organization_plan(
    organization_id: uuid.UUID,
    payload: AdminPlanUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> AdminOrganizationRead:
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    plan = await session.scalar(select(Plan).where(Plan.key == payload.plan_key))
    if plan is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown plan '{payload.plan_key}'.")

    organization.plan_id = plan.id
    await session.commit()
    await session.refresh(organization)

    return await _to_admin_read(session, organization, plan)
