from __future__ import annotations

from httpx import AsyncClient

from .conftest import auth_headers, register_org


async def _build_drawer(
    client: AsyncClient,
    headers: dict,
    org_id: str,
    *,
    inside_width_mm: str,
    inside_depth_mm: str,
    inside_height_mm: str,
) -> dict:
    """Real org -> shop -> toolbox -> drawer-profile -> drawer chain, same
    pattern as test_shops.py::test_shop_toolbox_drawer_chain."""
    shop_resp = await client.post(
        f"/organizations/{org_id}/shops",
        json={"name": "Main Garage", "slug": "main-garage"},
        headers=headers,
    )
    assert shop_resp.status_code == 201, shop_resp.text
    shop_id = shop_resp.json()["id"]

    toolbox_resp = await client.post(
        f"/organizations/{org_id}/shops/{shop_id}/toolboxes",
        json={"name": "Rolling Cart"},
        headers=headers,
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

    return {
        "shop_id": shop_id,
        "toolbox_id": toolbox_id,
        "drawer_profile_id": drawer_profile_id,
        "drawer_id": drawer_id,
    }


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
    """Generates a real InsertDesign via the bin generator (same technique as
    test_insert_designs.py) -- gives us a real, known `bounds_json` footprint
    to pack, without hand-computing Gridfinity dimensions ourselves."""
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
    payload = {
        "name": name,
        "drawer_id": drawer_id,
        "insert_design_id": insert_design_id,
        "quantity": quantity,
    }
    if insert_quantity is not None:
        payload["insert_quantity"] = insert_quantity
    resp = await client.post(f"/organizations/{org_id}/tools", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _layouts_url(org_id: str, shop_id: str, toolbox_id: str, drawer_id: str) -> str:
    return f"/organizations/{org_id}/shops/{shop_id}/toolboxes/{toolbox_id}/drawers/{drawer_id}/layouts"


def _placement_rect(placement: dict, bounds_by_design: dict[str, tuple[float, float]]) -> tuple[float, float, float, float]:
    """Resolve a placement's actual (x, y, w, h) rectangle, swapping w/h when
    rotated -- matches how the frontend is expected to reconstruct geometry
    from `insert_design_id` + `rotation_deg` alone (InsertPlacementRead has
    no width/depth of its own, mirroring the underlying InsertPlacement
    table)."""
    width_mm, depth_mm = bounds_by_design[placement["insert_design_id"]]
    rotated = abs(float(placement["rotation_deg"])) > 45.0
    w, h = (depth_mm, width_mm) if rotated else (width_mm, depth_mm)
    return float(placement["x_mm"]), float(placement["y_mm"]), w, h


def _in_bounds(rect: tuple[float, float, float, float], bin_w: float, bin_d: float, tol: float = 1e-2) -> bool:
    x, y, w, h = rect
    return x >= -tol and y >= -tol and x + w <= bin_w + tol and y + h <= bin_d + tol


def _overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float], tol: float = 1e-6) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx + tol or bx + bw <= ax + tol or ay + ah <= by + tol or by + bh <= ay + tol)


def _assert_no_overlaps(rects: list[tuple[float, float, float, float]]) -> None:
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            assert not _overlaps(rects[i], rects[j]), f"placements overlap: {rects[i]} vs {rects[j]}"


async def test_generate_layout_places_items_without_overlap_or_out_of_bounds(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    chain = await _build_drawer(
        client, headers, org_id, inside_width_mm="500", inside_depth_mm="500", inside_height_mm="100"
    )

    bin_a = await _generate_bin(client, headers, org_id, name="Small Bin", grid_width_units=1, grid_depth_units=1)
    bin_b = await _generate_bin(client, headers, org_id, name="Wide Bin", grid_width_units=2, grid_depth_units=1)

    tool_a = await _create_tool(
        client, headers, org_id, name="Chisel Set", drawer_id=chain["drawer_id"],
        insert_design_id=bin_a["id"], quantity=5, insert_quantity=3,
    )
    tool_b = await _create_tool(
        client, headers, org_id, name="Screwdriver Set", drawer_id=chain["drawer_id"],
        insert_design_id=bin_b["id"], quantity=2, insert_quantity=2,
    )
    assert tool_a["insert_quantity"] == 3
    assert tool_b["insert_quantity"] == 2

    resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]), headers=headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "computed"
    assert body["drawer_id"] == chain["drawer_id"]

    unplaced = body["layout_json"]["unplaced"]
    assert unplaced == [], f"expected everything to fit in a generous drawer, got unplaced: {unplaced}"
    assert len(body["placements"]) == 3 + 2

    utilization_pct = body["layout_json"]["utilization_pct"]
    assert 0.0 < utilization_pct < 100.0

    bounds_by_design = {
        bin_a["id"]: (bin_a["bounds_json"]["width_mm"], bin_a["bounds_json"]["depth_mm"]),
        bin_b["id"]: (bin_b["bounds_json"]["width_mm"], bin_b["bounds_json"]["depth_mm"]),
    }
    rects = [_placement_rect(p, bounds_by_design) for p in body["placements"]]
    for rect in rects:
        assert _in_bounds(rect, 500.0, 500.0), f"placement out of bounds: {rect}"
    _assert_no_overlaps(rects)

    # GET list (newest first) and GET by id both return the same nested shape.
    list_resp = await client.get(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]), headers=headers
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["id"] == body["id"]
    assert len(list_resp.json()[0]["placements"]) == 5

    get_resp = await client.get(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]) + f"/{body['id']}",
        headers=headers,
    )
    assert get_resp.status_code == 200
    assert len(get_resp.json()["placements"]) == 5


async def test_generate_layout_requires_rotation_to_fit(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    # An elongated bin (narrow width, long depth) -- generated for real, not
    # hand-computed, so we read its actual footprint back off the response.
    long_bin = await _generate_bin(
        client, headers, org_id, name="Long Bin", grid_width_units=1, grid_depth_units=5, height_units=1
    )
    item_w = long_bin["bounds_json"]["width_mm"]
    item_d = long_bin["bounds_json"]["depth_mm"]
    assert item_d > item_w, "expected an elongated (deeper than wide) bin for this test to be meaningful"

    # Sized so the item's *original* orientation cannot fit (depth exceeds
    # the drawer's depth) but the *rotated* orientation fits exactly.
    drawer_width = item_d + 5.0
    drawer_depth = item_w + 5.0
    chain = await _build_drawer(
        client, headers, org_id,
        inside_width_mm=str(drawer_width), inside_depth_mm=str(drawer_depth), inside_height_mm="100",
    )

    await _create_tool(
        client, headers, org_id, name="Long Level", drawer_id=chain["drawer_id"],
        insert_design_id=long_bin["id"], quantity=1, insert_quantity=1,
    )

    resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]), headers=headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["layout_json"]["unplaced"] == []
    assert len(body["placements"]) == 1

    placement = body["placements"][0]
    assert abs(float(placement["rotation_deg"])) > 45.0, f"expected rotation, got {placement}"

    rect = _placement_rect(placement, {long_bin["id"]: (item_w, item_d)})
    assert _in_bounds(rect, drawer_width, drawer_depth)


async def test_generate_layout_reports_no_space_for_excess_items(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    small_bin = await _generate_bin(client, headers, org_id, name="Unit Bin", grid_width_units=1, grid_depth_units=1)
    item_w = small_bin["bounds_json"]["width_mm"]
    item_d = small_bin["bounds_json"]["depth_mm"]

    # A drawer just barely big enough for one copy of the bin, but we'll ask
    # for far more copies than can possibly fit.
    chain = await _build_drawer(
        client, headers, org_id,
        inside_width_mm=str(item_w + 2.0), inside_depth_mm=str(item_d + 2.0), inside_height_mm="100",
    )

    await _create_tool(
        client, headers, org_id, name="Bit Set", drawer_id=chain["drawer_id"],
        insert_design_id=small_bin["id"], quantity=10, insert_quantity=8,
    )

    resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]), headers=headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    unplaced = body["layout_json"]["unplaced"]
    assert len(unplaced) > 0
    assert all(u["reason"] == "no space" for u in unplaced)
    assert len(body["placements"]) + len(unplaced) == 8

    bounds_by_design = {small_bin["id"]: (item_w, item_d)}
    rects = [_placement_rect(p, bounds_by_design) for p in body["placements"]]
    for rect in rects:
        assert _in_bounds(rect, item_w + 2.0, item_d + 2.0), f"placement out of bounds: {rect}"
    _assert_no_overlaps(rects)


async def test_generate_layout_returns_422_when_no_tools_have_insert(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    chain = await _build_drawer(
        client, headers, org_id, inside_width_mm="300", inside_depth_mm="300", inside_height_mm="50"
    )

    # A tool in the drawer, but with no insert_design_id linked -- still
    # ineligible for packing.
    resp = await client.post(
        f"/organizations/{org_id}/tools",
        json={"name": "Bare Hammer", "drawer_id": chain["drawer_id"], "quantity": 1},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    layout_resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]), headers=headers
    )
    assert layout_resp.status_code == 422, layout_resp.text


async def test_generate_layout_marks_oversized_height_unplaced(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    tall_bin = await _generate_bin(
        client, headers, org_id, name="Tall Bin", grid_width_units=1, grid_depth_units=1, height_units=3
    )
    tall_height = tall_bin["bounds_json"]["height_mm"]

    # Drawer height deliberately smaller than the bin's height.
    assert tall_height > 10.0, "expected the height-3-unit bin to be taller than 10mm for this test to be meaningful"
    chain = await _build_drawer(
        client, headers, org_id, inside_width_mm="300", inside_depth_mm="300", inside_height_mm="10"
    )

    await _create_tool(
        client, headers, org_id, name="Tall Tool", drawer_id=chain["drawer_id"],
        insert_design_id=tall_bin["id"], quantity=1, insert_quantity=1,
    )

    resp = await client.post(
        _layouts_url(org_id, chain["shop_id"], chain["toolbox_id"], chain["drawer_id"]), headers=headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["placements"] == []
    unplaced = body["layout_json"]["unplaced"]
    assert len(unplaced) == 1
    assert unplaced[0]["reason"] == "exceeds drawer height"
    assert unplaced[0]["insert_design_id"] == tall_bin["id"]
