"""Verifies the fix for the old codebase's vulnerability where
`organization_id` was trusted straight from an unauthenticated query param
(see Workshop-Designer/backend/app/routers/profiles.py). In the rebuild,
`get_current_membership` requires a real Membership row tied to the caller's
JWT, so org A's token can never read or write org B's resources by simply
passing org B's UUID in the path.
"""

from httpx import AsyncClient

from .conftest import auth_headers, register_org


async def test_org_a_cannot_list_org_b_profiles(client: AsyncClient) -> None:
    org_a = await register_org(client)
    org_b = await register_org(client)

    # org B creates a printer profile.
    create_resp = await client.post(
        f"/organizations/{org_b['organization_id']}/profiles/printers",
        json={"name": "Org B Printer", "build_width_mm": "200", "build_depth_mm": "200", "build_height_mm": "200"},
        headers=auth_headers(org_b["access_token"]),
    )
    assert create_resp.status_code == 201
    org_b_profile_id = create_resp.json()["id"]

    # org A's token tries to list org B's profiles by passing org B's org id in the path.
    list_resp = await client.get(
        f"/organizations/{org_b['organization_id']}/profiles/printers",
        headers=auth_headers(org_a["access_token"]),
    )
    assert list_resp.status_code == 403

    # org A's token tries to fetch the specific profile directly.
    get_resp = await client.get(
        f"/organizations/{org_b['organization_id']}/profiles/printers/{org_b_profile_id}",
        headers=auth_headers(org_a["access_token"]),
    )
    assert get_resp.status_code == 403

    # org A's token tries to delete org B's profile.
    delete_resp = await client.delete(
        f"/organizations/{org_b['organization_id']}/profiles/printers/{org_b_profile_id}",
        headers=auth_headers(org_a["access_token"]),
    )
    assert delete_resp.status_code == 403

    # Sanity: org B can still see its own profile.
    own_list = await client.get(
        f"/organizations/{org_b['organization_id']}/profiles/printers",
        headers=auth_headers(org_b["access_token"]),
    )
    assert own_list.status_code == 200
    assert len(own_list.json()) == 1


async def test_org_a_cannot_access_org_b_shop(client: AsyncClient) -> None:
    org_a = await register_org(client)
    org_b = await register_org(client)

    shop_resp = await client.post(
        f"/organizations/{org_b['organization_id']}/shops",
        json={"name": "Org B Shop", "slug": "org-b-shop"},
        headers=auth_headers(org_b["access_token"]),
    )
    assert shop_resp.status_code == 201
    shop_id = shop_resp.json()["id"]

    # Even a well-formed request against org B's real shop id, using org A's
    # token but org B's org id in the path, must fail at the membership check.
    resp = await client.get(
        f"/organizations/{org_b['organization_id']}/shops/{shop_id}",
        headers=auth_headers(org_a["access_token"]),
    )
    assert resp.status_code == 403


async def test_unauthenticated_request_rejected(client: AsyncClient) -> None:
    org = await register_org(client)
    resp = await client.get(f"/organizations/{org['organization_id']}/shops")
    assert resp.status_code == 401
