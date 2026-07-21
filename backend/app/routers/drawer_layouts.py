from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_membership
from ..models import (
    Drawer,
    DrawerLayout,
    DrawerProfile,
    InsertDesign,
    InsertPlacement,
    Membership,
    PrinterProfile,
    Shop,
    Tool,
    Toolbox,
)
from ..schemas.drawer_layout import DrawerLayoutRead, ExportLayoutCreate
from ..services.bin_merge import MergeCluster, PlacementForMerge, effective_footprint, find_merge_clusters
from ..services.bin_params import compute_manifest_fields
from ..services.drawer_layout import PackItem, filter_by_height, pack
from ..services.panelize import PanelizeItem, panelize
from ..workers.tasks import generate_bin_design, generate_plate_stl

router = APIRouter(
    prefix="/organizations/{organization_id}/shops/{shop_id}/toolboxes/{toolbox_id}/drawers/{drawer_id}/layouts",
    tags=["drawer-layouts"],
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


async def _get_layout(session: AsyncSession, drawer_id: uuid.UUID, layout_id: uuid.UUID) -> DrawerLayout:
    layout = await session.scalar(
        select(DrawerLayout).where(DrawerLayout.id == layout_id, DrawerLayout.drawer_id == drawer_id)
    )
    if layout is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Drawer layout not found.")
    return layout


async def _attach_placements(session: AsyncSession, layouts: list[DrawerLayout]) -> None:
    """This codebase doesn't use SQLAlchemy ORM relationships anywhere (see
    the other models) -- so nested `placements` for response serialization
    are queried separately and attached as a plain instance attribute rather
    than a mapped relationship, matching that convention."""
    if not layouts:
        return
    layout_ids = [layout.id for layout in layouts]
    rows = await session.scalars(
        select(InsertPlacement).where(InsertPlacement.drawer_layout_id.in_(layout_ids))
    )
    by_layout: dict[uuid.UUID, list[InsertPlacement]] = {layout_id: [] for layout_id in layout_ids}
    for placement in rows:
        by_layout[placement.drawer_layout_id].append(placement)
    for layout in layouts:
        layout.placements = by_layout.get(layout.id, [])  # type: ignore[attr-defined]


@router.post("", response_model=DrawerLayoutRead, status_code=status.HTTP_201_CREATED)
async def generate_layout(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    drawer_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> DrawerLayout:
    await _get_shop(session, organization_id, shop_id)
    await _get_toolbox(session, shop_id, toolbox_id)
    drawer = await _get_drawer(session, toolbox_id, drawer_id)

    profile = await session.scalar(
        select(DrawerProfile).where(
            DrawerProfile.id == drawer.drawer_profile_id, DrawerProfile.organization_id == organization_id
        )
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Drawer has no resolvable drawer profile.")

    tools = list(
        await session.scalars(
            select(Tool).where(Tool.drawer_id == drawer_id, Tool.insert_design_id.is_not(None))
        )
    )
    if not tools:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No tools in this drawer have a linked insert design.",
        )

    insert_design_ids = {tool.insert_design_id for tool in tools}
    designs_by_id = {
        design.id: design
        for design in await session.scalars(
            select(InsertDesign).where(InsertDesign.id.in_(insert_design_ids))
        )
    }

    items: list[PackItem] = []
    for tool in tools:
        design = designs_by_id.get(tool.insert_design_id)
        if design is None or not design.bounds_json:
            # Insert design still generating (no bounds yet) or was removed
            # out from under the tool -- skip rather than crash; it simply
            # contributes no tool-copies to pack.
            continue
        bounds = design.bounds_json
        copies = tool.insert_quantity if tool.insert_quantity is not None else 1
        for _ in range(copies):
            items.append(
                PackItem(
                    tool_id=tool.id,
                    insert_design_id=tool.insert_design_id,
                    width_mm=float(bounds["width_mm"]),
                    depth_mm=float(bounds["depth_mm"]),
                    height_mm=float(bounds["height_mm"]),
                    label=tool.name,
                )
            )

    if not items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No eligible insert copies to place (linked insert designs have no computed bounds yet).",
        )

    eligible_items, height_unplaced = filter_by_height(items, float(profile.inside_height_mm))
    result = pack(eligible_items, float(profile.inside_width_mm), float(profile.inside_depth_mm))
    all_unplaced = height_unplaced + result.unplaced

    layout = DrawerLayout(
        drawer_id=drawer_id,
        status="computed",
        layout_json={
            "unplaced": [
                {
                    "tool_id": str(u.tool_id),
                    "insert_design_id": str(u.insert_design_id),
                    "reason": u.reason,
                }
                for u in all_unplaced
            ],
            "utilization_pct": result.utilization_pct,
            "merges": [],
        },
    )
    session.add(layout)
    await session.flush()

    placement_rows = [
        InsertPlacement(
            drawer_layout_id=layout.id,
            insert_design_id=placement.insert_design_id,
            x_mm=Decimal(str(round(placement.x_mm, 3))),
            y_mm=Decimal(str(round(placement.y_mm, 3))),
            rotation_deg=Decimal("90") if placement.rotated else Decimal("0"),
        )
        for placement in result.placements
    ]
    session.add_all(placement_rows)
    await session.commit()
    await session.refresh(layout)

    layout.placements = placement_rows  # type: ignore[attr-defined]
    return layout


@router.get("", response_model=list[DrawerLayoutRead])
async def list_layouts(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    drawer_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> list[DrawerLayout]:
    await _get_shop(session, organization_id, shop_id)
    await _get_toolbox(session, shop_id, toolbox_id)
    await _get_drawer(session, toolbox_id, drawer_id)

    layouts = list(
        await session.scalars(
            select(DrawerLayout)
            .where(DrawerLayout.drawer_id == drawer_id)
            .order_by(DrawerLayout.created_at.desc())
        )
    )
    await _attach_placements(session, layouts)
    return layouts


@router.get("/{layout_id}", response_model=DrawerLayoutRead)
async def get_layout(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    drawer_id: uuid.UUID,
    layout_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> DrawerLayout:
    await _get_shop(session, organization_id, shop_id)
    await _get_toolbox(session, shop_id, toolbox_id)
    await _get_drawer(session, toolbox_id, drawer_id)
    layout = await _get_layout(session, drawer_id, layout_id)
    await _attach_placements(session, [layout])
    return layout


@router.post("/{layout_id}/merge", response_model=DrawerLayoutRead, status_code=status.HTTP_201_CREATED)
async def merge_layout(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    drawer_id: uuid.UUID,
    layout_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> DrawerLayout:
    """Non-destructive: produces a *new* `DrawerLayout` snapshot with adjacent,
    compatible, single-cell generated bins collapsed into freshly-generated
    multi-cell bins (real shared-wall material savings, not a fused pair of
    double-walled meshes). The source layout, its placements, and the
    original individual `InsertDesign` rows are never modified. "Nothing to
    merge" is a normal `201` outcome (`layout_json.merges == []`), not an
    error -- see `bin_merge.find_merge_clusters`.
    """
    await _get_shop(session, organization_id, shop_id)
    await _get_toolbox(session, shop_id, toolbox_id)
    await _get_drawer(session, toolbox_id, drawer_id)
    source_layout = await _get_layout(session, drawer_id, layout_id)
    await _attach_placements(session, [source_layout])
    source_placements: list[InsertPlacement] = source_layout.placements  # type: ignore[attr-defined]

    insert_design_ids = {placement.insert_design_id for placement in source_placements}
    designs_by_id = {
        design.id: design
        for design in await session.scalars(
            select(InsertDesign).where(InsertDesign.id.in_(insert_design_ids))
        )
    }

    merge_inputs: list[PlacementForMerge] = []
    for placement in source_placements:
        design = designs_by_id.get(placement.insert_design_id)
        if design is None or not design.bounds_json:
            # No resolvable footprint (design still generating or removed
            # out from under the placement) -- not merge-eligible, but it
            # still gets copied through verbatim below.
            continue
        width_mm, depth_mm = effective_footprint(design.bounds_json, placement.rotation_deg)
        merge_inputs.append(
            PlacementForMerge(
                placement_id=placement.id,
                insert_design_id=placement.insert_design_id,
                x_mm=float(placement.x_mm),
                y_mm=float(placement.y_mm),
                width_mm=width_mm,
                depth_mm=depth_mm,
                source=design.source,
                status=design.status,
                parameters_json=design.parameters_json or {},
            )
        )

    clusters: list[MergeCluster] = find_merge_clusters(merge_inputs)
    clustered_placement_ids = {placement_id for cluster in clusters for placement_id in cluster.placement_ids}

    merges_summary: list[dict] = []
    cluster_designs: list[tuple[MergeCluster, InsertDesign]] = []
    for cluster in clusters:
        params_dict = {
            "grid_width_units": cluster.grid_width_units,
            "grid_depth_units": cluster.grid_depth_units,
            "height_units": cluster.height_units,
            "compartments_x": 1,
            "compartments_y": 1,
            "include_stacking_lip": cluster.include_stacking_lip,
            "magnet_diameter_mm": cluster.magnet_diameter_mm,
            "magnet_thickness_mm": cluster.magnet_thickness_mm,
            "magnet_diameter_clearance_mm": cluster.magnet_diameter_clearance_mm,
            "magnet_depth_clearance_mm": cluster.magnet_depth_clearance_mm,
        }
        try:
            engine_version, content_hash, bounds = compute_manifest_fields(params_dict)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

        new_design = InsertDesign(
            organization_id=organization_id,
            name=f"Merged {cluster.grid_width_units}x{cluster.grid_depth_units} Bin",
            source="generated",
            source_reference=f"Merged {cluster.source_placement_count} bins from layout {layout_id}",
            parameters_json=params_dict,
            engine_version=engine_version,
            content_hash=content_hash,
            bounds_json=bounds,
            status="queued",
        )
        session.add(new_design)
        await session.commit()
        await session.refresh(new_design)

        # Only the heavy CSG step is deferred to the worker -- same sequence
        # as `insert_designs.py::generate_bin_endpoint`.
        generate_bin_design.send(str(new_design.id))

        cluster_designs.append((cluster, new_design))
        merges_summary.append(
            {
                "merged_insert_design_id": str(new_design.id),
                "grid_width_units": cluster.grid_width_units,
                "grid_depth_units": cluster.grid_depth_units,
                "source_placement_count": cluster.source_placement_count,
            }
        )

    source_layout_json = source_layout.layout_json or {}
    new_layout = DrawerLayout(
        drawer_id=drawer_id,
        status="computed",
        layout_json={
            "unplaced": source_layout_json.get("unplaced", []),
            "utilization_pct": source_layout_json.get("utilization_pct"),
            "merges": merges_summary,
        },
    )
    session.add(new_layout)
    await session.flush()

    new_placement_rows: list[InsertPlacement] = []
    for placement in source_placements:
        if placement.id in clustered_placement_ids:
            continue
        new_placement_rows.append(
            InsertPlacement(
                drawer_layout_id=new_layout.id,
                insert_design_id=placement.insert_design_id,
                x_mm=placement.x_mm,
                y_mm=placement.y_mm,
                rotation_deg=placement.rotation_deg,
            )
        )
    for cluster, new_design in cluster_designs:
        new_placement_rows.append(
            InsertPlacement(
                drawer_layout_id=new_layout.id,
                insert_design_id=new_design.id,
                x_mm=Decimal(str(round(cluster.x_mm, 3))),
                y_mm=Decimal(str(round(cluster.y_mm, 3))),
                rotation_deg=Decimal("0"),
            )
        )

    session.add_all(new_placement_rows)
    await session.commit()
    await session.refresh(new_layout)

    new_layout.placements = new_placement_rows  # type: ignore[attr-defined]
    return new_layout


@router.post("/{layout_id}/export", response_model=DrawerLayoutRead, status_code=status.HTTP_201_CREATED)
async def export_layout(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    drawer_id: uuid.UUID,
    layout_id: uuid.UUID,
    payload: ExportLayoutCreate,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> DrawerLayout:
    """Print-bed panelization (M3 Phase 5): takes a computed/exported source
    layout and re-buckets its already-placed bins onto N printer-bed-sized
    plates, generating one real combined STL per plate. Non-destructive, same
    "always create a new row" convention `merge_layout` uses -- export never
    re-solves drawer-space x/y, it only re-packs the same footprint
    rectangles onto print-bed space. Source `InsertPlacement`s are copied
    through verbatim (drawer-space coordinates untouched); the print-bed
    assignment (which plate, plate-local x/y, rotation for that plate) lives
    only in the new layout's `layout_json["plates"]`, not in the placement
    rows themselves.
    """
    await _get_shop(session, organization_id, shop_id)
    await _get_toolbox(session, shop_id, toolbox_id)
    await _get_drawer(session, toolbox_id, drawer_id)

    printer = await session.scalar(
        select(PrinterProfile).where(
            PrinterProfile.id == payload.printer_profile_id, PrinterProfile.organization_id == organization_id
        )
    )
    if printer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Printer profile not found.")

    source_layout = await _get_layout(session, drawer_id, layout_id)
    if source_layout.status not in ("computed", "exported"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Layout has no placements to export yet."
        )

    await _attach_placements(session, [source_layout])
    source_placements: list[InsertPlacement] = source_layout.placements  # type: ignore[attr-defined]
    if not source_placements:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This layout has no placed bins to export."
        )

    insert_design_ids = {placement.insert_design_id for placement in source_placements}
    designs_by_id = {
        design.id: design
        for design in await session.scalars(
            select(InsertDesign).where(InsertDesign.id.in_(insert_design_ids))
        )
    }

    panelize_items: list[PanelizeItem] = []
    not_generated_unplaced: list[dict] = []
    for placement in source_placements:
        design = designs_by_id.get(placement.insert_design_id)
        if design is None or not design.bounds_json or design.status != "generated":
            # Not silently dropped -- surfaced in the response's always-visible
            # `unplaced` list, same anti-silent-drop convention the rest of
            # this router follows (see `generate_layout`/`merge_layout`).
            not_generated_unplaced.append(
                {
                    "placement_id": str(placement.id),
                    "insert_design_id": str(placement.insert_design_id),
                    "reason": "insert not yet generated",
                }
            )
            continue
        width_mm, depth_mm = effective_footprint(design.bounds_json, placement.rotation_deg)
        panelize_items.append(
            PanelizeItem(
                placement_id=placement.id,
                insert_design_id=placement.insert_design_id,
                width_mm=width_mm,
                depth_mm=depth_mm,
                label=design.name,
            )
        )

    if not panelize_items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No placements have a generated insert design to export yet.",
        )

    # Assumption (not a documented spec): `usable_margin_mm` applies
    # symmetrically on both edges of each axis -- `PrinterProfile` has no
    # documented per-side semantics.
    usable_width_mm = float(printer.build_width_mm) - 2 * float(printer.usable_margin_mm)
    usable_depth_mm = float(printer.build_depth_mm) - 2 * float(printer.usable_margin_mm)
    if usable_width_mm <= 0 or usable_depth_mm <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Printer profile's usable print area (build dimensions minus 2x usable_margin_mm) must be positive.",
        )

    result = panelize(panelize_items, usable_width_mm, usable_depth_mm)

    source_layout_json = source_layout.layout_json or {}
    all_unplaced = (
        list(source_layout_json.get("unplaced", []))
        + [
            {"placement_id": str(u.tool_id), "insert_design_id": str(u.insert_design_id), "reason": u.reason}
            for u in result.unplaced
        ]
        + not_generated_unplaced
    )

    plates_json = [
        {
            "plate_index": plate_index,
            "status": "queued",
            "stl_path": None,
            "error_message": None,
            "bin_count": len(assignments),
            "assignments": [
                {
                    "placement_id": str(a.placement_id),
                    "insert_design_id": str(a.insert_design_id),
                    "x_mm": a.x_mm,
                    "y_mm": a.y_mm,
                    "rotation_deg": 90 if a.rotated else 0,
                }
                for a in assignments
            ],
        }
        for plate_index, assignments in enumerate(result.plates)
    ]

    new_layout = DrawerLayout(
        drawer_id=drawer_id,
        status="exported",
        printer_profile_id=printer.id,
        layout_json={
            "unplaced": all_unplaced,
            "utilization_pct": source_layout_json.get("utilization_pct"),
            "merges": source_layout_json.get("merges", []),
            "plates": plates_json,
        },
    )
    session.add(new_layout)
    await session.flush()

    # Verbatim copy -- export never re-solves drawer-space x/y, see docstring.
    new_placement_rows = [
        InsertPlacement(
            drawer_layout_id=new_layout.id,
            insert_design_id=placement.insert_design_id,
            x_mm=placement.x_mm,
            y_mm=placement.y_mm,
            rotation_deg=placement.rotation_deg,
        )
        for placement in source_placements
    ]
    session.add_all(new_placement_rows)
    await session.commit()
    await session.refresh(new_layout)

    for plate_index in range(len(plates_json)):
        generate_plate_stl.send(str(new_layout.id), plate_index)

    new_layout.placements = new_placement_rows  # type: ignore[attr-defined]
    return new_layout


@router.get("/{layout_id}/plates/{plate_index}/file")
async def get_plate_file(
    organization_id: uuid.UUID,
    shop_id: uuid.UUID,
    toolbox_id: uuid.UUID,
    drawer_id: uuid.UUID,
    layout_id: uuid.UUID,
    plate_index: int,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Mirrors `insert_designs.py::get_insert_design_file` exactly."""
    await _get_shop(session, organization_id, shop_id)
    await _get_toolbox(session, shop_id, toolbox_id)
    await _get_drawer(session, toolbox_id, drawer_id)
    layout = await _get_layout(session, drawer_id, layout_id)

    plates = (layout.layout_json or {}).get("plates", [])
    plate = next((p for p in plates if p.get("plate_index") == plate_index), None)
    if plate is None or plate.get("status") != "generated" or not plate.get("stl_path"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated plate file not available yet.")

    path = Path(plate["stl_path"])
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated plate file not available yet.")

    return FileResponse(path, media_type="model/stl", filename=f"plate-{plate_index}.stl")
