from __future__ import annotations

import json
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..deps import get_current_membership
from ..models import (
    Design,
    Drawer,
    DrawerLayout,
    DrawerProfile,
    InsertDesign,
    LabelStyleProfile,
    MagnetProfile,
    MaterialProfile,
    Membership,
    PrinterProfile,
    Shop,
    Tool,
    Toolbox,
)
from ..schemas.design import DesignRead
from ..schemas.drawer_layout import DrawerLayoutRead
from ..schemas.insert_design import InsertDesignRead
from ..schemas.profiles import (
    DrawerProfileRead,
    LabelStyleProfileRead,
    MagnetProfileRead,
    MaterialProfileRead,
    PrinterProfileRead,
)
from ..schemas.shop import DrawerRead, ShopRead, ToolboxRead
from ..schemas.tool import ToolRead

router = APIRouter(prefix="/organizations/{organization_id}/export", tags=["export"])
settings = get_settings()


def _add_file_to_zip(zf: zipfile.ZipFile, path_str: str | None, base_dir: Path) -> None:
    """Missing files on disk are skipped, not a hard failure for the whole
    export -- matches this app's established defensive `.is_file()`-check-
    before-serving pattern used everywhere else files are served."""
    if not path_str:
        return
    path = Path(path_str)
    if not path.is_file():
        return
    try:
        arcname = Path("files") / path.relative_to(base_dir)
    except ValueError:
        arcname = Path("files") / path.name
    zf.write(path, arcname=str(arcname))


@router.get("")
async def export_organization(
    organization_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Full org data snapshot as a ZIP -- independent of Docker volume
    backups, especially for self-hosted deployments without an off-box
    backup story. Manual/on-demand only (no scheduling mechanism exists
    anywhere in this app); synchronous, not a Dramatiq job, since this is a
    rare operator-initiated action on realistic (dozens-to-low-hundreds of
    small STL files) org sizes, not a hot path.

    `data.json` reuses each entity's existing `*Read` Pydantic schema rather
    than inventing an export-specific shape. `Tool`/`DrawerLayout` need
    their derived fields (location/has_photo, placements) attached first --
    same "query separately, attach as instance attribute" convention this
    codebase uses everywhere instead of ORM relationships.
    """
    from ..routers.drawer_layouts import _attach_placements
    from ..routers.tools import _attach_derived_fields

    base_dir = Path(settings.generated_files_dir)

    shops = list(await session.scalars(select(Shop).where(Shop.organization_id == organization_id)))
    toolboxes = list(
        await session.scalars(
            select(Toolbox).join(Shop, Toolbox.shop_id == Shop.id).where(Shop.organization_id == organization_id)
        )
    )
    drawers = list(
        await session.scalars(
            select(Drawer)
            .join(Toolbox, Drawer.toolbox_id == Toolbox.id)
            .join(Shop, Toolbox.shop_id == Shop.id)
            .where(Shop.organization_id == organization_id)
        )
    )
    drawer_profiles = list(
        await session.scalars(select(DrawerProfile).where(DrawerProfile.organization_id == organization_id))
    )
    printer_profiles = list(
        await session.scalars(select(PrinterProfile).where(PrinterProfile.organization_id == organization_id))
    )
    magnet_profiles = list(
        await session.scalars(select(MagnetProfile).where(MagnetProfile.organization_id == organization_id))
    )
    material_profiles = list(
        await session.scalars(select(MaterialProfile).where(MaterialProfile.organization_id == organization_id))
    )
    label_style_profiles = list(
        await session.scalars(select(LabelStyleProfile).where(LabelStyleProfile.organization_id == organization_id))
    )

    tools = list(await session.scalars(select(Tool).where(Tool.organization_id == organization_id)))
    await _attach_derived_fields(session, tools)

    insert_designs = list(
        await session.scalars(select(InsertDesign).where(InsertDesign.organization_id == organization_id))
    )
    designs = list(await session.scalars(select(Design).where(Design.organization_id == organization_id)))

    drawer_layouts = list(
        await session.scalars(
            select(DrawerLayout)
            .join(Drawer, DrawerLayout.drawer_id == Drawer.id)
            .join(Toolbox, Drawer.toolbox_id == Toolbox.id)
            .join(Shop, Toolbox.shop_id == Shop.id)
            .where(Shop.organization_id == organization_id)
        )
    )
    await _attach_placements(session, drawer_layouts)

    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "organization_id": str(organization_id),
        "shops": [ShopRead.model_validate(row).model_dump(mode="json") for row in shops],
        "toolboxes": [ToolboxRead.model_validate(row).model_dump(mode="json") for row in toolboxes],
        "drawers": [DrawerRead.model_validate(row).model_dump(mode="json") for row in drawers],
        "drawer_profiles": [DrawerProfileRead.model_validate(row).model_dump(mode="json") for row in drawer_profiles],
        "printer_profiles": [
            PrinterProfileRead.model_validate(row).model_dump(mode="json") for row in printer_profiles
        ],
        "magnet_profiles": [MagnetProfileRead.model_validate(row).model_dump(mode="json") for row in magnet_profiles],
        "material_profiles": [
            MaterialProfileRead.model_validate(row).model_dump(mode="json") for row in material_profiles
        ],
        "label_style_profiles": [
            LabelStyleProfileRead.model_validate(row).model_dump(mode="json") for row in label_style_profiles
        ],
        "tools": [ToolRead.model_validate(row).model_dump(mode="json") for row in tools],
        "insert_designs": [InsertDesignRead.model_validate(row).model_dump(mode="json") for row in insert_designs],
        "designs": [DesignRead.model_validate(row).model_dump(mode="json") for row in designs],
        "drawer_layouts": [DrawerLayoutRead.model_validate(row).model_dump(mode="json") for row in drawer_layouts],
    }

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    tmp_path = Path(tmp.name)

    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.json", json.dumps(data, indent=2))

        for design in designs:
            _add_file_to_zip(zf, design.outline_stl_path, base_dir)
            _add_file_to_zip(zf, design.text_stl_path, base_dir)
            _add_file_to_zip(zf, design.qr_stl_path, base_dir)
        for insert_design in insert_designs:
            _add_file_to_zip(zf, insert_design.stl_path, base_dir)
        for layout in drawer_layouts:
            for plate in (layout.layout_json or {}).get("plates", []):
                _add_file_to_zip(zf, plate.get("stl_path"), base_dir)
        # Not in the original plan (Tool Photos didn't exist when it was
        # written) but the same on-disk convention applies, and skipping
        # user-uploaded photos from a "full data backup" would be a real gap.
        for tool in tools:
            _add_file_to_zip(zf, tool.photo_path, base_dir)

    background_tasks.add_task(tmp_path.unlink, missing_ok=True)
    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=f"workshopos-export-{organization_id}.zip",
        background=background_tasks,
    )
