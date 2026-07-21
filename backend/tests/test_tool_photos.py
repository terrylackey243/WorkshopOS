from __future__ import annotations

from httpx import AsyncClient

from .conftest import auth_headers, register_org


def _tiny_jpeg() -> bytes:
    # Smallest valid-enough JPEG the extension check accepts -- content
    # sniffing isn't done server-side (matches the STL upload endpoint's
    # established "trust the extension" precedent), so real JPEG bytes
    # aren't required for these tests, just a filename ending in .jpg.
    return b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"


async def _create_tool(client: AsyncClient, headers: dict, org_id: str) -> str:
    resp = await client.post(
        f"/organizations/{org_id}/tools", json={"name": "Impact Driver", "quantity": 1}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["has_photo"] is False
    return resp.json()["id"]


async def test_upload_photo_sets_has_photo_and_serves_it_back(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id)

    photo_bytes = _tiny_jpeg()
    upload_resp = await client.post(
        f"/organizations/{org_id}/tools/{tool_id}/photo",
        headers=headers,
        files={"file": ("drill.jpg", photo_bytes, "image/jpeg")},
    )
    assert upload_resp.status_code == 201, upload_resp.text
    assert upload_resp.json()["has_photo"] is True

    get_resp = await client.get(f"/organizations/{org_id}/tools/{tool_id}", headers=headers)
    assert get_resp.json()["has_photo"] is True

    file_resp = await client.get(f"/organizations/{org_id}/tools/{tool_id}/photo", headers=headers)
    assert file_resp.status_code == 200
    assert file_resp.content == photo_bytes
    assert file_resp.headers["content-type"] == "image/jpeg"


async def test_replace_photo_removes_old_file(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id)

    await client.post(
        f"/organizations/{org_id}/tools/{tool_id}/photo",
        headers=headers,
        files={"file": ("first.jpg", _tiny_jpeg(), "image/jpeg")},
    )
    # Replace with a different extension -- the old .jpg must not linger.
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    resp = await client.post(
        f"/organizations/{org_id}/tools/{tool_id}/photo",
        headers=headers,
        files={"file": ("second.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 201, resp.text

    file_resp = await client.get(f"/organizations/{org_id}/tools/{tool_id}/photo", headers=headers)
    assert file_resp.content == png_bytes
    assert file_resp.headers["content-type"] == "image/png"


async def test_delete_photo_clears_has_photo_and_404s_after(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id)

    await client.post(
        f"/organizations/{org_id}/tools/{tool_id}/photo",
        headers=headers,
        files={"file": ("drill.jpg", _tiny_jpeg(), "image/jpeg")},
    )
    delete_resp = await client.delete(f"/organizations/{org_id}/tools/{tool_id}/photo", headers=headers)
    assert delete_resp.status_code == 200, delete_resp.text
    assert delete_resp.json()["has_photo"] is False

    file_resp = await client.get(f"/organizations/{org_id}/tools/{tool_id}/photo", headers=headers)
    assert file_resp.status_code == 404


async def test_get_photo_404s_when_none_uploaded(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id)

    resp = await client.get(f"/organizations/{org_id}/tools/{tool_id}/photo", headers=headers)
    assert resp.status_code == 404


async def test_upload_rejects_wrong_extension(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id)

    resp = await client.post(
        f"/organizations/{org_id}/tools/{tool_id}/photo",
        headers=headers,
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 422


async def test_upload_rejects_oversized_photo(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id)

    resp = await client.post(
        f"/organizations/{org_id}/tools/{tool_id}/photo",
        headers=headers,
        files={"file": ("huge.jpg", b"\x00" * (11 * 1024 * 1024), "image/jpeg")},
    )
    assert resp.status_code == 413


async def test_photo_does_not_leak_across_organizations(client: AsyncClient) -> None:
    org_a = await register_org(client)
    org_a_id = org_a["organization_id"]
    headers_a = auth_headers(org_a["access_token"])
    tool_id = await _create_tool(client, headers_a, org_a_id)
    await client.post(
        f"/organizations/{org_a_id}/tools/{tool_id}/photo",
        headers=headers_a,
        files={"file": ("drill.jpg", _tiny_jpeg(), "image/jpeg")},
    )

    org_b = await register_org(client)
    org_b_id = org_b["organization_id"]
    headers_b = auth_headers(org_b["access_token"])

    # org B can't even address org A's tool -- 404, not the photo bytes.
    resp = await client.get(f"/organizations/{org_b_id}/tools/{tool_id}/photo", headers=headers_b)
    assert resp.status_code == 404
