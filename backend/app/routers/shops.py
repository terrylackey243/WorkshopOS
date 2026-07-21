from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_membership, get_current_organization
from ..models import Membership, Organization, Shop
from ..schemas.shop import ShopCreate, ShopRead, ShopUpdate
from ..services.plan_limits import enforce_plan_limit

router = APIRouter(prefix="/organizations/{organization_id}/shops", tags=["shops"])


async def _get_shop(session: AsyncSession, organization_id: uuid.UUID, shop_id: uuid.UUID) -> Shop:
    shop = await session.scalar(
        select(Shop).where(Shop.id == shop_id, Shop.organization_id == organization_id)
    )
    if shop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found.")
    return shop


@router.post("", response_model=ShopRead, status_code=status.HTTP_201_CREATED)
async def create_shop(
    organization_id: uuid.UUID,
    payload: ShopCreate,
    organization: Organization = Depends(get_current_organization),
    session: AsyncSession = Depends(get_session),
) -> Shop:
    count_stmt = select(func.count()).select_from(Shop).where(Shop.organization_id == organization_id)
    await enforce_plan_limit(session, organization, "max_shops", count_stmt)

    shop = Shop(organization_id=organization_id, **payload.model_dump())
    session.add(shop)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A shop with this slug already exists.") from exc
    await session.refresh(shop)
    return shop


@router.get("", response_model=list[ShopRead])
async def list_shops(
    organization_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> list[Shop]:
    rows = await session.scalars(
        select(Shop).where(Shop.organization_id == organization_id).order_by(Shop.name)
    )
    return list(rows)


@router.get("/{shop_id}", response_model=ShopRead)
async def get_shop(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Shop:
    return await _get_shop(session, organization_id, shop_id)


@router.patch("/{shop_id}", response_model=ShopRead)
async def update_shop(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    payload: ShopUpdate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Shop:
    shop = await _get_shop(session, organization_id, shop_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(shop, key, value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A shop with this slug already exists.") from exc
    await session.refresh(shop)
    return shop


@router.delete("/{shop_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shop(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Response:
    shop = await _get_shop(session, organization_id, shop_id)
    await session.delete(shop)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
