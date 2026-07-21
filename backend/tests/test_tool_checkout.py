from __future__ import annotations

from datetime import datetime, timedelta, timezone

from httpx import AsyncClient

from .conftest import auth_headers, register_org


async def _create_tool(client: AsyncClient, headers: dict, org_id: str, name: str = "Impact Driver") -> str:
    resp = await client.post(f"/organizations/{org_id}/tools", json={"name": name, "quantity": 1}, headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["checked_out_to"] is None
    return resp.json()["id"]


async def test_checkout_sets_all_three_fields(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id)

    resp = await client.post(
        f"/organizations/{org_id}/tools/{tool_id}/checkout",
        json={"checked_out_to": "Jane"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["checked_out_to"] == "Jane"
    assert body["checked_out_at"] is not None
    assert body["checkout_due_at"] is None


async def test_checkout_with_due_date(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id)

    due = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    resp = await client.post(
        f"/organizations/{org_id}/tools/{tool_id}/checkout",
        json={"checked_out_to": "Jane", "checkout_due_at": due},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["checkout_due_at"] is not None


async def test_double_checkout_returns_422(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id)

    await client.post(
        f"/organizations/{org_id}/tools/{tool_id}/checkout", json={"checked_out_to": "Jane"}, headers=headers
    )
    resp = await client.post(
        f"/organizations/{org_id}/tools/{tool_id}/checkout", json={"checked_out_to": "Bob"}, headers=headers
    )
    assert resp.status_code == 422
    assert "already checked out" in resp.json()["detail"].lower()


async def test_return_clears_all_three_fields(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id)

    await client.post(
        f"/organizations/{org_id}/tools/{tool_id}/checkout", json={"checked_out_to": "Jane"}, headers=headers
    )
    resp = await client.post(f"/organizations/{org_id}/tools/{tool_id}/return", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["checked_out_to"] is None
    assert body["checked_out_at"] is None
    assert body["checkout_due_at"] is None


async def test_returning_a_not_checked_out_tool_returns_422(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id)

    resp = await client.post(f"/organizations/{org_id}/tools/{tool_id}/return", headers=headers)
    assert resp.status_code == 422
    assert "not currently checked out" in resp.json()["detail"].lower()


async def test_dashboard_buckets_overdue_vs_active_correctly(client: AsyncClient) -> None:
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])

    # Not checked out at all -- should appear in neither bucket.
    await _create_tool(client, headers, org_id, "Idle Tool")

    # Checked out, no due date -- active.
    no_due_id = await _create_tool(client, headers, org_id, "No Due Date Tool")
    await client.post(
        f"/organizations/{org_id}/tools/{no_due_id}/checkout", json={"checked_out_to": "Jane"}, headers=headers
    )

    # Checked out, due in the future -- active.
    future_id = await _create_tool(client, headers, org_id, "Future Due Tool")
    future_due = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    await client.post(
        f"/organizations/{org_id}/tools/{future_id}/checkout",
        json={"checked_out_to": "Bob", "checkout_due_at": future_due},
        headers=headers,
    )

    # Checked out, due in the past -- overdue.
    past_id = await _create_tool(client, headers, org_id, "Overdue Tool")
    past_due = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    await client.post(
        f"/organizations/{org_id}/tools/{past_id}/checkout",
        json={"checked_out_to": "Sam", "checkout_due_at": past_due},
        headers=headers,
    )

    resp = await client.get(f"/organizations/{org_id}/dashboard", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    overdue_ids = {t["id"] for t in body["overdue_checkouts"]}
    active_ids = {t["id"] for t in body["active_checkouts"]}

    assert overdue_ids == {past_id}
    assert active_ids == {no_due_id, future_id}
    # The idle (never-checked-out) tool appears in neither bucket.
    all_ids = overdue_ids | active_ids
    assert len(all_ids) == 3


async def test_dashboard_tools_carry_location_and_has_photo(client: AsyncClient) -> None:
    """Dashboard results reuse ToolRead -- confirm _attach_derived_fields was
    actually called (location/has_photo present, not raising due to a
    missing attribute), not just that the checkout fields round-trip."""
    org = await register_org(client)
    org_id = org["organization_id"]
    headers = auth_headers(org["access_token"])
    tool_id = await _create_tool(client, headers, org_id)
    await client.post(
        f"/organizations/{org_id}/tools/{tool_id}/checkout", json={"checked_out_to": "Jane"}, headers=headers
    )

    resp = await client.get(f"/organizations/{org_id}/dashboard", headers=headers)
    body = resp.json()
    assert len(body["active_checkouts"]) == 1
    tool = body["active_checkouts"][0]
    assert "location" in tool and tool["location"] is None
    assert tool["has_photo"] is False


async def test_dashboard_does_not_leak_across_organizations(client: AsyncClient) -> None:
    org_a = await register_org(client)
    org_a_id = org_a["organization_id"]
    headers_a = auth_headers(org_a["access_token"])
    tool_id = await _create_tool(client, headers_a, org_a_id)
    await client.post(
        f"/organizations/{org_a_id}/tools/{tool_id}/checkout", json={"checked_out_to": "Jane"}, headers=headers_a
    )

    org_b = await register_org(client)
    org_b_id = org_b["organization_id"]
    headers_b = auth_headers(org_b["access_token"])

    resp = await client.get(f"/organizations/{org_b_id}/dashboard", headers=headers_b)
    assert resp.status_code == 200
    body = resp.json()
    assert body["overdue_checkouts"] == []
    assert body["active_checkouts"] == []
