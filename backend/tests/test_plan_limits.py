"""Proves the Plan table isn't decorative: the free plan seeded in the
migration (1 shop / 1 toolbox / 10 drawers / 100 tools / 1 user) is actually
enforced by app.services.plan_limits.enforce_plan_limit, wired into the
create endpoints. Also covers Pro's tightened `max_shops=1` (see migration
0007's locked-in tier table).
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PRO_PLAN_ID, Organization

from .conftest import auth_headers, register_org


async def test_second_shop_on_free_plan_returns_402(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    first = await client.post(
        f"/organizations/{org_id}/shops", json={"name": "Shop One", "slug": "shop-one"}, headers=headers
    )
    assert first.status_code == 201

    second = await client.post(
        f"/organizations/{org_id}/shops", json={"name": "Shop Two", "slug": "shop-two"}, headers=headers
    )
    assert second.status_code == 402


async def test_eleventh_drawer_on_free_plan_returns_402(client: AsyncClient) -> None:
    """Free's max_drawers moved 5->10 in migration 0007 -- this replaces the
    old "sixth drawer" test at the new limit."""
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    shop_resp = await client.post(
        f"/organizations/{org_id}/shops", json={"name": "Shop", "slug": "shop"}, headers=headers
    )
    shop_id = shop_resp.json()["id"]

    toolbox_resp = await client.post(
        f"/organizations/{org_id}/shops/{shop_id}/toolboxes", json={"name": "Toolbox"}, headers=headers
    )
    toolbox_id = toolbox_resp.json()["id"]

    profile_resp = await client.post(
        f"/organizations/{org_id}/profiles/drawer-profiles",
        json={"name": "Drawer Preset", "inside_width_mm": "100", "inside_depth_mm": "100", "inside_height_mm": "50"},
        headers=headers,
    )
    drawer_profile_id = profile_resp.json()["id"]

    for i in range(10):
        resp = await client.post(
            f"/organizations/{org_id}/shops/{shop_id}/toolboxes/{toolbox_id}/drawers",
            json={"drawer_profile_id": drawer_profile_id, "position_label": f"slot-{i}"},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text

    eleventh = await client.post(
        f"/organizations/{org_id}/shops/{shop_id}/toolboxes/{toolbox_id}/drawers",
        json={"drawer_profile_id": drawer_profile_id, "position_label": "slot-11"},
        headers=headers,
    )
    assert eleventh.status_code == 402


async def test_101st_tool_on_free_plan_returns_402(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    for i in range(100):
        resp = await client.post(
            f"/organizations/{org_id}/tools", json={"name": f"Tool {i}"}, headers=headers
        )
        assert resp.status_code == 201, resp.text

    hundred_and_first = await client.post(
        f"/organizations/{org_id}/tools", json={"name": "Tool 101"}, headers=headers
    )
    assert hundred_and_first.status_code == 402


async def test_second_shop_on_pro_plan_returns_402(client: AsyncClient, db_session: AsyncSession) -> None:
    """Pro's max_shops tightened unlimited->1 in migration 0007 (see its
    docstring's "retroactive impact" note) -- hand-set plan_id after
    register_org, mirroring how a real license activation / Stripe webhook
    would leave the DB."""
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    await db_session.execute(
        update(Organization).where(Organization.id == uuid.UUID(org_id)).values(plan_id=PRO_PLAN_ID)
    )
    await db_session.commit()

    first = await client.post(
        f"/organizations/{org_id}/shops", json={"name": "Shop One", "slug": "shop-one"}, headers=headers
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        f"/organizations/{org_id}/shops", json={"name": "Shop Two", "slug": "shop-two"}, headers=headers
    )
    assert second.status_code == 402
