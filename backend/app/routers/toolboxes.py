from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_membership, get_current_organization
from ..models import Membership, Organization, Shop, Toolbox
from ..schemas.shop import ToolboxCreate, ToolboxRead, ToolboxUpdate
from ..services.plan_limits import enforce_plan_limit

router = APIRouter(
    prefix="/organizations/{organization_id}/shops/{shop_id}/toolboxes", tags=["toolboxes"]
)


async def _get_shop(session: AsyncSession, organization_id: uuid.UUID, shop_id: uuid.UUID) -> Shop:
    shop = await session.scalar(
        select(Shop).where(Shop.id == shop_id, Shop.organization_id == organization_id)
    )
    if shop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found.")
    return shop


async def _get_toolbox(session: AsyncSession, shop_id: uuid.UUID, toolbox_id: uuid.UUID) -> Toolbox:
    toolbox = await session.scalar(
        select(Toolbox).where(Toolbox.id == toolbox_id, Toolbox.shop_id == shop_id)
    )
    if toolbox is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Toolbox not found.")
    return toolbox


@router.post("", response_model=ToolboxRead, status_code=status.HTTP_201_CREATED)
async def create_toolbox(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    payload: ToolboxCreate,
    organization: Organization = Depends(get_current_organization),
    session: AsyncSession = Depends(get_session),
) -> Toolbox:
    await _get_shop(session, organization_id, shop_id)

    count_stmt = (
        select(func.count())
        .select_from(Toolbox)
        .join(Shop, Toolbox.shop_id == Shop.id)
        .where(Shop.organization_id == organization_id)
    )
    await enforce_plan_limit(session, organization, "max_toolboxes", count_stmt)

    toolbox = Toolbox(shop_id=shop_id, **payload.model_dump())
    session.add(toolbox)
    await session.commit()
    await session.refresh(toolbox)
    return toolbox


@router.get("", response_model=list[ToolboxRead])
async def list_toolboxes(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> list[Toolbox]:
    await _get_shop(session, organization_id, shop_id)
    rows = await session.scalars(
        select(Toolbox).where(Toolbox.shop_id == shop_id).order_by(Toolbox.name)
    )
    return list(rows)


@router.get("/{toolbox_id}", response_model=ToolboxRead)
async def get_toolbox(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Toolbox:
    await _get_shop(session, organization_id, shop_id)
    return await _get_toolbox(session, shop_id, toolbox_id)


@router.patch("/{toolbox_id}", response_model=ToolboxRead)
async def update_toolbox(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    payload: ToolboxUpdate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Toolbox:
    await _get_shop(session, organization_id, shop_id)
    toolbox = await _get_toolbox(session, shop_id, toolbox_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(toolbox, key, value)
    await session.commit()
    await session.refresh(toolbox)
    return toolbox


@router.delete("/{toolbox_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_toolbox(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _get_shop(session, organization_id, shop_id)
    toolbox = await _get_toolbox(session, shop_id, toolbox_id)
    await session.delete(toolbox)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
