from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models import RoadmapItem, User
from ..schemas.roadmap import RoadmapItemCreate, RoadmapItemRead, RoadmapItemUpdate

# Deliberately NOT nested under /organizations/{organization_id} -- this is a
# shared product roadmap (WorkshopOS's own development progress), not
# per-tenant data. Any authenticated user can view/manage it; there's no
# per-organization ownership to scope against. See app/models/roadmap.py.
router = APIRouter(prefix="/roadmap", tags=["roadmap"])


async def _get_item(session: AsyncSession, item_id: uuid.UUID) -> RoadmapItem:
    item = await session.get(RoadmapItem, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Roadmap item not found.")
    return item


@router.get("", response_model=list[RoadmapItemRead])
async def list_roadmap_items(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[RoadmapItem]:
    rows = await session.scalars(select(RoadmapItem).order_by(RoadmapItem.position))
    return list(rows)


@router.post("", response_model=RoadmapItemRead, status_code=status.HTTP_201_CREATED)
async def create_roadmap_item(
    payload: RoadmapItemCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RoadmapItem:
    max_position = await session.scalar(select(func.max(RoadmapItem.position)))
    item = RoadmapItem(
        title=payload.title,
        description=payload.description,
        status=payload.status,
        position=(max_position + 1) if max_position is not None else 0,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.patch("/{item_id}", response_model=RoadmapItemRead)
async def update_roadmap_item(
    item_id: uuid.UUID,
    payload: RoadmapItemUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RoadmapItem:
    item = await _get_item(session, item_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_roadmap_item(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    item = await _get_item(session, item_id)
    await session.delete(item)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _swap_with_neighbor(
    session: AsyncSession, item_id: uuid.UUID, *, direction: str
) -> RoadmapItem:
    item = await _get_item(session, item_id)
    comparator = RoadmapItem.position < item.position if direction == "up" else RoadmapItem.position > item.position
    order = RoadmapItem.position.desc() if direction == "up" else RoadmapItem.position.asc()
    neighbor = await session.scalar(
        select(RoadmapItem).where(comparator).order_by(order).limit(1)
    )
    if neighbor is not None:
        item.position, neighbor.position = neighbor.position, item.position
        await session.commit()
        await session.refresh(item)
    return item


@router.post("/{item_id}/move-up", response_model=RoadmapItemRead)
async def move_roadmap_item_up(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RoadmapItem:
    return await _swap_with_neighbor(session, item_id, direction="up")


@router.post("/{item_id}/move-down", response_model=RoadmapItemRead)
async def move_roadmap_item_down(
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RoadmapItem:
    return await _swap_with_neighbor(session, item_id, direction="down")
