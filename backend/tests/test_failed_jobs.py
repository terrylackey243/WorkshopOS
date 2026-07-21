from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DrawerLayout

from .conftest import auth_headers, register_org


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
        "drawer_id": drawer_resp.json()["id"],
    }


async def _create_failed_design(client: AsyncClient, headers: dict, org_id: str, db_session: AsyncSession) -> str:
    style_resp = await client.post(
        f"/organizations/{org_id}/profiles/label-styles", json={"name": "Test Style"}, headers=headers
    )
    assert style_resp.status_code == 201, style_resp.text
    style_id = style_resp.json()["id"]

    design_resp = await client.post(
        f"/organizations/{org_id}/designs",
        json={"name": "Broken Label", "text": "HELLO", "label_style_profile_id": style_id},
        headers=headers,
    )
    assert design_resp.status_code == 201, design_resp.text
    design_id = design_resp.json()["id"]

    await db_session.execute(
        text("UPDATE designs SET status = 'failed', error_message = :msg WHERE id = :id"),
        {"msg": "label geometry blew up", "id": design_id},
    )
    await db_session.commit()
    return design_id


async def _create_failed_insert_design(
    client: AsyncClient, headers: dict, org_id: str, db_session: AsyncSession
) -> str:
    bin_resp = await client.post(
        f"/organizations/{org_id}/insert-designs/generate-bin",
        json={"name": "Broken Bin", "grid_width_units": 2, "grid_depth_units": 2, "height_units": 3},
        headers=headers,
    )
    assert bin_resp.status_code == 201, bin_resp.text
    insert_id = bin_resp.json()["id"]

    await db_session.execute(
        text("UPDATE insert_designs SET status = 'failed', error_message = :msg WHERE id = :id"),
        {"msg": "bin geometry blew up", "id": insert_id},
    )
    await db_session.commit()
    return insert_id


async def _create_layout_with_one_failed_plate(db_session: AsyncSession, drawer_id: str) -> str:
    layout = DrawerLayout(
        drawer_id=uuid.UUID(drawer_id),
        status="exported",
        layout_json={
            "unplaced": [],
            "plates": [
                {"plate_index": 0, "status": "generated", "stl_path": "/tmp/plate-0.stl", "error_message": None},
                {"plate_index": 1, "status": "failed", "stl_path": None, "error_message": "plate CSG failed"},
            ],
        },
    )
    db_session.add(layout)
    await db_session.commit()
    await db_session.refresh(layout)
    return str(layout.id)


async def test_failed_jobs_surfaces_all_three_kinds(client: AsyncClient, db_session: AsyncSession) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    chain = await _build_drawer(client, headers, org_id)
    design_id = await _create_failed_design(client, headers, org_id, db_session)
    insert_id = await _create_failed_insert_design(client, headers, org_id, db_session)
    layout_id = await _create_layout_with_one_failed_plate(db_session, chain["drawer_id"])

    resp = await client.get(f"/organizations/{org_id}/failed-jobs", headers=headers)
    assert resp.status_code == 200, resp.text
    jobs = resp.json()

    by_kind = {job["kind"]: job for job in jobs}
    assert set(by_kind.keys()) == {"label", "insert", "plate"}

    assert by_kind["label"]["id"] == design_id
    assert by_kind["label"]["error_message"] == "label geometry blew up"
    assert by_kind["label"]["link"] == f"/label-designer/{design_id}"

    assert by_kind["insert"]["id"] == insert_id
    assert by_kind["insert"]["error_message"] == "bin geometry blew up"
    assert by_kind["insert"]["link"] == f"/inserts/{insert_id}"

    assert by_kind["plate"]["id"] == f"{layout_id}:1"
    assert by_kind["plate"]["error_message"] == "plate CSG failed"
    assert by_kind["plate"]["link"] == f"/shops/{chain['shop_id']}/toolboxes/{chain['toolbox_id']}/drawers/{chain['drawer_id']}"

    # Only 3 entries total -- the generated (non-failed) plate must not appear.
    assert len(jobs) == 3


async def test_layout_with_no_failed_plates_contributes_nothing(client: AsyncClient, db_session: AsyncSession) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    chain = await _build_drawer(client, headers, org_id)

    layout = DrawerLayout(
        drawer_id=uuid.UUID(chain["drawer_id"]),
        status="computed",
        layout_json={"unplaced": [], "plates": []},
    )
    db_session.add(layout)
    await db_session.commit()

    resp = await client.get(f"/organizations/{org_id}/failed-jobs", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_failed_jobs_does_not_leak_across_organizations(client: AsyncClient, db_session: AsyncSession) -> None:
    org_a = await register_org(client)
    org_a_id = org_a["organization_id"]
    headers_a = auth_headers(org_a["access_token"])
    await _create_failed_design(client, headers_a, org_a_id, db_session)

    org_b = await register_org(client)
    org_b_id = org_b["organization_id"]
    headers_b = auth_headers(org_b["access_token"])

    resp = await client.get(f"/organizations/{org_b_id}/failed-jobs", headers=headers_b)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
