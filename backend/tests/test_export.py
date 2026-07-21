from __future__ import annotations

import io
import json
import zipfile

from httpx import AsyncClient

from .conftest import auth_headers, register_org


def _tiny_jpeg() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"


async def _build_drawer(client: AsyncClient, headers: dict, org_id: str) -> dict:
    """Real org -> shop -> toolbox -> drawer-profile -> drawer chain, same
    pattern as test_drawer_layouts.py::_build_drawer."""
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
            "inside_width_mm": "300",
            "inside_depth_mm": "400",
            "inside_height_mm": "50",
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

    return {
        "shop_id": shop_id,
        "toolbox_id": toolbox_id,
        "drawer_profile_id": drawer_profile_id,
        "drawer_id": drawer_resp.json()["id"],
    }


async def test_export_zip_round_trips_data_and_includes_a_real_file(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    chain = await _build_drawer(client, headers, org_id)

    tool_resp = await client.post(
        f"/organizations/{org_id}/tools", json={"name": "Impact Driver", "quantity": 1}, headers=headers
    )
    assert tool_resp.status_code == 201, tool_resp.text
    tool_id = tool_resp.json()["id"]

    photo_bytes = _tiny_jpeg()
    upload_resp = await client.post(
        f"/organizations/{org_id}/tools/{tool_id}/photo",
        files={"file": ("drill.jpg", photo_bytes, "image/jpeg")},
        headers=headers,
    )
    assert upload_resp.status_code == 201, upload_resp.text

    export_resp = await client.get(f"/organizations/{org_id}/export", headers=headers)
    assert export_resp.status_code == 200, export_resp.text
    assert export_resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(export_resp.content))
    names = zf.namelist()
    assert "data.json" in names

    data = json.loads(zf.read("data.json"))
    assert len(data["shops"]) == 1
    assert data["shops"][0]["id"] == chain["shop_id"]
    assert len(data["toolboxes"]) == 1
    assert len(data["drawers"]) == 1
    assert len(data["drawer_profiles"]) == 1
    assert len(data["tools"]) == 1
    assert data["tools"][0]["name"] == "Impact Driver"
    assert data["tools"][0]["has_photo"] is True
    assert data["insert_designs"] == []
    assert data["designs"] == []
    assert data["drawer_layouts"] == []

    photo_entries = [n for n in names if n.startswith("files/") and n.endswith(".jpg")]
    assert len(photo_entries) == 1
    assert zf.read(photo_entries[0]) == photo_bytes


async def test_export_skips_missing_files_without_failing(client: AsyncClient) -> None:
    """A design/insert row whose stl_path points at a file that no longer
    exists on disk must not fail the whole export -- matches this app's
    established defensive is_file()-check-before-serving convention."""
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    tool_resp = await client.post(
        f"/organizations/{org_id}/tools", json={"name": "Idle Tool", "quantity": 1}, headers=headers
    )
    assert tool_resp.status_code == 201, tool_resp.text

    export_resp = await client.get(f"/organizations/{org_id}/export", headers=headers)
    assert export_resp.status_code == 200, export_resp.text

    zf = zipfile.ZipFile(io.BytesIO(export_resp.content))
    data = json.loads(zf.read("data.json"))
    assert len(data["tools"]) == 1
    assert data["tools"][0]["has_photo"] is False
    assert [n for n in zf.namelist() if n.startswith("files/")] == []


async def test_export_does_not_leak_across_organizations(client: AsyncClient) -> None:
    org_a = await register_org(client)
    org_a_id = org_a["organization_id"]
    headers_a = auth_headers(org_a["access_token"])
    await client.post(f"/organizations/{org_a_id}/tools", json={"name": "Org A Tool"}, headers=headers_a)

    org_b = await register_org(client)
    org_b_id = org_b["organization_id"]
    headers_b = auth_headers(org_b["access_token"])

    export_resp = await client.get(f"/organizations/{org_b_id}/export", headers=headers_b)
    assert export_resp.status_code == 200, export_resp.text
    zf = zipfile.ZipFile(io.BytesIO(export_resp.content))
    data = json.loads(zf.read("data.json"))
    assert data["tools"] == []
    assert data["shops"] == []
