from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..deps import get_current_membership
from ..models import Design, LabelStyleProfile, MagnetProfile, Membership, Shop, Tool
from ..schemas.design import DesignCreate, DesignRead
from ..services.label_params import build_label_parameters, compute_manifest_fields
from ..workers.tasks import generate_design

router = APIRouter(prefix="/organizations/{organization_id}/designs", tags=["designs"])

settings = get_settings()


async def _get_design(session: AsyncSession, organization_id: uuid.UUID, design_id: uuid.UUID) -> Design:
    design = await session.scalar(
        select(Design).where(Design.id == design_id, Design.organization_id == organization_id)
    )
    if design is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Design not found.")
    return design


@router.post("", response_model=DesignRead, status_code=status.HTTP_201_CREATED)
async def create_design(
    organization_id: uuid.UUID,
    payload: DesignCreate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Design:
    label_style = await session.scalar(
        select(LabelStyleProfile).where(
            LabelStyleProfile.id == payload.label_style_profile_id,
            LabelStyleProfile.organization_id == organization_id,
        )
    )
    if label_style is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Label style profile not found.")

    magnet_profile_id = payload.magnet_profile_id or label_style.default_magnet_profile_id
    magnet: MagnetProfile | None = None
    if magnet_profile_id is not None:
        magnet = await session.scalar(
            select(MagnetProfile).where(
                MagnetProfile.id == magnet_profile_id,
                MagnetProfile.organization_id == organization_id,
            )
        )
        if magnet is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Magnet profile not found.")

    if payload.shop_id is not None:
        shop = await session.scalar(
            select(Shop).where(Shop.id == payload.shop_id, Shop.organization_id == organization_id)
        )
        if shop is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found.")

    qr_url: str | None = None
    if payload.tool_id is not None:
        tool = await session.scalar(
            select(Tool).where(Tool.id == payload.tool_id, Tool.organization_id == organization_id)
        )
        if tool is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found.")
        # Reuses `app_public_url`, added in the billing milestone for Stripe
        # redirect URLs -- same "where does this deployment's frontend live"
        # setting, no new config needed.
        qr_url = f"{settings.app_public_url}/tools/{tool.id}"

    params_dict = build_label_parameters(label_style, magnet, payload.text, qr_url=qr_url)
    try:
        engine_version, content_hash = compute_manifest_fields(params_dict)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    design = Design(
        organization_id=organization_id,
        shop_id=payload.shop_id,
        tool_id=payload.tool_id,
        name=payload.name,
        text=payload.text,
        label_style_profile_id=label_style.id,
        magnet_profile_id=magnet.id if magnet is not None else None,
        parameters_json=params_dict,
        engine_version=engine_version,
        content_hash=content_hash,
        status="queued",
    )
    session.add(design)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Could not create design.") from exc
    await session.refresh(design)

    # Only the heavy CSG step is deferred to the worker -- parameters were
    # already validated and hashed synchronously above.
    generate_design.send(str(design.id))

    return design


@router.get("", response_model=list[DesignRead])
async def list_designs(
    organization_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> list[Design]:
    rows = await session.scalars(
        select(Design).where(Design.organization_id == organization_id).order_by(Design.created_at.desc())
    )
    return list(rows)


@router.get("/{design_id}", response_model=DesignRead)
async def get_design(
    organization_id: uuid.UUID,
    design_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Design:
    return await _get_design(session, organization_id, design_id)


@router.delete("/{design_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_design(
    organization_id: uuid.UUID,
    design_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Response:
    design = await _get_design(session, organization_id, design_id)
    await session.delete(design)
    await session.commit()

    design_dir = Path(settings.generated_files_dir) / str(organization_id) / str(design_id)
    shutil.rmtree(design_dir, ignore_errors=True)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


_FILE_PATHS = {
    "outline": lambda d: d.outline_stl_path,
    "text": lambda d: d.text_stl_path,
    "qr": lambda d: d.qr_stl_path,
}


@router.get("/{design_id}/files/{kind}")
async def get_design_file(
    organization_id: uuid.UUID,
    design_id: uuid.UUID,
    kind: Literal["outline", "text", "qr"],
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    design = await _get_design(session, organization_id, design_id)
    path_str = _FILE_PATHS[kind](design)
    if design.status != "generated" or not path_str:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated file not available yet.")

    path = Path(path_str)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated file not available yet.")

    return FileResponse(path, media_type="model/stl", filename=f"{kind}.stl")
