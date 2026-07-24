from httpx import AsyncClient

from .conftest import auth_headers, register_org


async def _build_shop_toolbox_profile(client: AsyncClient, headers: dict, org_id: str) -> dict:
    """Real org -> shop -> toolbox -> drawer-profile chain, no drawer yet --
    callers create their own drawers to exercise row/order_in_row behavior."""
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
        json={"name": "Test Drawer Profile", "inside_width_mm": "100", "inside_depth_mm": "100", "inside_height_mm": "50"},
        headers=headers,
    )
    assert profile_resp.status_code == 201, profile_resp.text

    return {"shop_id": shop_id, "toolbox_id": toolbox_id, "drawer_profile_id": profile_resp.json()["id"]}


async def _create_drawer(
    client: AsyncClient, headers: dict, org_id: str, chain: dict, *, row: int | None = None, name: str | None = None
) -> dict:
    resp = await client.post(
        f"/organizations/{org_id}/shops/{chain['shop_id']}/toolboxes/{chain['toolbox_id']}/drawers",
        json={"drawer_profile_id": chain["drawer_profile_id"], "name": name, "row": row},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_drawer_list_orders_by_row_then_order_in_row_nulls_last(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    chain = await _build_shop_toolbox_profile(client, headers, org_id)

    unplaced = await _create_drawer(client, headers, org_id, chain, name="Unplaced")
    row2_second = await _create_drawer(client, headers, org_id, chain, row=2, name="Row2-Second")
    row1 = await _create_drawer(client, headers, org_id, chain, row=1, name="Row1")
    row2_first = await _create_drawer(client, headers, org_id, chain, row=2, name="Row2-First")

    list_resp = await client.get(
        f"/organizations/{org_id}/shops/{chain['shop_id']}/toolboxes/{chain['toolbox_id']}/drawers",
        headers=headers,
    )
    assert list_resp.status_code == 200
    ids_in_order = [d["id"] for d in list_resp.json()]
    assert ids_in_order == [row1["id"], row2_second["id"], row2_first["id"], unplaced["id"]]


async def test_drawer_create_auto_assigns_order_in_row_within_row(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    chain = await _build_shop_toolbox_profile(client, headers, org_id)

    first = await _create_drawer(client, headers, org_id, chain, row=1, name="First")
    second = await _create_drawer(client, headers, org_id, chain, row=1, name="Second")
    other_row = await _create_drawer(client, headers, org_id, chain, row=2, name="OtherRow")

    assert first["order_in_row"] == 0
    assert second["order_in_row"] == 1
    assert other_row["order_in_row"] == 0
    assert first["row"] == 1 and second["row"] == 1 and other_row["row"] == 2


async def test_drawer_move_right_swaps_within_row_only(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    chain = await _build_shop_toolbox_profile(client, headers, org_id)

    first = await _create_drawer(client, headers, org_id, chain, row=1, name="First")
    second = await _create_drawer(client, headers, org_id, chain, row=1, name="Second")
    other_row = await _create_drawer(client, headers, org_id, chain, row=2, name="OtherRow")

    move_resp = await client.post(
        f"/organizations/{org_id}/shops/{chain['shop_id']}/toolboxes/{chain['toolbox_id']}/drawers/{first['id']}/move-right",
        headers=headers,
    )
    assert move_resp.status_code == 200
    assert move_resp.json()["order_in_row"] == 1

    list_resp = await client.get(
        f"/organizations/{org_id}/shops/{chain['shop_id']}/toolboxes/{chain['toolbox_id']}/drawers",
        headers=headers,
    )
    by_id = {d["id"]: d for d in list_resp.json()}
    assert by_id[first["id"]]["order_in_row"] == 1
    assert by_id[second["id"]]["order_in_row"] == 0
    # A drawer in a different row is untouched by the swap.
    assert by_id[other_row["id"]]["order_in_row"] == 0


async def test_drawer_move_rejects_when_row_is_null(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    chain = await _build_shop_toolbox_profile(client, headers, org_id)

    unplaced = await _create_drawer(client, headers, org_id, chain, name="Unplaced")

    move_resp = await client.post(
        f"/organizations/{org_id}/shops/{chain['shop_id']}/toolboxes/{chain['toolbox_id']}/drawers/{unplaced['id']}/move-left",
        headers=headers,
    )
    assert move_resp.status_code == 400


async def test_drawer_update_row_recomputes_order_in_row(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    chain = await _build_shop_toolbox_profile(client, headers, org_id)

    # Row 2 already has one drawer at order_in_row=0.
    await _create_drawer(client, headers, org_id, chain, row=2, name="ExistingRow2")
    moving = await _create_drawer(client, headers, org_id, chain, row=1, name="Moving")
    assert moving["order_in_row"] == 0

    patch_resp = await client.patch(
        f"/organizations/{org_id}/shops/{chain['shop_id']}/toolboxes/{chain['toolbox_id']}/drawers/{moving['id']}",
        json={"row": 2},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    # Appended to the end of row 2 (which already had one drawer at 0), not
    # left with its stale row-1 order_in_row of 0.
    assert patch_resp.json()["row"] == 2
    assert patch_resp.json()["order_in_row"] == 1


async def test_shop_toolbox_drawer_chain(client: AsyncClient) -> None:
    data = await register_org(client)
    token = data["access_token"]
    org_id = data["organization_id"]
    headers = auth_headers(token)

    shop_resp = await client.post(
        f"/organizations/{org_id}/shops",
        json={"name": "Main Garage", "slug": "main-garage"},
        headers=headers,
    )
    assert shop_resp.status_code == 201, shop_resp.text
    shop_id = shop_resp.json()["id"]

    toolbox_resp = await client.post(
        f"/organizations/{org_id}/shops/{shop_id}/toolboxes",
        json={"name": "Rolling Cart", "kind": "roller"},
        headers=headers,
    )
    assert toolbox_resp.status_code == 201, toolbox_resp.text
    toolbox_id = toolbox_resp.json()["id"]

    profile_resp = await client.post(
        f"/organizations/{org_id}/profiles/drawer-profiles",
        json={"name": "Standard Drawer", "inside_width_mm": "300", "inside_depth_mm": "400", "inside_height_mm": "50"},
        headers=headers,
    )
    assert profile_resp.status_code == 201, profile_resp.text
    drawer_profile_id = profile_resp.json()["id"]

    drawer_resp = await client.post(
        f"/organizations/{org_id}/shops/{shop_id}/toolboxes/{toolbox_id}/drawers",
        json={"drawer_profile_id": drawer_profile_id, "position_label": "top-left"},
        headers=headers,
    )
    assert drawer_resp.status_code == 201, drawer_resp.text
    drawer_id = drawer_resp.json()["id"]

    list_resp = await client.get(
        f"/organizations/{org_id}/shops/{shop_id}/toolboxes/{toolbox_id}/drawers", headers=headers
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["id"] == drawer_id


async def test_tool_crud_and_placement(client: AsyncClient) -> None:
    data = await register_org(client)
    token = data["access_token"]
    org_id = data["organization_id"]
    headers = auth_headers(token)

    tool_resp = await client.post(
        f"/organizations/{org_id}/tools",
        json={"name": "10mm Wrench", "category": "wrench", "quantity": 2},
        headers=headers,
    )
    assert tool_resp.status_code == 201, tool_resp.text
    tool_id = tool_resp.json()["id"]

    patch_resp = await client.patch(
        f"/organizations/{org_id}/tools/{tool_id}", json={"quantity": 3}, headers=headers
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["quantity"] == 3

    delete_resp = await client.delete(f"/organizations/{org_id}/tools/{tool_id}", headers=headers)
    assert delete_resp.status_code == 204


async def test_tool_insert_design_linkage(client: AsyncClient) -> None:
    data = await register_org(client)
    org_id = data["organization_id"]
    headers = auth_headers(data["access_token"])

    bin_resp = await client.post(
        f"/organizations/{org_id}/insert-designs/generate-bin",
        json={"name": "Screwdriver holder", "grid_width_units": 1, "grid_depth_units": 1, "height_units": 2},
        headers=headers,
    )
    assert bin_resp.status_code == 201, bin_resp.text
    insert_design_id = bin_resp.json()["id"]

    tool_resp = await client.post(
        f"/organizations/{org_id}/tools",
        json={"name": "Phillips Screwdriver", "insert_design_id": insert_design_id},
        headers=headers,
    )
    assert tool_resp.status_code == 201, tool_resp.text
    assert tool_resp.json()["insert_design_id"] == insert_design_id

    # A bad organization_id cross-tenant IDOR guard: a second org can't
    # attach its tool to the first org's InsertDesign.
    other = await register_org(client)
    other_headers = auth_headers(other["access_token"])
    cross_resp = await client.post(
        f"/organizations/{other['organization_id']}/tools",
        json={"name": "Sneaky tool", "insert_design_id": insert_design_id},
        headers=other_headers,
    )
    assert cross_resp.status_code == 400

    # Clearing the association back to null.
    tool_id = tool_resp.json()["id"]
    clear_resp = await client.patch(
        f"/organizations/{org_id}/tools/{tool_id}", json={"insert_design_id": None}, headers=headers
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["insert_design_id"] is None
