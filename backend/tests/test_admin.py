"""HTTP-level tests for the superadmin-only /admin routes.

Superadmin status is a plain email allow-list (Settings.superadmin_emails),
not a DB column -- flip it per test via monkeypatch, same pattern
test_license_endpoint.py uses for deployment_mode/license_public_key
(get_settings() is lru_cached, so mutating the returned instance is correct).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.config import get_settings

from .conftest import auth_headers, register_org


@pytest.fixture
def superadmin(monkeypatch: pytest.MonkeyPatch):
    """Registers a fresh org/user and grants that user's email superadmin
    access for the duration of one test."""

    async def _make(client: AsyncClient) -> dict:
        data = await register_org(client)
        settings = get_settings()
        monkeypatch.setattr(settings, "superadmin_emails", data["user"]["email"])
        return data

    return _make


async def test_non_superadmin_gets_403(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])

    resp = await client.get("/admin/organizations", headers=headers)
    assert resp.status_code == 403


async def test_unauthenticated_gets_401(client: AsyncClient) -> None:
    resp = await client.get("/admin/organizations")
    assert resp.status_code == 401


async def test_superadmin_lists_organizations(client: AsyncClient, superadmin) -> None:
    admin_data = await superadmin(client)
    other = await register_org(client, org_name="Other Org")

    resp = await client.get("/admin/organizations", headers=auth_headers(admin_data["access_token"]))
    assert resp.status_code == 200, resp.text
    slugs = {row["slug"] for row in resp.json()}
    assert admin_data["organization_slug"] in slugs
    assert other["organization_slug"] in slugs


async def test_search_matches_org_name_slug_or_owner_email(client: AsyncClient, superadmin) -> None:
    admin_data = await superadmin(client)
    target = await register_org(client, org_name="Findable Workshop", email="findme@example.com")
    await register_org(client, org_name="Unrelated Org")
    headers = auth_headers(admin_data["access_token"])

    by_name = await client.get("/admin/organizations", params={"search": "Findable"}, headers=headers)
    assert {r["slug"] for r in by_name.json()} == {target["organization_slug"]}

    by_email = await client.get("/admin/organizations", params={"search": "findme@example.com"}, headers=headers)
    assert {r["slug"] for r in by_email.json()} == {target["organization_slug"]}

    for row in by_email.json():
        if row["slug"] == target["organization_slug"]:
            assert row["owner_email"] == "findme@example.com"
            assert row["plan_key"] == "free"


async def test_set_plan_updates_org_and_bypasses_stripe(client: AsyncClient, superadmin) -> None:
    admin_data = await superadmin(client)
    target = await register_org(client)
    admin_headers = auth_headers(admin_data["access_token"])
    target_headers = auth_headers(target["access_token"])

    resp = await client.post(
        f"/admin/organizations/{target['organization_id']}/plan",
        json={"plan_key": "enterprise"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan_key"] == "enterprise"

    # Persisted, and visible through the org's own normal (non-admin) view --
    # no stripe_customer_id was ever set, confirming this doesn't ride on the
    # Stripe/license flow at all.
    check = await client.get(f"/organizations/{target['organization_id']}", headers=target_headers)
    assert check.json()["plan"]["key"] == "enterprise"


async def test_set_plan_unknown_key_returns_400(client: AsyncClient, superadmin) -> None:
    admin_data = await superadmin(client)
    target = await register_org(client)

    resp = await client.post(
        f"/admin/organizations/{target['organization_id']}/plan",
        json={"plan_key": "nonexistent"},
        headers=auth_headers(admin_data["access_token"]),
    )
    assert resp.status_code == 400


async def test_set_plan_unknown_org_returns_404(client: AsyncClient, superadmin) -> None:
    admin_data = await superadmin(client)

    resp = await client.post(
        f"/admin/organizations/{uuid.uuid4()}/plan",
        json={"plan_key": "pro"},
        headers=auth_headers(admin_data["access_token"]),
    )
    assert resp.status_code == 404


async def test_non_superadmin_cannot_set_plan(client: AsyncClient) -> None:
    data = await register_org(client)

    resp = await client.post(
        f"/organizations/{data['organization_id']}/plan".replace("/organizations/", "/admin/organizations/"),
        json={"plan_key": "pro"},
        headers=auth_headers(data["access_token"]),
    )
    assert resp.status_code == 403


async def test_me_reports_is_superadmin(client: AsyncClient, superadmin) -> None:
    admin_data = await superadmin(client)
    non_admin = await register_org(client)

    admin_me = await client.get("/auth/me", headers=auth_headers(admin_data["access_token"]))
    assert admin_me.json()["is_superadmin"] is True

    other_me = await client.get("/auth/me", headers=auth_headers(non_admin["access_token"]))
    assert other_me.json()["is_superadmin"] is False
