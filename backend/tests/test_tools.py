from __future__ import annotations

from httpx import AsyncClient

from .conftest import auth_headers, register_org


async def _build_shop_toolbox_drawer(
    client: AsyncClient, headers: dict, org_id: str, *, drawer_name: str | None, position_label: str | None
) -> dict:
    """Real org -> shop -> toolbox -> drawer-profile -> drawer chain, same
    pattern as test_drawer_layouts.py::_build_drawer, but exposes
    name/position_label so callers can exercise the location breadcrumb's
    fallback logic."""
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
    drawer_profile_id = profile_resp.json()["id"]

    drawer_resp = await client.post(
        f"/organizations/{org_id}/shops/{shop_id}/toolboxes/{toolbox_id}/drawers",
        json={"drawer_profile_id": drawer_profile_id, "name": drawer_name, "position_label": position_label},
        headers=headers,
    )
    assert drawer_resp.status_code == 201, drawer_resp.text

    return {"shop_id": shop_id, "toolbox_id": toolbox_id, "drawer_id": drawer_resp.json()["id"]}


async def test_tool_location_reflects_drawer_name(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    chain = await _build_shop_toolbox_drawer(
        client, headers, org_id, drawer_name="Top Left", position_label=None
    )

    tool_resp = await client.post(
        f"/organizations/{org_id}/tools",
        json={"name": "Phillips Screwdriver", "drawer_id": chain["drawer_id"], "quantity": 1},
        headers=headers,
    )
    assert tool_resp.status_code == 201, tool_resp.text
    location = tool_resp.json()["location"]
    assert location is not None
    assert location["shop_id"] == chain["shop_id"]
    assert location["shop_name"] == "Main Garage"
    assert location["toolbox_id"] == chain["toolbox_id"]
    assert location["toolbox_name"] == "Rolling Cart"
    assert location["drawer_id"] == chain["drawer_id"]
    assert location["drawer_label"] == "Top Left"

    # GET /tools and GET /tools/{id} must both carry the same location, not
    # just the create response.
    list_resp = await client.get(f"/organizations/{org_id}/tools", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["location"] == location

    get_resp = await client.get(f"/organizations/{org_id}/tools/{tool_resp.json()['id']}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["location"] == location


async def test_tool_location_falls_back_to_position_label(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    chain = await _build_shop_toolbox_drawer(
        client, headers, org_id, drawer_name=None, position_label="Row 2, Bin 4"
    )

    tool_resp = await client.post(
        f"/organizations/{org_id}/tools",
        json={"name": "Wrench Set", "drawer_id": chain["drawer_id"], "quantity": 1},
        headers=headers,
    )
    assert tool_resp.status_code == 201, tool_resp.text
    assert tool_resp.json()["location"]["drawer_label"] == "Row 2, Bin 4"


async def test_tool_location_falls_back_to_drawer_word_when_both_unset(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    chain = await _build_shop_toolbox_drawer(client, headers, org_id, drawer_name=None, position_label=None)

    tool_resp = await client.post(
        f"/organizations/{org_id}/tools",
        json={"name": "Tape Measure", "drawer_id": chain["drawer_id"], "quantity": 1},
        headers=headers,
    )
    assert tool_resp.status_code == 201, tool_resp.text
    assert tool_resp.json()["location"]["drawer_label"] == "Drawer"


async def test_unassigned_tool_has_null_location(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    tool_resp = await client.post(
        f"/organizations/{org_id}/tools", json={"name": "Loose Bolt", "quantity": 1}, headers=headers
    )
    assert tool_resp.status_code == 201, tool_resp.text
    assert tool_resp.json()["location"] is None

    list_resp = await client.get(f"/organizations/{org_id}/tools", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["location"] is None


async def test_reassigning_tool_updates_location(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    chain = await _build_shop_toolbox_drawer(client, headers, org_id, drawer_name="Drawer A", position_label=None)

    tool_resp = await client.post(
        f"/organizations/{org_id}/tools", json={"name": "Hammer", "quantity": 1}, headers=headers
    )
    assert tool_resp.json()["location"] is None
    tool_id = tool_resp.json()["id"]

    patch_resp = await client.patch(
        f"/organizations/{org_id}/tools/{tool_id}",
        json={"drawer_id": chain["drawer_id"]},
        headers=headers,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["location"]["drawer_label"] == "Drawer A"


async def test_tool_location_does_not_leak_across_organizations(client: AsyncClient) -> None:
    """A drawer in org A must never resolve as a location for a tool that
    (by construction) can only ever reference drawers within its own org --
    this asserts the join is scoped correctly, not just that it works for
    the happy path within a single org."""
    org_a = await register_org(client)
    org_a_id = org_a["organization_id"]
    headers_a = auth_headers(org_a["access_token"])

    org_b = await register_org(client)
    org_b_id = org_b["organization_id"]
    headers_b = auth_headers(org_b["access_token"])

    chain_a = await _build_shop_toolbox_drawer(
        client, headers_a, org_a_id, drawer_name="Org A Drawer", position_label=None
    )

    # A tool created in org B cannot reference org A's drawer at all --
    # the existing `_validate_drawer` check should reject it outright.
    tool_resp = await client.post(
        f"/organizations/{org_b_id}/tools",
        json={"name": "Cross-Org Tool", "drawer_id": chain_a["drawer_id"], "quantity": 1},
        headers=headers_b,
    )
    assert tool_resp.status_code == 400
