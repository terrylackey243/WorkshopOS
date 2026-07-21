from httpx import AsyncClient

from .conftest import auth_headers, register_org


async def test_register_creates_org_and_owner_membership(client: AsyncClient) -> None:
    data = await register_org(client)
    assert data["organization_slug"]
    assert data["access_token"]
    assert data["user"]["is_active"] is True


async def test_register_duplicate_email_rejected(client: AsyncClient) -> None:
    email = "dupe@example.com"
    await register_org(client, email=email)
    response = await client.post(
        "/auth/register",
        json={
            "organization_name": "Another Org",
            "email": email,
            "password": "another-password-123",
        },
    )
    assert response.status_code == 409


async def test_login_round_trip(client: AsyncClient) -> None:
    email = "login-test@example.com"
    password = "correct-horse-battery-staple"
    await register_org(client, email=email)
    # override password isn't possible via register_org helper (fixed password), reuse it
    response = await client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_login_wrong_password_rejected(client: AsyncClient) -> None:
    email = "badpass@example.com"
    await register_org(client, email=email)
    response = await client.post("/auth/login", json={"email": email, "password": "wrong-password"})
    assert response.status_code == 401


async def test_me_returns_org_and_role(client: AsyncClient) -> None:
    data = await register_org(client)
    token = data["access_token"]
    response = await client.get("/auth/me", headers=auth_headers(token))
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"]
    assert len(body["organizations"]) == 1
    assert body["organizations"][0]["role"] == "owner"
    assert body["organizations"][0]["plan_key"] == "free"


async def test_me_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/auth/me")
    assert response.status_code == 401
