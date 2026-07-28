from httpx import AsyncClient

from .conftest import auth_headers, register_org


async def test_printer_profile_crud_and_default_flip(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    first = await client.post(
        f"/organizations/{org_id}/profiles/printers",
        json={
            "name": "Bambu X1C",
            "build_width_mm": "256",
            "build_depth_mm": "256",
            "build_height_mm": "256",
            "is_default": True,
        },
        headers=headers,
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]
    assert first.json()["is_default"] is True

    second = await client.post(
        f"/organizations/{org_id}/profiles/printers",
        json={
            "name": "Prusa MK4",
            "build_width_mm": "250",
            "build_depth_mm": "210",
            "build_height_mm": "220",
            "is_default": True,
        },
        headers=headers,
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]
    assert second.json()["is_default"] is True

    # Creating a second is_default=True profile must flip the first one off.
    refreshed_first = await client.get(f"/organizations/{org_id}/profiles/printers/{first_id}", headers=headers)
    assert refreshed_first.json()["is_default"] is False

    patch_resp = await client.patch(
        f"/organizations/{org_id}/profiles/printers/{first_id}",
        json={"name": "Bambu X1 Carbon"},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "Bambu X1 Carbon"

    default_resp = await client.post(
        f"/organizations/{org_id}/profiles/printers/{first_id}/default", headers=headers
    )
    assert default_resp.status_code == 200
    assert default_resp.json()["is_default"] is True

    refreshed_second = await client.get(f"/organizations/{org_id}/profiles/printers/{second_id}", headers=headers)
    assert refreshed_second.json()["is_default"] is False

    delete_resp = await client.delete(f"/organizations/{org_id}/profiles/printers/{second_id}", headers=headers)
    assert delete_resp.status_code == 204


async def test_duplicate_profile_name_conflicts(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    payload = {"name": "PLA Standard", "material_type": "PLA"}
    first = await client.post(f"/organizations/{org_id}/profiles/materials", json=payload, headers=headers)
    assert first.status_code == 201

    second = await client.post(f"/organizations/{org_id}/profiles/materials", json=payload, headers=headers)
    assert second.status_code == 409


async def test_magnet_and_label_style_profiles_smoke(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    magnet_resp = await client.post(
        f"/organizations/{org_id}/profiles/magnets",
        json={"name": "6x2.5mm", "diameter_mm": "6", "thickness_mm": "2.5"},
        headers=headers,
    )
    assert magnet_resp.status_code == 201, magnet_resp.text
    magnet_id = magnet_resp.json()["id"]

    label_resp = await client.post(
        f"/organizations/{org_id}/profiles/label-styles",
        json={"name": "Default Style", "default_magnet_profile_id": magnet_id},
        headers=headers,
    )
    assert label_resp.status_code == 201, label_resp.text
    assert label_resp.json()["default_magnet_profile_id"] == magnet_id
    assert float(label_resp.json()["text_height_mm"]) == 15.843


async def test_magnet_sealed_fit_requires_seal_cap_mm(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    missing_cap = await client.post(
        f"/organizations/{org_id}/profiles/magnets",
        json={"name": "Sealed 6x2.5mm", "diameter_mm": "6", "thickness_mm": "2.5", "fit_type": "sealed"},
        headers=headers,
    )
    assert missing_cap.status_code == 422, missing_cap.text

    ok = await client.post(
        f"/organizations/{org_id}/profiles/magnets",
        json={
            "name": "Sealed 6x2.5mm",
            "diameter_mm": "6",
            "thickness_mm": "2.5",
            "fit_type": "sealed",
            "seal_cap_mm": "0.6",
        },
        headers=headers,
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["fit_type"] == "sealed"
    assert float(ok.json()["seal_cap_mm"]) == 0.6


async def test_magnet_non_sealed_fit_rejects_seal_cap_mm(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    resp = await client.post(
        f"/organizations/{org_id}/profiles/magnets",
        json={
            "name": "Glued 6x2.5mm",
            "diameter_mm": "6",
            "thickness_mm": "2.5",
            "fit_type": "glue",
            "seal_cap_mm": "0.6",
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
