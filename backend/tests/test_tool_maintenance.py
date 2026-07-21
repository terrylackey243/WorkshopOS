from __future__ import annotations

from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .conftest import auth_headers, register_org


async def _create_tool(
    client: AsyncClient,
    headers: dict,
    org_id: str,
    name: str = "Impact Driver",
    maintenance_interval_days: int | None = None,
) -> str:
    payload = {"name": name, "quantity": 1}
    if maintenance_interval_days is not None:
        payload["maintenance_interval_days"] = maintenance_interval_days
    resp = await client.post(f"/organizations/{org_id}/tools", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_tool_without_interval_never_appears_in_maintenance_due(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    await _create_tool(client, headers, org_id, "No Interval Tool")

    resp = await client.get(f"/organizations/{org_id}/dashboard", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["maintenance_due"] == []


async def test_tool_with_interval_and_no_last_maintained_appears_immediately(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id, "Never Maintained Tool", maintenance_interval_days=30)

    resp = await client.get(f"/organizations/{org_id}/dashboard", headers=headers)
    assert resp.status_code == 200, resp.text
    due_ids = {t["id"] for t in resp.json()["maintenance_due"]}
    assert due_ids == {tool_id}


async def test_recently_maintained_tool_is_not_due(client: AsyncClient, db_session: AsyncSession) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id, "Recently Maintained Tool", maintenance_interval_days=30)

    recent = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.execute(
        text("UPDATE tools SET last_maintained_at = :ts WHERE id = :id"),
        {"ts": recent, "id": tool_id},
    )
    await db_session.commit()

    resp = await client.get(f"/organizations/{org_id}/dashboard", headers=headers)
    assert resp.status_code == 200, resp.text
    due_ids = {t["id"] for t in resp.json()["maintenance_due"]}
    assert tool_id not in due_ids


async def test_tool_maintained_long_ago_is_due(client: AsyncClient, db_session: AsyncSession) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id, "Overdue Maintenance Tool", maintenance_interval_days=30)

    long_ago = datetime.now(timezone.utc) - timedelta(days=90)
    await db_session.execute(
        text("UPDATE tools SET last_maintained_at = :ts WHERE id = :id"),
        {"ts": long_ago, "id": tool_id},
    )
    await db_session.commit()

    resp = await client.get(f"/organizations/{org_id}/dashboard", headers=headers)
    assert resp.status_code == 200, resp.text
    due_ids = {t["id"] for t in resp.json()["maintenance_due"]}
    assert due_ids == {tool_id}


async def test_mark_done_clears_dashboard_entry_and_sets_timestamp(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id, "Due Tool", maintenance_interval_days=30)

    resp = await client.post(
        f"/organizations/{org_id}/tools/{tool_id}/maintenance/mark-done", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["last_maintained_at"] is not None

    resp = await client.get(f"/organizations/{org_id}/dashboard", headers=headers)
    due_ids = {t["id"] for t in resp.json()["maintenance_due"]}
    assert tool_id not in due_ids


async def test_maintenance_interval_updatable_via_patch(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id, "Patchable Tool")

    resp = await client.patch(
        f"/organizations/{org_id}/tools/{tool_id}",
        json={"maintenance_interval_days": 14},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["maintenance_interval_days"] == 14

    dash = await client.get(f"/organizations/{org_id}/dashboard", headers=headers)
    due_ids = {t["id"] for t in dash.json()["maintenance_due"]}
    assert tool_id in due_ids


async def test_dashboard_maintenance_due_does_not_leak_across_organizations(client: AsyncClient) -> None:
    org_a = await register_org(client)
    org_a_id = org_a["organization_id"]
    headers_a = auth_headers(org_a["access_token"])
    await _create_tool(client, headers_a, org_a_id, "Org A Tool", maintenance_interval_days=1)

    org_b = await register_org(client)
    org_b_id = org_b["organization_id"]
    headers_b = auth_headers(org_b["access_token"])

    resp = await client.get(f"/organizations/{org_b_id}/dashboard", headers=headers_b)
    assert resp.status_code == 200
    assert resp.json()["maintenance_due"] == []
