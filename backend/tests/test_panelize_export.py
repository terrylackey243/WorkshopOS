from __future__ import annotations

import io
import uuid
from decimal import Decimal

import pytest
import trimesh
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DrawerLayout, InsertPlacement
from app.workers import tasks as worker_tasks

from .conftest import auth_headers, register_org

# M3 Phase 5 (Print-Bed Panelization at Export) integration tests. Reuses the
# M3 Phase 3/4 fixture-building style from test_drawer_layouts.py /
# test_bin_merge.py (real org/shop/toolbox/drawer chain, real generate-bin
# calls, real HTTP client calls) -- helpers duplicated locally rather than
# imported cross-file, matching this test suite's existing per-file
# convention.


async def _build_drawer(
    client: AsyncClient,
    headers: dict,
    org_id: str,
    *,
    inside_width_mm: str,
    inside_depth_mm: str,
    inside_height_mm: str,
) -> dict:
    shop_resp = await client.post(
        f"/organizations/{org_id}/shops", json={"name": "Main Garage", "slug": "main-garage"}, headers=headers
    )
    assert shop_resp.status_code == 201, shop_resp.text
    shop_id = shop_resp.json()["id"]

    toolbox_resp = await client.post(
        f"/organizations/{org_id}/shops/{shop_id}/toolboxes", json={"name": "Rolling Cart"}, headers=headers
    )
    assert toolbox_resp.status_code == 201, toolbox_resp.text
    toolbox_id = toolbox_resp.json()["id"]

    profile_resp = await client.post(
        f"/organizations/{org_id}/profiles/drawer-profiles",
        json={
            "name": "Test Drawer Profile",
            "inside_width_mm": inside_width_mm,
            "inside_depth_mm": inside_depth_mm,
            "inside_height_mm": inside_height_mm,
        },
        headers=headers,
    )
    assert profile_resp.status_code == 201, profile_resp.text
    drawer_profile_id = profile_resp.json()["id"]

    drawer_resp = await client.post(
        f"/organizations/{org_id}/shops/{shop_id}/toolboxes/{toolbox_id}/drawers",
        json={"drawer_profile_id": drawer_profile_id},
        headers=headers,
    )
    assert drawer_resp.status_code == 201, drawer_resp.text
    drawer_id = drawer_resp.json()["id"]

    return {"shop_id": shop_id, "toolbox_id": toolbox_id, "drawer_profile_id": drawer_profile_id, "drawer_id": drawer_id}


async def _generate_bin(
    client: AsyncClient,
    headers: dict,
    org_id: str,
    *,
    name: str,
    grid_width_units: int = 1,
    grid_depth_units: int = 1,
    height_units: int = 1,
) -> dict:
    resp = await client.post(
        f"/organizations/{org_id}/insert-designs/generate-bin",
        json={
            "name": name,
            "grid_width_units": grid_width_units,
            "grid_depth_units": grid_depth_units,
            "height_units": height_units,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_tool(
    client: AsyncClient,
    headers: dict,
    org_id: str,
    *,
    name: str,
    drawer_id: str,
    insert_design_id: str,
    quantity: int,
    insert_quantity: int | None = None,
) -> dict:
    payload = {"name": name, "drawer_id": drawer_id, "insert_design_id": insert_design_id, "quantity": quantity}
    if insert_quantity is not None:
        payload["insert_quantity"] = insert_quantity
    resp = await client.post(f"/organizations/{org_id}/tools", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_printer(
    client: AsyncClient,
    headers: dict,
    org_id: str,
    *,
    name: str = "Test Printer",
    build_width_mm: str,
    build_depth_mm: str,
    build_height_mm: str = "100",
    usable_margin_mm: str = "2.0",
) -> dict:
    resp = await client.post(
        f"/organizations/{org_id}/profiles/printers",
        json={
            "name": name,
            "build_width_mm": build_width_mm,
            "build_depth_mm": build_depth_mm,
            "build_height_mm": build_height_mm,
            "usable_margin_mm": usable_margin_mm,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _layouts_url(org_id: str, shop_id: str, toolbox_id: str, drawer_id: str) -> str:
    return f"/organizations/{org_id}/shops/{shop_id}/toolboxes/{toolbox_id}/drawers/{drawer_id}/layouts"


async def _insert_layout_with_placements(
    db_session: AsyncSession,
    *,
    drawer_id: str,
    placements: list[tuple[str, float, float, float]],  # (insert_design_id, x_mm, y_mm, rotation_deg)
) -> str:
    layout = DrawerLayout(
        drawer_id=uuid.UUID(drawer_id),
        status="computed",
        layout_json={"unplaced": [], "utilization_pct": 50.0, "merges": []},
    )
    db_session.add(layout)
    await db_session.flush()

    rows = [
        InsertPlacement(
            drawer_layout_id=layout.id,
            insert_design_id=uuid.UUID(insert_design_id),
            x_mm=Decimal(str(round(x_mm, 3))),
            y_mm=Decimal(str(round(y_mm, 3))),
            rotation_deg=Decimal(str(rotation_deg)),
        )
        for insert_design_id, x_mm, y_mm, rotation_deg in placements
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return str(layout.id)


async def _load_mesh_from_plate_file(client: AsyncClient, headers: dict, url: str) -> trimesh.Trimesh:
    resp = await client.get(url, headers=headers)
    assert resp.status_code == 200, resp.text
    mesh = trimesh.load(io.BytesIO(resp.content), file_type="stl")
    assert isinstance(mesh, trimesh.Trimesh)
    return mesh


async def test_export_panelizes_across_multiple_plates_and_generates_valid_stls(
    client: AsyncClient, db_session: AsyncSession, tmp_path, monkeypatch
) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]
    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))

    small_bin = await _generate_bin(client, headers, org_id, name="Unit Bin", grid_width_units=1, grid_depth_units=1)
    await worker_tasks._generate_bin_design(small_bin["id"])
    bin_resp = await client.get(f"/organizations/{org_id}/insert-designs/{small_bin['id']}", headers=headers)
    small_bin = bin_resp.json()
    assert small_bin["status"] == "generated"
    single_mesh = trimesh.load(small_bin["stl_path"])
    single_face_count = len(single_mesh.faces)
    single_vertex_count = len(single_mesh.vertices)
    assert single_face_count > 0 and single_vertex_count > 0

    # Drawer wide enough to lay all 5 copies out in a row without any 2D
    # packing surprises (a plain, uncontested happy-path layout).
    chain = await _build_drawer(
        client, headers, org_id, inside_width_mm="260", inside_depth_mm="50", inside_height_mm="50"
    )
    await _create_tool(
        client, headers, org_id, name="Bit Set", drawer_id=chain["drawer_id"],
        insert_design_id=small_bin["id"], quantity=5, insert_quantity=5,
    )

    layout_resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]), headers=headers
    )
    assert layout_resp.status_code == 201, layout_resp.text
    layout_body = layout_resp.json()
    assert layout_body["layout_json"]["unplaced"] == []
    assert len(layout_body["placements"]) == 5
    layout_id = layout_body["id"]

    # 100x100 bed, 2mm margin -> 96x96 usable. 41.5mm bins tile 2x2 (83mm)
    # per plate, so 5 bins need 2 plates (4 + 1).
    printer = await _create_printer(
        client, headers, org_id, build_width_mm="100", build_depth_mm="100", usable_margin_mm="2.0"
    )
    usable_mm = 100.0 - 2 * 2.0

    export_url = _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]) + f"/{layout_id}/export"
    export_resp = await client.post(export_url, json={"printer_profile_id": printer["id"]}, headers=headers)
    assert export_resp.status_code == 201, export_resp.text
    export_body = export_resp.json()

    assert export_body["status"] == "exported"
    assert export_body["printer_profile_id"] == printer["id"]
    assert len(export_body["placements"]) == 5, "source placements must be copied through verbatim"
    plates = export_body["layout_json"]["plates"]
    assert len(plates) == 2, f"expected 2 plates for 5 bins on a 96x96 usable bed, got {len(plates)}"
    bin_counts = sorted(p["bin_count"] for p in plates)
    assert bin_counts == [1, 4]
    assert sum(p["bin_count"] for p in plates) == 5
    assert all(p["status"] == "queued" for p in plates)
    new_layout_id = export_body["id"]

    # Force each plate's worker actor synchronously (bypassing the real
    # broker, same technique test_bin_merge.py uses for generate_bin_design).
    for plate in plates:
        await worker_tasks._generate_plate_stl(new_layout_id, plate["plate_index"])

    get_resp = await client.get(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]) + f"/{new_layout_id}",
        headers=headers,
    )
    assert get_resp.status_code == 200
    refreshed = get_resp.json()
    refreshed_plates = {p["plate_index"]: p for p in refreshed["layout_json"]["plates"]}
    assert len(refreshed_plates) == 2
    for plate_index, plate in refreshed_plates.items():
        assert plate["status"] == "generated", plate.get("error_message")
        assert plate["stl_path"]

    for plate_index, plate in refreshed_plates.items():
        file_url = (
            _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"])
            + f"/{new_layout_id}/plates/{plate_index}/file"
        )
        mesh = await _load_mesh_from_plate_file(client, headers, file_url)

        # Bounding box must fit the *usable* (margin-subtracted) area, not
        # the raw build volume -- direct test of the margin assumption.
        bounds = mesh.bounds
        assert bounds[0][0] >= -1e-3
        assert bounds[0][1] >= -1e-3
        assert bounds[1][0] <= usable_mm + 1e-3, f"plate {plate_index} exceeds usable width: {bounds}"
        assert bounds[1][1] <= usable_mm + 1e-3, f"plate {plate_index} exceeds usable depth: {bounds}"

        # Not degenerate/empty, and face count is consistent with N
        # concatenated (not fused, not dropped) single-bin bodies. Face count
        # is the reliable invariant here -- concatenation never drops or
        # merges triangles, so it must be exactly additive. Vertex count is
        # NOT asserted exactly equal: these bins tile with zero gap (see
        # test_bin_merge.py), so adjacent plate bodies can share exactly
        # coincident corner/edge vertices at their touching boundary, which
        # trimesh's STL export/reload vertex-merge legitimately welds --
        # that's expected geometry, not a dropped-body bug. Still assert
        # it's in the right ballpark (not near-empty, not wildly over) to
        # catch a genuinely degenerate/duplicated result.
        n = plate["bin_count"]
        assert len(mesh.faces) == n * single_face_count, f"plate {plate_index} face count mismatch"
        assert n * single_vertex_count * 0.9 <= len(mesh.vertices) <= n * single_vertex_count, (
            f"plate {plate_index} vertex count out of expected range: {len(mesh.vertices)}"
        )


async def test_export_respects_usable_margin_not_raw_build_dims(
    client: AsyncClient, db_session: AsyncSession, tmp_path, monkeypatch
) -> None:
    """2 bins that tile flush into an 83x83 footprint. A build plate of
    85x85 with 0 margin would fit them both on one plate; the SAME 85x85
    build plate with a 2mm margin (81x81 usable) cannot fit them together
    (81 < 83) and must split them across 2 plates. This is a direct,
    discriminating regression test for the margin-subtraction assumption --
    a bug that fed raw build_width_mm/build_depth_mm into panelize() instead
    of the usable, margin-subtracted dims would incorrectly place both on
    one plate."""
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]
    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))

    small_bin = await _generate_bin(client, headers, org_id, name="Unit Bin", grid_width_units=1, grid_depth_units=1)
    await worker_tasks._generate_bin_design(small_bin["id"])
    bin_resp = await client.get(f"/organizations/{org_id}/insert-designs/{small_bin['id']}", headers=headers)
    small_bin = bin_resp.json()
    assert small_bin["status"] == "generated"
    width_mm = small_bin["bounds_json"]["width_mm"]

    chain = await _build_drawer(
        client, headers, org_id, inside_width_mm="100", inside_depth_mm="100", inside_height_mm="50"
    )
    layout_id = await _insert_layout_with_placements(
        db_session,
        drawer_id=chain["drawer_id"],
        placements=[(small_bin["id"], 0.0, 0.0, 0.0), (small_bin["id"], width_mm, 0.0, 0.0)],
    )

    printer = await _create_printer(
        client, headers, org_id, build_width_mm="85", build_depth_mm="85", usable_margin_mm="2.0"
    )
    export_url = _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]) + f"/{layout_id}/export"
    export_resp = await client.post(export_url, json={"printer_profile_id": printer["id"]}, headers=headers)
    assert export_resp.status_code == 201, export_resp.text
    plates = export_resp.json()["layout_json"]["plates"]
    assert len(plates) == 2, "81x81 usable area (85x85 minus 2mm margin) cannot fit two 41.5mm bins side by side"
    assert sorted(p["bin_count"] for p in plates) == [1, 1]


async def test_export_rotated_placement_transform_order_regression(
    client: AsyncClient, db_session: AsyncSession, tmp_path, monkeypatch
) -> None:
    """Direct regression test for the mesh transform pipeline's
    re-normalize-after-rotate step (`generate_plate_stl` in
    `app/workers/tasks.py`). Uses a 2x1 (non-square) bin so a 90-degree
    rotation actually changes which axis is which -- a square bin would mask
    a transform-order bug entirely. The printer bed is sized so the item can
    ONLY fit rotated (upright width 83.5mm exceeds the 50mm bed width), so
    the packer is forced to rotate it regardless of its own heuristics."""
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]
    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))

    wide_bin = await _generate_bin(client, headers, org_id, name="2x1 Bin", grid_width_units=2, grid_depth_units=1)
    await worker_tasks._generate_bin_design(wide_bin["id"])
    bin_resp = await client.get(f"/organizations/{org_id}/insert-designs/{wide_bin['id']}", headers=headers)
    wide_bin = bin_resp.json()
    assert wide_bin["status"] == "generated"
    raw_width_mm = wide_bin["bounds_json"]["width_mm"]  # ~83.5
    raw_depth_mm = wide_bin["bounds_json"]["depth_mm"]  # ~41.5
    assert raw_width_mm > raw_depth_mm

    chain = await _build_drawer(
        client, headers, org_id, inside_width_mm="200", inside_depth_mm="200", inside_height_mm="50"
    )
    # rotation_deg=0 on the *source* placement -- the rotation this test
    # exercises is entirely panelize()'s own bed-packing decision, not
    # anything carried over from the drawer placement.
    layout_id = await _insert_layout_with_placements(
        db_session, drawer_id=chain["drawer_id"], placements=[(wide_bin["id"], 0.0, 0.0, 0.0)]
    )

    # usable bed: width_mm=50 (too narrow for the item upright, 83.5 > 50),
    # depth_mm=90 (plenty for either orientation) -- forces rotation.
    printer = await _create_printer(
        client, headers, org_id, build_width_mm="50", build_depth_mm="90", usable_margin_mm="0"
    )
    export_url = _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]) + f"/{layout_id}/export"
    export_resp = await client.post(export_url, json={"printer_profile_id": printer["id"]}, headers=headers)
    assert export_resp.status_code == 201, export_resp.text
    export_body = export_resp.json()
    plates = export_body["layout_json"]["plates"]
    assert len(plates) == 1
    assignments = plates[0]["assignments"]
    assert len(assignments) == 1
    assert assignments[0]["rotation_deg"] == 90, "packer must have rotated the item to make it fit"
    assert assignments[0]["x_mm"] == pytest.approx(0.0, abs=0.01)
    assert assignments[0]["y_mm"] == pytest.approx(0.0, abs=0.01)

    new_layout_id = export_body["id"]
    await worker_tasks._generate_plate_stl(new_layout_id, 0)

    file_url = (
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"])
        + f"/{new_layout_id}/plates/0/file"
    )
    mesh = await _load_mesh_from_plate_file(client, headers, file_url)
    bounds = mesh.bounds

    # The direct regression assertion: if the re-normalize-after-rotate step
    # were skipped, rotating about the post-normalize bounds-min corner (not
    # the centroid) would shift the bounding box away from (0, 0) -- this
    # would fail with a negative or non-zero min.
    assert bounds[0][0] == pytest.approx(0.0, abs=0.05), f"mesh not re-normalized to x=0 after rotation: {bounds}"
    assert bounds[0][1] == pytest.approx(0.0, abs=0.05), f"mesh not re-normalized to y=0 after rotation: {bounds}"

    # And the swapped footprint proves the rotation itself really happened
    # (not just a no-op that happened to already sit at the origin).
    mesh_width = bounds[1][0] - bounds[0][0]
    mesh_depth = bounds[1][1] - bounds[0][1]
    assert mesh_width == pytest.approx(raw_depth_mm, abs=0.2), f"expected rotated width ~= raw depth, got {bounds}"
    assert mesh_depth == pytest.approx(raw_width_mm, abs=0.2), f"expected rotated depth ~= raw width, got {bounds}"


async def test_export_too_small_printer_reports_exceeds_printer_bed_in_unplaced(
    client: AsyncClient, db_session: AsyncSession, tmp_path, monkeypatch
) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]
    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))

    small_bin = await _generate_bin(client, headers, org_id, name="Unit Bin", grid_width_units=1, grid_depth_units=1)
    await worker_tasks._generate_bin_design(small_bin["id"])
    bin_resp = await client.get(f"/organizations/{org_id}/insert-designs/{small_bin['id']}", headers=headers)
    small_bin = bin_resp.json()
    assert small_bin["status"] == "generated"

    chain = await _build_drawer(
        client, headers, org_id, inside_width_mm="100", inside_depth_mm="100", inside_height_mm="50"
    )
    await _create_tool(
        client, headers, org_id, name="Bit Set", drawer_id=chain["drawer_id"],
        insert_design_id=small_bin["id"], quantity=1, insert_quantity=1,
    )
    layout_resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]), headers=headers
    )
    assert layout_resp.status_code == 201, layout_resp.text
    layout_id = layout_resp.json()["id"]
    placement_id = layout_resp.json()["placements"][0]["id"]

    # 10x10mm usable bed -- far smaller than a 41.5mm bin in either
    # orientation. Must be reported, never a 500 or a silent drop.
    printer = await _create_printer(
        client, headers, org_id, build_width_mm="10", build_depth_mm="10", usable_margin_mm="0"
    )
    export_url = _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]) + f"/{layout_id}/export"
    export_resp = await client.post(export_url, json={"printer_profile_id": printer["id"]}, headers=headers)
    assert export_resp.status_code == 201, export_resp.text
    body = export_resp.json()

    assert body["layout_json"]["plates"] == []
    unplaced = body["layout_json"]["unplaced"]
    matching = [u for u in unplaced if u.get("placement_id") == placement_id]
    assert len(matching) == 1, unplaced
    assert matching[0]["reason"] == "exceeds printer bed"


async def test_export_404_when_printer_profile_not_found(
    client: AsyncClient, tmp_path, monkeypatch
) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]
    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))

    small_bin = await _generate_bin(client, headers, org_id, name="Unit Bin")
    await worker_tasks._generate_bin_design(small_bin["id"])

    chain = await _build_drawer(
        client, headers, org_id, inside_width_mm="100", inside_depth_mm="100", inside_height_mm="50"
    )
    await _create_tool(
        client, headers, org_id, name="Bit Set", drawer_id=chain["drawer_id"],
        insert_design_id=small_bin["id"], quantity=1, insert_quantity=1,
    )
    layout_resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]), headers=headers
    )
    layout_id = layout_resp.json()["id"]

    export_url = _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]) + f"/{layout_id}/export"
    export_resp = await client.post(export_url, json={"printer_profile_id": str(uuid.uuid4())}, headers=headers)
    assert export_resp.status_code == 404
    assert export_resp.json()["detail"] == "Printer profile not found."


async def test_export_422_when_no_placements_have_generated_insert(
    client: AsyncClient, tmp_path, monkeypatch
) -> None:
    """The insert design's worker actor is deliberately never forced through
    here -- it stays `status="queued"` (bounds_json is set synchronously at
    creation time, so the layout can still place it, but export must refuse:
    there's no real STL to combine yet)."""
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]
    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))

    small_bin = await _generate_bin(client, headers, org_id, name="Unit Bin")
    assert small_bin["status"] == "queued"

    chain = await _build_drawer(
        client, headers, org_id, inside_width_mm="100", inside_depth_mm="100", inside_height_mm="50"
    )
    await _create_tool(
        client, headers, org_id, name="Bit Set", drawer_id=chain["drawer_id"],
        insert_design_id=small_bin["id"], quantity=1, insert_quantity=1,
    )
    layout_resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]), headers=headers
    )
    assert layout_resp.status_code == 201, layout_resp.text
    layout_id = layout_resp.json()["id"]

    printer = await _create_printer(client, headers, org_id, build_width_mm="100", build_depth_mm="100")
    export_url = _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]) + f"/{layout_id}/export"
    export_resp = await client.post(export_url, json={"printer_profile_id": printer["id"]}, headers=headers)
    assert export_resp.status_code == 422
    assert export_resp.json()["detail"] == "No placements have a generated insert design to export yet."
