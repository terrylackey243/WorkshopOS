from __future__ import annotations

import csv
import io
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..deps import get_current_membership, get_current_organization
from ..models import Drawer, InsertDesign, Membership, Organization, Plan, Shop, Toolbox, Tool
from ..schemas.tool import (
    ToolCheckoutRequest,
    ToolCreate,
    ToolImportResult,
    ToolLocationRead,
    ToolRead,
    ToolUpdate,
)
from ..services.plan_limits import enforce_plan_limit

router = APIRouter(prefix="/organizations/{organization_id}/tools", tags=["tools"])
settings = get_settings()

# A name/category/manufacturer/sku/notes/quantity row is roughly 200 bytes,
# so this is thousands of rows -- generous for real use, small next to the
# STL upload endpoint's 25MB cap since this is plain text, not binary
# geometry. IMPORT_MAX_ROWS is a defensive ceiling independent of byte size,
# since a Pro/Enterprise org has no `max_tools` limit to naturally cap this
# the way Free's 100-tool limit does.
IMPORT_MAX_BYTES = 2 * 1024 * 1024
IMPORT_MAX_ROWS = 5000
IMPORT_COLUMNS = ("name", "category", "manufacturer", "sku", "notes", "quantity")

# Generous for a phone-camera photo, small next to the STL upload endpoint's
# 25MB cap since this is a photo, not a multi-part printable geometry file.
# Read fully into memory (unlike the chunked-write STL endpoint) -- 10MB is
# small enough to buffer, and there's no follow-up worker step to defer.
PHOTO_MAX_BYTES = 10 * 1024 * 1024
PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


async def _get_tool(session: AsyncSession, organization_id: uuid.UUID, tool_id: uuid.UUID) -> Tool:
    tool = await session.scalar(
        select(Tool).where(Tool.id == tool_id, Tool.organization_id == organization_id)
    )
    if tool is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found.")
    return tool


async def _validate_drawer(session: AsyncSession, organization_id: uuid.UUID, drawer_id: uuid.UUID) -> None:
    row = await session.scalar(
        select(Drawer.id)
        .join(Toolbox, Drawer.toolbox_id == Toolbox.id)
        .join(Shop, Toolbox.shop_id == Shop.id)
        .where(Drawer.id == drawer_id, Shop.organization_id == organization_id)
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown drawer_id for this organization.")


async def _validate_insert_design(session: AsyncSession, organization_id: uuid.UUID, insert_design_id: uuid.UUID) -> None:
    row = await session.scalar(
        select(InsertDesign.id).where(
            InsertDesign.id == insert_design_id, InsertDesign.organization_id == organization_id
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown insert_design_id for this organization."
        )


def _validate_insert_quantity(insert_quantity: int | None, quantity: int) -> None:
    if insert_quantity is not None and not (0 <= insert_quantity <= quantity):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="insert_quantity must be between 0 and quantity.",
        )


async def _attach_derived_fields(session: AsyncSession, tools: list[Tool]) -> None:
    """This codebase doesn't use SQLAlchemy ORM relationships anywhere -- so
    `Tool.location` (a derived shop/toolbox/drawer breadcrumb, not a real
    column) is computed here via one batch join query and attached as a
    plain instance attribute, same pattern as
    `drawer_layouts.py::_attach_placements`. `has_photo` is attached here too
    (cheap, no query needed) so every ToolRead-returning endpoint gets both
    derived fields from one call site."""
    if not tools:
        return
    drawer_ids = {tool.drawer_id for tool in tools if tool.drawer_id is not None}
    locations_by_drawer: dict[uuid.UUID, ToolLocationRead] = {}
    if drawer_ids:
        rows = await session.execute(
            select(
                Drawer.id,
                Shop.id,
                Shop.name,
                Toolbox.id,
                Toolbox.name,
                Drawer.name,
                Drawer.position_label,
            )
            .join(Toolbox, Drawer.toolbox_id == Toolbox.id)
            .join(Shop, Toolbox.shop_id == Shop.id)
            .where(Drawer.id.in_(drawer_ids))
        )
        for drawer_id, shop_id, shop_name, toolbox_id, toolbox_name, drawer_name, position_label in rows:
            locations_by_drawer[drawer_id] = ToolLocationRead(
                shop_id=shop_id,
                shop_name=shop_name,
                toolbox_id=toolbox_id,
                toolbox_name=toolbox_name,
                drawer_id=drawer_id,
                drawer_label=drawer_name or position_label or "Drawer",
            )
    for tool in tools:
        tool.location = (  # type: ignore[attr-defined]
            locations_by_drawer.get(tool.drawer_id) if tool.drawer_id is not None else None
        )
        tool.has_photo = tool.photo_path is not None  # type: ignore[attr-defined]


@router.post("", response_model=ToolRead, status_code=status.HTTP_201_CREATED)
async def create_tool(
    organization_id: uuid.UUID,
    payload: ToolCreate,
    organization: Organization = Depends(get_current_organization),
    session: AsyncSession = Depends(get_session),
) -> Tool:
    if payload.drawer_id is not None:
        await _validate_drawer(session, organization_id, payload.drawer_id)
    if payload.insert_design_id is not None:
        await _validate_insert_design(session, organization_id, payload.insert_design_id)

    insert_quantity = payload.insert_quantity
    if payload.insert_design_id is not None and insert_quantity is None:
        insert_quantity = 1
    _validate_insert_quantity(insert_quantity, payload.quantity)

    count_stmt = select(func.count()).select_from(Tool).where(Tool.organization_id == organization_id)
    await enforce_plan_limit(session, organization, "max_tools", count_stmt)

    data = payload.model_dump()
    data["insert_quantity"] = insert_quantity
    tool = Tool(organization_id=organization_id, **data)
    session.add(tool)
    await session.commit()
    await session.refresh(tool)
    await _attach_derived_fields(session, [tool])
    return tool


def _parse_import_row(row: dict, row_number: int) -> tuple[dict | None, str | None]:
    """Validates one CSV row against `ToolCreate`'s own constraints (kept in
    sync with schemas/tool.py by construction, not duplicated as separate
    literal limits). Returns (fields, None) on success or (None, message) on
    failure -- never partially-valid data, since a whole-file all-or-nothing
    import must be able to tell "every row checked out" from "something's
    wrong" with one boolean per row."""
    name = (row.get("name") or "").strip()
    if not name:
        return None, f"Row {row_number}: name is required."
    if len(name) > 200:
        return None, f"Row {row_number}: name is too long (max 200 characters)."

    category = (row.get("category") or "").strip() or None
    if category and len(category) > 100:
        return None, f"Row {row_number}: category is too long (max 100 characters)."

    manufacturer = (row.get("manufacturer") or "").strip() or None
    if manufacturer and len(manufacturer) > 200:
        return None, f"Row {row_number}: manufacturer is too long (max 200 characters)."

    sku = (row.get("sku") or "").strip() or None
    if sku and len(sku) > 100:
        return None, f"Row {row_number}: sku is too long (max 100 characters)."

    notes = (row.get("notes") or "").strip() or None
    if notes and len(notes) > 2000:
        return None, f"Row {row_number}: notes is too long (max 2000 characters)."

    quantity_raw = (row.get("quantity") or "").strip()
    if not quantity_raw:
        quantity = 1
    else:
        try:
            quantity = int(quantity_raw)
        except ValueError:
            return None, f"Row {row_number}: quantity {quantity_raw!r} is not a whole number."
        if quantity < 0:
            return None, f"Row {row_number}: quantity cannot be negative."

    return {
        "name": name,
        "category": category,
        "manufacturer": manufacturer,
        "sku": sku,
        "notes": notes,
        "quantity": quantity,
    }, None


@router.post("/import", response_model=ToolImportResult, status_code=status.HTTP_201_CREATED)
async def import_tools(
    organization_id: uuid.UUID,
    file: UploadFile = File(...),
    organization: Organization = Depends(get_current_organization),
    session: AsyncSession = Depends(get_session),
) -> ToolImportResult | JSONResponse:
    filename = file.filename or ""
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Uploaded file must have a .csv extension."
        )

    raw = await file.read()
    await file.close()
    if len(raw) > IMPORT_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {IMPORT_MAX_BYTES // (1024 * 1024)}MB upload limit.",
        )

    try:
        text = raw.decode("utf-8-sig")  # tolerate a BOM from Excel-exported CSVs
    except UnicodeDecodeError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="File must be UTF-8 text.")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="File has no header row.")
    # Case-insensitive header matching -- DictReader's own keys stay
    # whatever case the file used, so normalize once instead of at every
    # per-row lookup.
    header_map = {name.strip().lower(): name for name in reader.fieldnames if name}
    if "name" not in header_map:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="File is missing a required 'name' column."
        )

    parsed_rows: list[dict] = []
    errors: list[dict] = []
    row_number = 0
    for raw_row in reader:
        row_number += 1
        if row_number > IMPORT_MAX_ROWS:
            errors.append(
                {"row": None, "message": f"File exceeds the {IMPORT_MAX_ROWS}-row import limit."}
            )
            break
        normalized = {col: raw_row.get(header_map[col]) for col in IMPORT_COLUMNS if col in header_map}
        # A fully blank line (every cell empty) is normal CSV authoring
        # noise, not a row to reject -- skip it silently, same as any
        # spreadsheet tool would when re-exporting.
        if not any((v or "").strip() for v in normalized.values()):
            continue
        fields, error = _parse_import_row(normalized, row_number)
        if error:
            errors.append({"row": row_number, "message": error})
        else:
            assert fields is not None
            parsed_rows.append(fields)

    if not errors and parsed_rows:
        count_stmt = select(func.count()).select_from(Tool).where(Tool.organization_id == organization_id)
        current_count = await session.scalar(count_stmt)
        plan = await session.get(Plan, organization.plan_id)
        if plan is not None and plan.max_tools is not None:
            if (current_count or 0) + len(parsed_rows) > plan.max_tools:
                errors.append(
                    {
                        "row": None,
                        "message": (
                            f"Importing {len(parsed_rows)} tools would exceed plan '{plan.key}''s "
                            f"limit of {plan.max_tools} tools (you currently have {current_count}). "
                            "Remove rows or upgrade your plan."
                        ),
                    }
                )

    if errors:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "Import failed -- no tools were created.", "errors": errors},
        )

    if not parsed_rows:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="File has no data rows.")

    tools = [Tool(organization_id=organization_id, **fields) for fields in parsed_rows]
    session.add_all(tools)
    await session.commit()
    for tool in tools:
        await session.refresh(tool)
    await _attach_derived_fields(session, tools)

    return ToolImportResult(imported=len(tools), tools=tools)


@router.get("", response_model=list[ToolRead])
async def list_tools(
    organization_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> list[Tool]:
    rows = list(
        await session.scalars(
            select(Tool).where(Tool.organization_id == organization_id).order_by(Tool.name)
        )
    )
    await _attach_derived_fields(session, rows)
    return rows


@router.get("/{tool_id}", response_model=ToolRead)
async def get_tool(
    organization_id: uuid.UUID,
    tool_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Tool:
    tool = await _get_tool(session, organization_id, tool_id)
    await _attach_derived_fields(session, [tool])
    return tool


@router.patch("/{tool_id}", response_model=ToolRead)
async def update_tool(
    organization_id: uuid.UUID,
    tool_id: uuid.UUID,
    payload: ToolUpdate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Tool:
    tool = await _get_tool(session, organization_id, tool_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("drawer_id") is not None:
        await _validate_drawer(session, organization_id, changes["drawer_id"])
    if changes.get("insert_design_id") is not None:
        await _validate_insert_design(session, organization_id, changes["insert_design_id"])

    # PATCH may only touch one of insert_design_id/insert_quantity/quantity --
    # validate the EFFECTIVE post-update values (merge `changes` onto the
    # tool's current values), not just whatever happens to be in this payload.
    effective_insert_design_id = changes.get("insert_design_id", tool.insert_design_id)
    effective_quantity = changes.get("quantity", tool.quantity)
    effective_insert_quantity = changes.get("insert_quantity", tool.insert_quantity)
    if effective_insert_design_id is not None and effective_insert_quantity is None:
        effective_insert_quantity = 1
        changes["insert_quantity"] = 1
    _validate_insert_quantity(effective_insert_quantity, effective_quantity)

    for key, value in changes.items():
        setattr(tool, key, value)
    await session.commit()
    await session.refresh(tool)
    await _attach_derived_fields(session, [tool])
    return tool


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(
    organization_id: uuid.UUID,
    tool_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Response:
    tool = await _get_tool(session, organization_id, tool_id)
    await session.delete(tool)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _photo_dir(organization_id: uuid.UUID, tool_id: uuid.UUID) -> Path:
    return Path(settings.generated_files_dir) / str(organization_id) / "tools" / str(tool_id)


@router.post("/{tool_id}/photo", response_model=ToolRead, status_code=status.HTTP_201_CREATED)
async def upload_tool_photo(
    organization_id: uuid.UUID,
    tool_id: uuid.UUID,
    file: UploadFile = File(...),
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Tool:
    tool = await _get_tool(session, organization_id, tool_id)

    filename = file.filename or ""
    ext = Path(filename.lower()).suffix
    if ext not in PHOTO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Photo must be one of: {', '.join(PHOTO_EXTENSIONS)}.",
        )

    raw = await file.read()
    await file.close()
    if len(raw) > PHOTO_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Photo exceeds the {PHOTO_MAX_BYTES // (1024 * 1024)}MB upload limit.",
        )

    photo_dir = _photo_dir(organization_id, tool_id)
    photo_dir.mkdir(parents=True, exist_ok=True)

    # Replace semantics: one photo per tool. Remove any previously-stored
    # photo first (it may have a different extension than the new upload),
    # rather than leaving an orphaned file alongside the new one.
    if tool.photo_path:
        old_path = Path(tool.photo_path)
        if old_path.is_file():
            old_path.unlink()

    new_path = photo_dir / f"photo{ext}"
    new_path.write_bytes(raw)

    tool.photo_path = str(new_path)
    await session.commit()
    await session.refresh(tool)
    await _attach_derived_fields(session, [tool])
    return tool


@router.delete("/{tool_id}/photo", response_model=ToolRead)
async def delete_tool_photo(
    organization_id: uuid.UUID,
    tool_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Tool:
    tool = await _get_tool(session, organization_id, tool_id)
    if tool.photo_path:
        old_path = Path(tool.photo_path)
        if old_path.is_file():
            old_path.unlink()
        tool.photo_path = None
        await session.commit()
        await session.refresh(tool)
    await _attach_derived_fields(session, [tool])
    return tool


@router.get("/{tool_id}/photo")
async def get_tool_photo(
    organization_id: uuid.UUID,
    tool_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    tool = await _get_tool(session, organization_id, tool_id)
    if not tool.photo_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This tool has no photo.")
    path = Path(tool.photo_path)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This tool has no photo.")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@router.post("/{tool_id}/checkout", response_model=ToolRead)
async def checkout_tool(
    organization_id: uuid.UUID,
    tool_id: uuid.UUID,
    payload: ToolCheckoutRequest,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Tool:
    """Sets checked_out_to/checked_out_at/checkout_due_at together, never
    via plain PATCH -- keeps the three fields atomically consistent (see
    the model's own docstring for why)."""
    tool = await _get_tool(session, organization_id, tool_id)
    if tool.checked_out_to is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"This tool is already checked out to {tool.checked_out_to!r}.",
        )
    tool.checked_out_to = payload.checked_out_to
    tool.checked_out_at = datetime.now(timezone.utc)
    tool.checkout_due_at = payload.checkout_due_at
    await session.commit()
    await session.refresh(tool)
    await _attach_derived_fields(session, [tool])
    return tool


@router.post("/{tool_id}/return", response_model=ToolRead)
async def return_tool(
    organization_id: uuid.UUID,
    tool_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Tool:
    tool = await _get_tool(session, organization_id, tool_id)
    if tool.checked_out_to is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This tool is not currently checked out."
        )
    tool.checked_out_to = None
    tool.checked_out_at = None
    tool.checkout_due_at = None
    await session.commit()
    await session.refresh(tool)
    await _attach_derived_fields(session, [tool])
    return tool


@router.post("/{tool_id}/maintenance/mark-done", response_model=ToolRead)
async def mark_tool_maintenance_done(
    organization_id: uuid.UUID,
    tool_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Tool:
    tool = await _get_tool(session, organization_id, tool_id)
    tool.last_maintained_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(tool)
    await _attach_derived_fields(session, [tool])
    return tool
