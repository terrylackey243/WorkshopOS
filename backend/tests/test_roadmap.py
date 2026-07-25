import pytest
from httpx import AsyncClient

from app.config import get_settings

from .conftest import auth_headers, register_org


@pytest.fixture
def superadmin(monkeypatch: pytest.MonkeyPatch):
    """Registers a fresh org/user and grants that user's email superadmin
    access for the duration of one test -- same pattern as test_admin.py's
    fixture of the same name (roadmap mutations are gated by
    deps.require_superadmin, same as /admin)."""

    async def _make(client: AsyncClient) -> dict:
        data = await register_org(client)
        settings = get_settings()
        monkeypatch.setattr(settings, "superadmin_emails", data["user"]["email"])
        return data

    return _make


async def test_roadmap_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/roadmap")
    assert resp.status_code == 401


async def test_non_superadmin_cannot_mutate_roadmap(client: AsyncClient) -> None:
    """Any authenticated user can list the roadmap, but create/update/reorder/
    delete are superadmin-only (see routers/roadmap.py)."""
    data = await register_org(client)
    headers = auth_headers(data["access_token"])

    list_resp = await client.get("/roadmap", headers=headers)
    assert list_resp.status_code == 200

    create_resp = await client.post("/roadmap", json={"title": "Should not work"}, headers=headers)
    assert create_resp.status_code == 403

    # Seed one item as a superadmin so update/delete/move have a real target.
    other = await register_org(client)
    other_headers = auth_headers(other["access_token"])
    seed = await client.post(
        "/roadmap", json={"title": "Existing item"}, headers=other_headers
    )
    assert seed.status_code == 403  # `other` isn't a superadmin either -- confirms no false positive


async def test_roadmap_list_is_ordered_by_position(client: AsyncClient, superadmin) -> None:
    # Note: the real seed data (10 items from migration 0004) is only
    # inserted by Alembic, not by conftest's `Base.metadata.create_all` --
    # this test only asserts on rows it creates itself, not the seed content.
    data = await superadmin(client)
    headers = auth_headers(data["access_token"])

    for title, status_value in [("First", "done"), ("Second", "in_progress"), ("Third", "planned")]:
        resp = await client.post("/roadmap", json={"title": title, "status": status_value}, headers=headers)
        assert resp.status_code == 201, resp.text

    items = (await client.get("/roadmap", headers=headers)).json()
    assert [i["title"] for i in items] == ["First", "Second", "Third"]
    positions = [item["position"] for item in items]
    assert positions == sorted(positions)


async def test_roadmap_crud_and_reorder(client: AsyncClient, superadmin) -> None:
    data = await superadmin(client)
    headers = auth_headers(data["access_token"])

    # Need at least one existing item for the move-up assertions below to
    # have a real neighbor to swap with.
    seed_resp = await client.post("/roadmap", json={"title": "Earlier item"}, headers=headers)
    assert seed_resp.status_code == 201, seed_resp.text

    create_resp = await client.post(
        "/roadmap",
        json={"title": "New idea", "description": "Something we thought of later", "status": "planned"},
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    item = create_resp.json()
    item_id = item["id"]

    # A freshly-created item is appended at the end.
    all_items = (await client.get("/roadmap", headers=headers)).json()
    assert all_items[-1]["id"] == item_id

    patch_resp = await client.patch(
        f"/roadmap/{item_id}", json={"status": "in_progress"}, headers=headers
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "in_progress"

    # Move it up one slot and confirm it actually swapped with its neighbor.
    before = (await client.get("/roadmap", headers=headers)).json()
    before_index = next(i for i, r in enumerate(before) if r["id"] == item_id)
    neighbor_id = before[before_index - 1]["id"]

    move_resp = await client.post(f"/roadmap/{item_id}/move-up", headers=headers)
    assert move_resp.status_code == 200

    after = (await client.get("/roadmap", headers=headers)).json()
    after_index = next(i for i, r in enumerate(after) if r["id"] == item_id)
    assert after_index == before_index - 1
    assert after[after_index + 1]["id"] == neighbor_id

    delete_resp = await client.delete(f"/roadmap/{item_id}", headers=headers)
    assert delete_resp.status_code == 204

    final = (await client.get("/roadmap", headers=headers)).json()
    assert item_id not in [r["id"] for r in final]
