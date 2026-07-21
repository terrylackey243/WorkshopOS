from httpx import AsyncClient

from .conftest import auth_headers, register_org


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
