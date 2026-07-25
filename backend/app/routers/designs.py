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


async def _resolve_design_refs(
    session: AsyncSession,
    organization_id: uuid.UUID,
    label_style_profile_id: uuid.UUID,
    magnet_profile_id: uuid.UUID | None,
    shop_id: uuid.UUID | None,
    tool_id: uuid.UUID | None,
) -> tuple[LabelStyleProfile, MagnetProfile | None, str | None]:
    """Looks up and validates the profile/shop/tool references shared by
    `create_design` and `update_design`, and resolves the QR deep-link URL.
    Returns the label style, resolved magnet (falling back to the label
    style's own default when omitted), and QR url (None when no tool linked).
    """
    label_style = await session.scalar(
        select(LabelStyleProfile).where(
            LabelStyleProfile.id == label_style_profile_id,
            LabelStyleProfile.organization_id == organization_id,
        )
    )
    if label_style is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Label style profile not found.")

    resolved_magnet_id = magnet_profile_id or label_style.default_magnet_profile_id
    magnet: MagnetProfile | None = None
    if resolved_magnet_id is not None:
        magnet = await session.scalar(
            select(MagnetProfile).where(
                MagnetProfile.id == resolved_magnet_id,
                MagnetProfile.organization_id == organization_id,
            )
        )
        if magnet is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Magnet profile not found.")

    if shop_id is not None:
        shop = await session.scalar(
            select(Shop).where(Shop.id == shop_id, Shop.organization_id == organization_id)
        )
        if shop is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found.")

    qr_url: str | None = None
    if tool_id is not None:
        tool = await session.scalar(
            select(Tool).where(Tool.id == tool_id, Tool.organization_id == organization_id)
        )
        if tool is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found.")
        # Reuses `app_public_url`, added in the billing milestone for Stripe
        # redirect URLs -- same "where does this deployment's frontend live"
        # setting, no new config needed.
        qr_url = f"{settings.app_public_url}/tools/{tool.id}"

    return label_style, magnet, qr_url


@router.post("", response_model=DesignRead, status_code=status.HTTP_201_CREATED)
async def create_design(
    organization_id: uuid.UUID,
    payload: DesignCreate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Design:
    label_style, magnet, qr_url = await _resolve_design_refs(
        session,
        organization_id,
        payload.label_style_profile_id,
        payload.magnet_profile_id,
        payload.shop_id,
        payload.tool_id,
    )

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


@router.patch("/{design_id}", response_model=DesignRead)
async def update_design(
    organization_id: uuid.UUID,
    design_id: uuid.UUID,
    payload: DesignCreate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Design:
    """Edits an existing design's fields in place and re-enqueues generation
    -- every field here (text, label style, magnet, tool link) feeds
    `parameters_json`, so there's no way to change one without a new STL.
    Unlike `regenerate_design` (which re-derives params from the design's
    *existing* FKs), this first repoints those FKs at whatever the edit form
    submitted.
    """
    design = await _get_design(session, organization_id, design_id)

    label_style, magnet, qr_url = await _resolve_design_refs(
        session,
        organization_id,
        payload.label_style_profile_id,
        payload.magnet_profile_id,
        payload.shop_id,
        payload.tool_id,
    )

    params_dict = build_label_parameters(label_style, magnet, payload.text, qr_url=qr_url)
    try:
        engine_version, content_hash = compute_manifest_fields(params_dict)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    design.name = payload.name
    design.text = payload.text
    design.shop_id = payload.shop_id
    design.tool_id = payload.tool_id
    design.label_style_profile_id = label_style.id
    design.magnet_profile_id = magnet.id if magnet is not None else None
    design.parameters_json = params_dict
    design.engine_version = engine_version
    design.content_hash = content_hash
    design.status = "queued"
    design.error_message = None
    await session.commit()
    await session.refresh(design)

    generate_design.send(str(design.id))

    return design


@router.post("/{design_id}/regenerate", response_model=DesignRead)
async def regenerate_design(
    organization_id: uuid.UUID,
    design_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Design:
    """Re-derives `parameters_json` from the design's linked profiles' and
    tool's *current* field values (not the values at creation time) and
    re-enqueues generation. This is the only way an already-created design
    picks up an edit to its label style / magnet profile -- `parameters_json`
    is otherwise a frozen snapshot from `create_design`, by design (it's
    what `content_hash` is a checksum of), so profile edits never silently
    change what an existing design generates until this is called.

    Re-fetches by the design's own `label_style_profile_id`/`magnet_profile_id`
    FKs rather than re-running `create_design`'s default-magnet-profile
    fallback: those FKs already hold the resolved profile this design uses
    (including a real magnet profile the label style's default resolved to
    at creation), so this always reproduces the *same* profile selection
    with fresh values, never a different one.
    """
    design = await _get_design(session, organization_id, design_id)

    if design.label_style_profile_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This design's label style profile no longer exists.",
        )
    label_style = await session.scalar(
        select(LabelStyleProfile).where(
            LabelStyleProfile.id == design.label_style_profile_id,
            LabelStyleProfile.organization_id == organization_id,
        )
    )
    if label_style is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Label style profile not found.")

    magnet: MagnetProfile | None = None
    if design.magnet_profile_id is not None:
        magnet = await session.scalar(
            select(MagnetProfile).where(
                MagnetProfile.id == design.magnet_profile_id,
                MagnetProfile.organization_id == organization_id,
            )
        )
        if magnet is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Magnet profile not found.")

    qr_url: str | None = None
    if design.tool_id is not None:
        tool = await session.scalar(
            select(Tool).where(Tool.id == design.tool_id, Tool.organization_id == organization_id)
        )
        if tool is not None:
            qr_url = f"{settings.app_public_url}/tools/{tool.id}"

    params_dict = build_label_parameters(label_style, magnet, design.text, qr_url=qr_url)
    try:
        engine_version, content_hash = compute_manifest_fields(params_dict)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    design.parameters_json = params_dict
    design.engine_version = engine_version
    design.content_hash = content_hash
    design.status = "queued"
    design.error_message = None
    await session.commit()
    await session.refresh(design)

    generate_design.send(str(design.id))

    return design


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

    # This URL is stable across regenerations (same design_id/kind), but the
    # file it points at is overwritten in place every time -- FileResponse's
    # default Last-Modified/ETag headers with no Cache-Control let a browser
    # serve a stale cached copy for a design edited/regenerated after the
    # first view, without ever re-requesting it. `no-store` forces a fresh
    # fetch every time so the preview/download always reflects the current
    # generation, at the cost of re-downloading an unchanged file.
    return FileResponse(
        path, media_type="model/stl", filename=f"{kind}.stl", headers={"Cache-Control": "no-store"}
    )
