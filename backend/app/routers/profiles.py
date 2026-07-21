from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_membership
from ..models import DrawerProfile, LabelStyleProfile, MagnetProfile, MaterialProfile, Membership, PrinterProfile
from ..schemas.profiles import (
    DrawerProfileCreate, DrawerProfileRead, DrawerProfileUpdate,
    LabelStyleProfileCreate, LabelStyleProfileRead, LabelStyleProfileUpdate,
    MagnetProfileCreate, MagnetProfileRead, MagnetProfileUpdate,
    MaterialProfileCreate, MaterialProfileRead, MaterialProfileUpdate,
    PrinterProfileCreate, PrinterProfileRead, PrinterProfileUpdate,
)

router = APIRouter(prefix="/organizations/{organization_id}/profiles", tags=["profiles"])

# Generic CRUD engine for the 5 per-organization profile/preset entities.
# Ported from Workshop-Designer/backend/app/routers/profiles.py's
# `_create`/`_list`/`_get`/`_patch`/`_delete`/`_default` shape (including the
# `is_default` single-flag-per-org semantics and IntegrityError->409 mapping),
# with one deliberate fix: `organization_id` is bound from the authenticated
# `get_current_membership` path dependency, never trusted from the request
# body or an unauthenticated query param like the old code did.


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A profile with this name already exists.") from exc


async def _create(model: Any, organization_id: uuid.UUID, payload: Any, session: AsyncSession):
    obj = model(organization_id=organization_id, **payload.model_dump())
    if obj.is_default:
        # Clear existing defaults BEFORE adding `obj` to the session. If this
        # ran after `session.add(obj)`, the session.execute() autoflush would
        # INSERT `obj` first, and this UPDATE's WHERE organization_id=...
        # would then catch (and immediately un-default) the row we just
        # created -- a real bug that existed in the old codebase's identical
        # _create pattern, caught here by test_printer_profile_crud_and_default_flip.
        await session.execute(
            update(model).where(model.organization_id == organization_id).values(is_default=False)
        )
    session.add(obj)
    await _commit(session)
    await session.refresh(obj)
    return obj


async def _list(model: Any, organization_id: uuid.UUID, session: AsyncSession):
    rows = await session.scalars(
        select(model)
        .where(model.organization_id == organization_id)
        .order_by(model.is_default.desc(), model.name)
    )
    return list(rows)


async def _get(model: Any, organization_id: uuid.UUID, profile_id: uuid.UUID, session: AsyncSession):
    obj = await session.scalar(
        select(model).where(model.id == profile_id, model.organization_id == organization_id)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return obj


async def _patch(
    model: Any, organization_id: uuid.UUID, profile_id: uuid.UUID, payload: Any, session: AsyncSession
):
    obj = await _get(model, organization_id, profile_id, session)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("is_default") is True:
        await session.execute(
            update(model)
            .where(model.organization_id == organization_id, model.id != obj.id)
            .values(is_default=False)
        )
    for key, value in changes.items():
        setattr(obj, key, value)
    await _commit(session)
    await session.refresh(obj)
    return obj


async def _delete(model: Any, organization_id: uuid.UUID, profile_id: uuid.UUID, session: AsyncSession):
    obj = await _get(model, organization_id, profile_id, session)
    await session.delete(obj)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _default(model: Any, organization_id: uuid.UUID, profile_id: uuid.UUID, session: AsyncSession):
    obj = await _get(model, organization_id, profile_id, session)
    await session.execute(
        update(model).where(model.organization_id == organization_id).values(is_default=False)
    )
    obj.is_default = True
    await session.commit()
    await session.refresh(obj)
    return obj


# --- Printers ------------------------------------------------------------------

@router.post("/printers", response_model=PrinterProfileRead, status_code=201)
async def create_printer(
    organization_id: uuid.UUID,
    payload: PrinterProfileCreate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _create(PrinterProfile, organization_id, payload, session)


@router.get("/printers", response_model=list[PrinterProfileRead])
async def list_printers(
    organization_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _list(PrinterProfile, organization_id, session)


@router.get("/printers/{profile_id}", response_model=PrinterProfileRead)
async def get_printer(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _get(PrinterProfile, organization_id, profile_id, session)


@router.patch("/printers/{profile_id}", response_model=PrinterProfileRead)
async def patch_printer(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    payload: PrinterProfileUpdate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _patch(PrinterProfile, organization_id, profile_id, payload, session)


@router.delete("/printers/{profile_id}", status_code=204)
async def delete_printer(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _delete(PrinterProfile, organization_id, profile_id, session)


@router.post("/printers/{profile_id}/default", response_model=PrinterProfileRead)
async def default_printer(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _default(PrinterProfile, organization_id, profile_id, session)


# --- Magnets ------------------------------------------------------------------

@router.post("/magnets", response_model=MagnetProfileRead, status_code=201)
async def create_magnet(
    organization_id: uuid.UUID,
    payload: MagnetProfileCreate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _create(MagnetProfile, organization_id, payload, session)


@router.get("/magnets", response_model=list[MagnetProfileRead])
async def list_magnets(
    organization_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _list(MagnetProfile, organization_id, session)


@router.get("/magnets/{profile_id}", response_model=MagnetProfileRead)
async def get_magnet(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _get(MagnetProfile, organization_id, profile_id, session)


@router.patch("/magnets/{profile_id}", response_model=MagnetProfileRead)
async def patch_magnet(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    payload: MagnetProfileUpdate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _patch(MagnetProfile, organization_id, profile_id, payload, session)


@router.delete("/magnets/{profile_id}", status_code=204)
async def delete_magnet(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _delete(MagnetProfile, organization_id, profile_id, session)


@router.post("/magnets/{profile_id}/default", response_model=MagnetProfileRead)
async def default_magnet(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _default(MagnetProfile, organization_id, profile_id, session)


# --- Materials ------------------------------------------------------------------

@router.post("/materials", response_model=MaterialProfileRead, status_code=201)
async def create_material(
    organization_id: uuid.UUID,
    payload: MaterialProfileCreate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _create(MaterialProfile, organization_id, payload, session)


@router.get("/materials", response_model=list[MaterialProfileRead])
async def list_materials(
    organization_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _list(MaterialProfile, organization_id, session)


@router.get("/materials/{profile_id}", response_model=MaterialProfileRead)
async def get_material(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _get(MaterialProfile, organization_id, profile_id, session)


@router.patch("/materials/{profile_id}", response_model=MaterialProfileRead)
async def patch_material(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    payload: MaterialProfileUpdate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _patch(MaterialProfile, organization_id, profile_id, payload, session)


@router.delete("/materials/{profile_id}", status_code=204)
async def delete_material(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _delete(MaterialProfile, organization_id, profile_id, session)


@router.post("/materials/{profile_id}/default", response_model=MaterialProfileRead)
async def default_material(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _default(MaterialProfile, organization_id, profile_id, session)


# --- Drawer profiles ------------------------------------------------------------------

@router.post("/drawer-profiles", response_model=DrawerProfileRead, status_code=201)
async def create_drawer_profile(
    organization_id: uuid.UUID,
    payload: DrawerProfileCreate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _create(DrawerProfile, organization_id, payload, session)


@router.get("/drawer-profiles", response_model=list[DrawerProfileRead])
async def list_drawer_profiles(
    organization_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _list(DrawerProfile, organization_id, session)


@router.get("/drawer-profiles/{profile_id}", response_model=DrawerProfileRead)
async def get_drawer_profile(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _get(DrawerProfile, organization_id, profile_id, session)


@router.patch("/drawer-profiles/{profile_id}", response_model=DrawerProfileRead)
async def patch_drawer_profile(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    payload: DrawerProfileUpdate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _patch(DrawerProfile, organization_id, profile_id, payload, session)


@router.delete("/drawer-profiles/{profile_id}", status_code=204)
async def delete_drawer_profile(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _delete(DrawerProfile, organization_id, profile_id, session)


@router.post("/drawer-profiles/{profile_id}/default", response_model=DrawerProfileRead)
async def default_drawer_profile(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _default(DrawerProfile, organization_id, profile_id, session)


# --- Label styles ------------------------------------------------------------------

@router.post("/label-styles", response_model=LabelStyleProfileRead, status_code=201)
async def create_label_style(
    organization_id: uuid.UUID,
    payload: LabelStyleProfileCreate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _create(LabelStyleProfile, organization_id, payload, session)


@router.get("/label-styles", response_model=list[LabelStyleProfileRead])
async def list_label_styles(
    organization_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _list(LabelStyleProfile, organization_id, session)


@router.get("/label-styles/{profile_id}", response_model=LabelStyleProfileRead)
async def get_label_style(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _get(LabelStyleProfile, organization_id, profile_id, session)


@router.patch("/label-styles/{profile_id}", response_model=LabelStyleProfileRead)
async def patch_label_style(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    payload: LabelStyleProfileUpdate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _patch(LabelStyleProfile, organization_id, profile_id, payload, session)


@router.delete("/label-styles/{profile_id}", status_code=204)
async def delete_label_style(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _delete(LabelStyleProfile, organization_id, profile_id, session)


@router.post("/label-styles/{profile_id}/default", response_model=LabelStyleProfileRead)
async def default_label_style(
    organization_id: uuid.UUID,
    profile_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
):
    return await _default(LabelStyleProfile, organization_id, profile_id, session)
