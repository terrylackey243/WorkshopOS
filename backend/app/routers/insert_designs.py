from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..deps import get_current_membership
from ..models import InsertDesign, MagnetProfile, Membership
from ..schemas.insert_design import BinCreate, InsertDesignRead
from ..services.bin_params import build_bin_parameters, compute_manifest_fields
from ..workers.tasks import generate_bin_design, process_uploaded_insert

router = APIRouter(prefix="/organizations/{organization_id}/insert-designs", tags=["insert-designs"])

settings = get_settings()

# Generous cap for real Gridfinity-scale community files (typically a few MB)
# while still bounding worst-case disk/parse cost for an untrusted upload.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024


async def _get_insert_design(
    session: AsyncSession, organization_id: uuid.UUID, insert_design_id: uuid.UUID
) -> InsertDesign:
    design = await session.scalar(
        select(InsertDesign).where(
            InsertDesign.id == insert_design_id, InsertDesign.organization_id == organization_id
        )
    )
    if design is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insert design not found.")
    return design


@router.post("/generate-bin", response_model=InsertDesignRead, status_code=status.HTTP_201_CREATED)
async def generate_bin_endpoint(
    organization_id: uuid.UUID,
    payload: BinCreate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> InsertDesign:
    magnet: MagnetProfile | None = None
    if payload.magnet_profile_id is not None:
        magnet = await session.scalar(
            select(MagnetProfile).where(
                MagnetProfile.id == payload.magnet_profile_id,
                MagnetProfile.organization_id == organization_id,
            )
        )
        if magnet is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Magnet profile not found.")

    params_dict = build_bin_parameters(
        grid_width_units=payload.grid_width_units,
        grid_depth_units=payload.grid_depth_units,
        height_units=payload.height_units,
        compartments_x=payload.compartments_x,
        compartments_y=payload.compartments_y,
        include_stacking_lip=payload.include_stacking_lip,
        magnet=magnet,
    )
    try:
        engine_version, content_hash, bounds = compute_manifest_fields(params_dict)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    insert_design = InsertDesign(
        organization_id=organization_id,
        name=payload.name,
        source="generated",
        parameters_json=params_dict,
        engine_version=engine_version,
        content_hash=content_hash,
        bounds_json=bounds,
        status="queued",
    )
    session.add(insert_design)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Could not create insert design.") from exc
    await session.refresh(insert_design)

    # Only the heavy CSG step is deferred to the worker -- parameters were
    # already validated and hashed synchronously above.
    generate_bin_design.send(str(insert_design.id))

    return insert_design


@router.post("/upload", response_model=InsertDesignRead, status_code=status.HTTP_201_CREATED)
async def upload_insert_design(
    organization_id: uuid.UUID,
    name: str = Form(...),
    file: UploadFile = File(...),
    source_reference: str | None = Form(None),
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> InsertDesign:
    # Don't trust Content-Type -- browsers/OSes are inconsistent about what
    # they send for STL, and there's no officially registered MIME type for
    # it. The filename extension is the only reliable signal available here.
    filename = file.filename or ""
    if not filename.lower().endswith(".stl"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Uploaded file must have a .stl extension."
        )

    insert_design = InsertDesign(
        organization_id=organization_id,
        name=name,
        source="upload",
        source_reference=source_reference,
        status="queued",
    )
    session.add(insert_design)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Could not create insert design.") from exc
    await session.refresh(insert_design)

    design_dir = Path(settings.generated_files_dir) / str(organization_id) / str(insert_design.id)
    design_dir.mkdir(parents=True, exist_ok=True)
    upload_path = design_dir / "upload.stl"

    total_bytes = 0
    try:
        with upload_path.open("wb") as out_file:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="File exceeds the 25MB upload limit.",
                    )
                out_file.write(chunk)
    except HTTPException:
        shutil.rmtree(design_dir, ignore_errors=True)
        await session.delete(insert_design)
        await session.commit()
        raise
    finally:
        await file.close()

    insert_design.stl_path = str(upload_path)
    await session.commit()
    await session.refresh(insert_design)

    # Heavy lifting (parsing untrusted mesh geometry, computing bounds) is
    # deferred to the worker -- mirrors generate_bin_endpoint's "validate/
    # persist cheaply now, defer heavy work" shape.
    process_uploaded_insert.send(str(insert_design.id))

    return insert_design


@router.get("", response_model=list[InsertDesignRead])
async def list_insert_designs(
    organization_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> list[InsertDesign]:
    rows = await session.scalars(
        select(InsertDesign)
        .where(InsertDesign.organization_id == organization_id)
        .order_by(InsertDesign.created_at.desc())
    )
    return list(rows)


@router.get("/{insert_design_id}", response_model=InsertDesignRead)
async def get_insert_design(
    organization_id: uuid.UUID,
    insert_design_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> InsertDesign:
    return await _get_insert_design(session, organization_id, insert_design_id)


@router.delete("/{insert_design_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_insert_design(
    organization_id: uuid.UUID,
    insert_design_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Response:
    insert_design = await _get_insert_design(session, organization_id, insert_design_id)
    await session.delete(insert_design)
    await session.commit()

    design_dir = Path(settings.generated_files_dir) / str(organization_id) / str(insert_design_id)
    shutil.rmtree(design_dir, ignore_errors=True)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{insert_design_id}/file")
async def get_insert_design_file(
    organization_id: uuid.UUID,
    insert_design_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    insert_design = await _get_insert_design(session, organization_id, insert_design_id)
    if insert_design.status != "generated" or not insert_design.stl_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated file not available yet.")

    path = Path(insert_design.stl_path)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated file not available yet.")

    return FileResponse(path, media_type="model/stl", filename="bin.stl")
