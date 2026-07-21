from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import trimesh
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DrawerLayout, InsertPlacement
from app.workers import tasks as worker_tasks

from .conftest import auth_headers, register_org

# M3 Phase 4 (Bin Merging) tests. Reuses the M3 Phase 3 fixture-building
# style from test_drawer_layouts.py (real org/shop/toolbox/drawer chain, real
# generate-bin calls for InsertDesigns with known bounds_json, real HTTP
# client calls) -- helpers duplicated locally rather than imported cross-file,
# matching this test suite's existing per-file convention (see
# test_insert_designs.py, which does the same rather than importing from
# test_drawer_layouts.py).


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


def _layouts_url(org_id: str, shop_id: str, toolbox_id: str, drawer_id: str) -> str:
    return f"/organizations/{org_id}/shops/{shop_id}/toolboxes/{toolbox_id}/drawers/{drawer_id}/layouts"


def _placement_rect(placement: dict, bounds_by_design: dict[str, tuple[float, float]]) -> tuple[float, float, float, float]:
    width_mm, depth_mm = bounds_by_design[placement["insert_design_id"]]
    rotated = abs(float(placement["rotation_deg"])) > 45.0
    w, h = (depth_mm, width_mm) if rotated else (width_mm, depth_mm)
    return float(placement["x_mm"]), float(placement["y_mm"]), w, h


async def _insert_layout_with_placements(
    db_session: AsyncSession,
    *,
    drawer_id: str,
    placements: list[tuple[str, float, float]],  # (insert_design_id, x_mm, y_mm) -- rotation always 0
) -> str:
    """Directly constructs a `DrawerLayout` + `InsertPlacement` rows at exact,
    known coordinates -- more reliable than coaxing the packer into a
    specific engineered adjacency (incompatible-but-touching, L-shaped,
    gapped) for scenarios the packer wouldn't naturally produce on its own."""
    layout = DrawerLayout(
        drawer_id=uuid.UUID(drawer_id),
        status="computed",
        layout_json={"unplaced": [], "utilization_pct": 50.0},
    )
    db_session.add(layout)
    await db_session.flush()

    rows = [
        InsertPlacement(
            drawer_layout_id=layout.id,
            insert_design_id=uuid.UUID(insert_design_id),
            x_mm=Decimal(str(round(x_mm, 3))),
            y_mm=Decimal(str(round(y_mm, 3))),
            rotation_deg=Decimal("0"),
        )
        for insert_design_id, x_mm, y_mm in placements
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return str(layout.id)


async def test_merge_collapses_a_clean_2x2_grid_of_identical_bins(
    client: AsyncClient, db_session: AsyncSession, tmp_path, monkeypatch
) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    # Redirect generated files to a temp dir (the real /data/generated mount
    # point doesn't exist outside the container) -- same as
    # test_insert_designs.py::test_generate_bin_design_writes_stl_file.
    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))

    small_bin = await _generate_bin(client, headers, org_id, name="Unit Bin", grid_width_units=1, grid_depth_units=1, height_units=1)
    width_mm = small_bin["bounds_json"]["width_mm"]
    depth_mm = small_bin["bounds_json"]["depth_mm"]
    assert width_mm == pytest.approx(41.5, abs=0.01)
    assert depth_mm == pytest.approx(41.5, abs=0.01)

    # `generate-bin` only enqueues the Dramatiq actor -- no worker process
    # consumes that queue in tests, so the design would stay `status="queued"`
    # forever (and thus fail `find_merge_clusters`'s `status == "generated"`
    # eligibility filter) unless we force it through synchronously, same
    # technique as test_insert_designs.py.
    await worker_tasks._generate_bin_design(small_bin["id"])
    small_bin_resp = await client.get(f"/organizations/{org_id}/insert-designs/{small_bin['id']}", headers=headers)
    assert small_bin_resp.status_code == 200
    small_bin = small_bin_resp.json()
    assert small_bin["status"] == "generated"

    # Drawer sized to exactly fit a 2x2 tiling of 41.5mm bins (83mm) --
    # forces the best-area-fit packer to tile them with zero gaps.
    chain = await _build_drawer(
        client, headers, org_id, inside_width_mm="83", inside_depth_mm="83", inside_height_mm="50"
    )
    await _create_tool(
        client, headers, org_id, name="Bit Set", drawer_id=chain["drawer_id"],
        insert_design_id=small_bin["id"], quantity=4, insert_quantity=4,
    )

    layout_resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]), headers=headers
    )
    assert layout_resp.status_code == 201, layout_resp.text
    layout_body = layout_resp.json()
    layout_id = layout_body["id"]

    # Verify (don't assume) the packer actually produced a clean, gap-free
    # 2x2 tiling before writing merge assertions against it.
    assert layout_body["layout_json"]["unplaced"] == []
    assert len(layout_body["placements"]) == 4
    bounds_by_design = {small_bin["id"]: (width_mm, depth_mm)}
    rects = [_placement_rect(p, bounds_by_design) for p in layout_body["placements"]]
    xs = sorted({round(r[0], 2) for r in rects})
    ys = sorted({round(r[1], 2) for r in rects})
    assert xs == pytest.approx([0.0, 41.5], abs=0.01), f"expected a 2-column tiling, got x positions {xs}"
    assert ys == pytest.approx([0.0, 41.5], abs=0.01), f"expected a 2-row tiling, got y positions {ys}"
    total_area = sum(w * h for _, _, w, h in rects)
    bbox_area = 83.0 * 83.0
    assert total_area == pytest.approx(bbox_area, abs=1.0), "expected the 4 bins to tile with zero gaps"

    merge_resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]) + f"/{layout_id}/merge",
        headers=headers,
    )
    assert merge_resp.status_code == 201, merge_resp.text
    merged_body = merge_resp.json()

    assert len(merged_body["placements"]) == 1
    merges = merged_body["layout_json"]["merges"]
    assert len(merges) == 1
    assert merges[0]["grid_width_units"] == 2
    assert merges[0]["grid_depth_units"] == 2
    assert merges[0]["source_placement_count"] == 4

    merged_placement = merged_body["placements"][0]
    merged_design_id = merged_placement["insert_design_id"]
    assert merged_design_id == merges[0]["merged_insert_design_id"]
    assert merged_design_id not in {small_bin["id"]}
    assert float(merged_placement["x_mm"]) == pytest.approx(0.0, abs=0.01)
    assert float(merged_placement["y_mm"]) == pytest.approx(0.0, abs=0.01)
    assert float(merged_placement["rotation_deg"]) == 0.0

    # The new merged InsertDesign has the resolved combined grid dimensions,
    # is queued for real generation, and carries merge provenance.
    design_resp = await client.get(f"/organizations/{org_id}/insert-designs/{merged_design_id}", headers=headers)
    assert design_resp.status_code == 200
    design_body = design_resp.json()
    assert design_body["source"] == "generated"
    assert design_body["status"] == "queued"
    assert design_body["parameters_json"]["grid_width_units"] == 2
    assert design_body["parameters_json"]["grid_depth_units"] == 2
    assert design_body["parameters_json"]["height_units"] == 1
    assert design_body["parameters_json"]["compartments_x"] == 1
    assert design_body["parameters_json"]["compartments_y"] == 1
    assert f"Merged 4 bins from layout {layout_id}" == design_body["source_reference"]

    # Non-destructive: the original layout and its 4 placements, and the
    # original InsertDesign, are completely untouched.
    original_layout_resp = await client.get(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]) + f"/{layout_id}",
        headers=headers,
    )
    assert original_layout_resp.status_code == 200
    original_layout_body = original_layout_resp.json()
    assert len(original_layout_body["placements"]) == 4
    assert original_layout_body["layout_json"]["merges"] == []

    original_design_resp = await client.get(f"/organizations/{org_id}/insert-designs/{small_bin['id']}", headers=headers)
    assert original_design_resp.status_code == 200
    assert original_design_resp.json() == small_bin

    # Poll the merged design to `generated` (calling the worker's async
    # implementation directly, bypassing Dramatiq/Redis -- same technique as
    # test_insert_designs.py::test_generate_bin_design_writes_stl_file) and
    # independently verify its real exported STL's bounding box matches the
    # expected combined 2x2 grid footprint.
    await worker_tasks._generate_bin_design(merged_design_id)
    generated_resp = await client.get(f"/organizations/{org_id}/insert-designs/{merged_design_id}", headers=headers)
    assert generated_resp.status_code == 200
    generated_body = generated_resp.json()
    assert generated_body["status"] == "generated"
    assert generated_body["error_message"] is None

    stl_path = generated_body["stl_path"]
    mesh = trimesh.load(stl_path)
    assert mesh.is_watertight
    bounds = mesh.bounds
    mesh_width = bounds[1][0] - bounds[0][0]
    mesh_depth = bounds[1][1] - bounds[0][1]
    assert mesh_width == pytest.approx(42 * 2 - 0.5, abs=0.2)
    assert mesh_depth == pytest.approx(42 * 2 - 0.5, abs=0.2)


async def test_merge_rejects_adjacent_bins_with_incompatible_height_units(
    client: AsyncClient, db_session: AsyncSession, tmp_path, monkeypatch
) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]
    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))

    bin_h1 = await _generate_bin(client, headers, org_id, name="Short Bin", grid_width_units=1, grid_depth_units=1, height_units=1)
    bin_h2 = await _generate_bin(client, headers, org_id, name="Tall Bin", grid_width_units=1, grid_depth_units=1, height_units=2)
    # Force both through to `status="generated"` -- otherwise they'd both be
    # filtered out by eligibility alone, and this test wouldn't actually
    # exercise the compatibility-key mismatch it claims to.
    await worker_tasks._generate_bin_design(bin_h1["id"])
    await worker_tasks._generate_bin_design(bin_h2["id"])
    w1 = bin_h1["bounds_json"]["width_mm"]

    chain = await _build_drawer(
        client, headers, org_id, inside_width_mm="200", inside_depth_mm="200", inside_height_mm="100"
    )

    # Placed touching (flush, x2 starts exactly where x1 ends) but with
    # different height_units -- must NOT merge (compatibility key mismatch).
    layout_id = await _insert_layout_with_placements(
        db_session,
        drawer_id=chain["drawer_id"],
        placements=[(bin_h1["id"], 0.0, 0.0), (bin_h2["id"], w1, 0.0)],
    )

    merge_resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]) + f"/{layout_id}/merge",
        headers=headers,
    )
    assert merge_resp.status_code == 201, merge_resp.text
    body = merge_resp.json()
    assert body["layout_json"]["merges"] == []
    assert len(body["placements"]) == 2
    result_design_ids = {p["insert_design_id"] for p in body["placements"]}
    assert result_design_ids == {bin_h1["id"], bin_h2["id"]}


async def test_merge_rejects_adjacent_bins_with_dividers(
    client: AsyncClient, db_session: AsyncSession, tmp_path, monkeypatch
) -> None:
    """A bin with compartments_x=2 (internal dividers) is never a merge
    candidate, even if geometrically adjacent to an otherwise-compatible
    single-cell bin -- per the plan's explicit scope limit."""
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]
    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))

    single_cell = await _generate_bin(client, headers, org_id, name="Single Cell", grid_width_units=1, grid_depth_units=1, height_units=1)

    # A 2-wide bin with 2 x-compartments, same height_units -- otherwise
    # compatibility-key-identical to single_cell.
    divided_resp = await client.post(
        f"/organizations/{org_id}/insert-designs/generate-bin",
        json={"name": "Divided Bin", "grid_width_units": 2, "grid_depth_units": 1, "height_units": 1, "compartments_x": 2, "compartments_y": 1},
        headers=headers,
    )
    assert divided_resp.status_code == 201, divided_resp.text
    divided = divided_resp.json()

    # Force both to `status="generated"` -- proves the rejection is really
    # from the compartments_x/y==1 eligibility filter, not incidental
    # `status="queued"` filtering.
    await worker_tasks._generate_bin_design(single_cell["id"])
    await worker_tasks._generate_bin_design(divided["id"])

    w1 = single_cell["bounds_json"]["width_mm"]

    chain = await _build_drawer(
        client, headers, org_id, inside_width_mm="200", inside_depth_mm="200", inside_height_mm="100"
    )
    layout_id = await _insert_layout_with_placements(
        db_session,
        drawer_id=chain["drawer_id"],
        placements=[(single_cell["id"], 0.0, 0.0), (divided["id"], w1, 0.0)],
    )

    merge_resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]) + f"/{layout_id}/merge",
        headers=headers,
    )
    assert merge_resp.status_code == 201, merge_resp.text
    body = merge_resp.json()
    assert body["layout_json"]["merges"] == []
    assert len(body["placements"]) == 2


async def test_merge_rejects_l_shaped_cluster(
    client: AsyncClient, db_session: AsyncSession, tmp_path, monkeypatch
) -> None:
    """3 identical, compatible, pairwise-adjacent bins arranged in an L-shape
    (not a clean rectangle) must NOT merge. This is the plan's deliberate
    "reject the whole component" rule -- find_merge_clusters does not attempt
    partial/general rectilinear-polygon decomposition, so none of the 3
    bins merge, even though pairs of them are individually adjacent."""
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]
    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))

    bin_a = await _generate_bin(client, headers, org_id, name="L Bin", grid_width_units=1, grid_depth_units=1, height_units=1)
    await worker_tasks._generate_bin_design(bin_a["id"])
    w = bin_a["bounds_json"]["width_mm"]
    d = bin_a["bounds_json"]["depth_mm"]

    # Re-use the same design for all 3 placements (identical bin, 3 copies)
    # at (0,0), (w,0), (0,d) -- an L-shape missing the (w,d) corner.
    chain = await _build_drawer(
        client, headers, org_id, inside_width_mm="200", inside_depth_mm="200", inside_height_mm="100"
    )
    layout_id = await _insert_layout_with_placements(
        db_session,
        drawer_id=chain["drawer_id"],
        placements=[(bin_a["id"], 0.0, 0.0), (bin_a["id"], w, 0.0), (bin_a["id"], 0.0, d)],
    )

    merge_resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]) + f"/{layout_id}/merge",
        headers=headers,
    )
    assert merge_resp.status_code == 201, merge_resp.text
    body = merge_resp.json()
    assert body["layout_json"]["merges"] == [], "L-shaped cluster must not merge (bounding box has more area than the 3 members)"
    assert len(body["placements"]) == 3


async def test_merge_with_nothing_to_merge_returns_201_with_empty_merges(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    small_bin = await _generate_bin(client, headers, org_id, name="Lonely Bin", grid_width_units=1, grid_depth_units=1)

    chain = await _build_drawer(
        client, headers, org_id, inside_width_mm="300", inside_depth_mm="300", inside_height_mm="50"
    )
    await _create_tool(
        client, headers, org_id, name="Solo Tool", drawer_id=chain["drawer_id"],
        insert_design_id=small_bin["id"], quantity=1, insert_quantity=1,
    )

    layout_resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]), headers=headers
    )
    assert layout_resp.status_code == 201, layout_resp.text
    layout_id = layout_resp.json()["id"]
    assert len(layout_resp.json()["placements"]) == 1

    merge_resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]) + f"/{layout_id}/merge",
        headers=headers,
    )
    assert merge_resp.status_code == 201, merge_resp.text
    body = merge_resp.json()
    assert body["layout_json"]["merges"] == []
    assert len(body["placements"]) == 1
    assert body["placements"][0]["insert_design_id"] == small_bin["id"]
