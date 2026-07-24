from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_membership, get_current_organization
from ..models import Drawer, DrawerProfile, Membership, Organization, Shop, Toolbox
from ..schemas.shop import DrawerCreate, DrawerRead, DrawerUpdate
from ..services.plan_limits import enforce_plan_limit

router = APIRouter(
    prefix="/organizations/{organization_id}/shops/{shop_id}/toolboxes/{toolbox_id}/drawers",
    tags=["drawers"],
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


async def _get_drawer(session: AsyncSession, toolbox_id: uuid.UUID, drawer_id: uuid.UUID) -> Drawer:
    drawer = await session.scalar(
        select(Drawer).where(Drawer.id == drawer_id, Drawer.toolbox_id == toolbox_id)
    )
    if drawer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drawer not found.")
    return drawer


async def _validate_drawer_profile(session: AsyncSession, organization_id: uuid.UUID, drawer_profile_id: uuid.UUID) -> None:
    profile = await session.scalar(
        select(DrawerProfile.id).where(
            DrawerProfile.id == drawer_profile_id, DrawerProfile.organization_id == organization_id
        )
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown drawer_profile_id for this organization.")


async def _next_order_in_row(session: AsyncSession, toolbox_id: uuid.UUID, row: int | None) -> int | None:
    """Append-to-end position within a (toolbox, row) group, or None if unplaced."""
    if row is None:
        return None
    max_order = await session.scalar(
        select(func.max(Drawer.order_in_row)).where(Drawer.toolbox_id == toolbox_id, Drawer.row == row)
    )
    return (max_order + 1) if max_order is not None else 0


@router.post("", response_model=DrawerRead, status_code=status.HTTP_201_CREATED)
async def create_drawer(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    payload: DrawerCreate,
    organization: Organization = Depends(get_current_organization),
    session: AsyncSession = Depends(get_session),
) -> Drawer:
    await _get_shop(session, organization_id, shop_id)
    await _get_toolbox(session, shop_id, toolbox_id)
    await _validate_drawer_profile(session, organization_id, payload.drawer_profile_id)

    count_stmt = (
        select(func.count())
        .select_from(Drawer)
        .join(Toolbox, Drawer.toolbox_id == Toolbox.id)
        .join(Shop, Toolbox.shop_id == Shop.id)
        .where(Shop.organization_id == organization_id)
    )
    await enforce_plan_limit(session, organization, "max_drawers", count_stmt)

    order_in_row = await _next_order_in_row(session, toolbox_id, payload.row)
    drawer = Drawer(toolbox_id=toolbox_id, order_in_row=order_in_row, **payload.model_dump())
    session.add(drawer)
    await session.commit()
    await session.refresh(drawer)
    return drawer


@router.get("", response_model=list[DrawerRead])
async def list_drawers(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> list[Drawer]:
    await _get_shop(session, organization_id, shop_id)
    await _get_toolbox(session, shop_id, toolbox_id)
    rows = await session.scalars(
        select(Drawer)
        .where(Drawer.toolbox_id == toolbox_id)
        .order_by(Drawer.row.asc().nulls_last(), Drawer.order_in_row.asc().nulls_last())
    )
    return list(rows)


@router.get("/{drawer_id}", response_model=DrawerRead)
async def get_drawer(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    drawer_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Drawer:
    await _get_shop(session, organization_id, shop_id)
    await _get_toolbox(session, shop_id, toolbox_id)
    return await _get_drawer(session, toolbox_id, drawer_id)


@router.patch("/{drawer_id}", response_model=DrawerRead)
async def update_drawer(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    drawer_id: uuid.UUID,
    payload: DrawerUpdate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Drawer:
    await _get_shop(session, organization_id, shop_id)
    await _get_toolbox(session, shop_id, toolbox_id)
    drawer = await _get_drawer(session, toolbox_id, drawer_id)

    changes = payload.model_dump(exclude_unset=True)
    if "drawer_profile_id" in changes and changes["drawer_profile_id"] is not None:
        await _validate_drawer_profile(session, organization_id, changes["drawer_profile_id"])
    if "row" in changes and changes["row"] != drawer.row:
        drawer.order_in_row = await _next_order_in_row(session, toolbox_id, changes["row"])
    for key, value in changes.items():
        setattr(drawer, key, value)
    await session.commit()
    await session.refresh(drawer)
    return drawer


@router.delete("/{drawer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_drawer(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    drawer_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _get_shop(session, organization_id, shop_id)
    await _get_toolbox(session, shop_id, toolbox_id)
    drawer = await _get_drawer(session, toolbox_id, drawer_id)
    await session.delete(drawer)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _swap_within_row(
    session: AsyncSession, toolbox_id: uuid.UUID, drawer_id: uuid.UUID, *, direction: str
) -> Drawer:
    drawer = await _get_drawer(session, toolbox_id, drawer_id)
    if drawer.row is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Drawer has no row assigned.")
    comparator = (
        Drawer.order_in_row < drawer.order_in_row
        if direction == "left"
        else Drawer.order_in_row > drawer.order_in_row
    )
    order = Drawer.order_in_row.desc() if direction == "left" else Drawer.order_in_row.asc()
    neighbor = await session.scalar(
        select(Drawer)
        .where(Drawer.toolbox_id == toolbox_id, Drawer.row == drawer.row, comparator)
        .order_by(order)
        .limit(1)
    )
    if neighbor is not None:
        drawer.order_in_row, neighbor.order_in_row = neighbor.order_in_row, drawer.order_in_row
        await session.commit()
        await session.refresh(drawer)
    return drawer


@router.post("/{drawer_id}/move-left", response_model=DrawerRead)
async def move_drawer_left(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    drawer_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Drawer:
    await _get_shop(session, organization_id, shop_id)
    await _get_toolbox(session, shop_id, toolbox_id)
    return await _swap_within_row(session, toolbox_id, drawer_id, direction="left")


@router.post("/{drawer_id}/move-right", response_model=DrawerRead)
async def move_drawer_right(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    drawer_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Drawer:
    await _get_shop(session, organization_id, shop_id)
    await _get_toolbox(session, shop_id, toolbox_id)
    return await _swap_within_row(session, toolbox_id, drawer_id, direction="right")
