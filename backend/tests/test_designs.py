from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient

from app.workers import tasks as worker_tasks

from .conftest import auth_headers, register_org


async def _create_magnet_and_label_style(
    client: AsyncClient, org_id: str, headers: dict, **label_overrides
) -> tuple[str, str]:
    magnet_resp = await client.post(
        f"/organizations/{org_id}/profiles/magnets",
        json={"name": "6x2.5mm", "diameter_mm": "6", "thickness_mm": "2.5"},
        headers=headers,
    )
    assert magnet_resp.status_code == 201, magnet_resp.text
    magnet_id = magnet_resp.json()["id"]

    payload = {"name": "Default Style", "default_magnet_profile_id": magnet_id}
    payload.update(label_overrides)
    label_resp = await client.post(
        f"/organizations/{org_id}/profiles/label-styles",
        json=payload,
        headers=headers,
    )
    assert label_resp.status_code == 201, label_resp.text
    return magnet_id, label_resp.json()["id"]


async def test_create_design_returns_queued_with_real_hash(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    _, label_style_id = await _create_magnet_and_label_style(client, org_id, headers)

    resp = await client.post(
        f"/organizations/{org_id}/designs",
        json={"name": "Wrenches Label", "text": "Wrenches", "label_style_profile_id": label_style_id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["engine_version"] == "0.5.3"
    assert isinstance(body["content_hash"], str) and len(body["content_hash"]) == 64
    # Real hex digest, not a placeholder.
    int(body["content_hash"], 16)

    list_resp = await client.get(f"/organizations/{org_id}/designs", headers=headers)
    assert list_resp.status_code == 200
    assert any(d["id"] == body["id"] for d in list_resp.json())


async def test_create_design_with_bad_magnet_layout_returns_422(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    # An edge_offset_mm this large leaves no room for magnet supports next
    # to a short label's text bounds -- calculate_metrics()'s own validation
    # raises ValueError("Label is too narrow for the requested magnet
    # supports."), which the router must turn into a 422.
    _, label_style_id = await _create_magnet_and_label_style(
        client, org_id, headers, magnet_edge_offset_mm="100"
    )

    resp = await client.post(
        f"/organizations/{org_id}/designs",
        json={"name": "Bad Label", "text": "Hi", "label_style_profile_id": label_style_id},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert "too narrow" in resp.json()["detail"].lower()


async def test_generate_design_writes_stl_files(client: AsyncClient, tmp_path, monkeypatch) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    _, label_style_id = await _create_magnet_and_label_style(client, org_id, headers)

    create_resp = await client.post(
        f"/organizations/{org_id}/designs",
        json={"name": "Wrenches Label", "text": "Wrenches", "label_style_profile_id": label_style_id},
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    design_id = create_resp.json()["id"]

    # Redirect generated files to a temp directory for this test instead of
    # the real /data/generated (which won't exist outside the container).
    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))

    # Call the async worker implementation directly against the real test
    # Postgres (app.db.SessionFactory points at the same DATABASE_URL as the
    # rest of the test suite), bypassing Dramatiq/Redis entirely.
    await worker_tasks._generate_design(design_id)

    get_resp = await client.get(f"/organizations/{org_id}/designs/{design_id}", headers=headers)
    assert get_resp.status_code == 200, get_resp.text
    body = get_resp.json()
    assert body["status"] == "generated"
    assert body["error_message"] is None
    assert body["generated_at"] is not None

    outline_path = Path(body["outline_stl_path"])
    text_path = Path(body["text_stl_path"])
    assert outline_path.is_file() and outline_path.stat().st_size > 0
    assert text_path.is_file() and text_path.stat().st_size > 0


async def test_design_linked_to_tool_generates_qr_stl(client: AsyncClient, tmp_path, monkeypatch) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    _, label_style_id = await _create_magnet_and_label_style(client, org_id, headers)

    tool_resp = await client.post(
        f"/organizations/{org_id}/tools", json={"name": "Impact Driver", "quantity": 1}, headers=headers
    )
    assert tool_resp.status_code == 201, tool_resp.text
    tool_id = tool_resp.json()["id"]

    create_resp = await client.post(
        f"/organizations/{org_id}/designs",
        json={
            "name": "Impact Driver Label",
            "text": "IMPACT",
            "label_style_profile_id": label_style_id,
            "tool_id": tool_id,
        },
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    assert create_resp.json()["tool_id"] == tool_id
    design_id = create_resp.json()["id"]

    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))
    await worker_tasks._generate_design(design_id)

    get_resp = await client.get(f"/organizations/{org_id}/designs/{design_id}", headers=headers)
    body = get_resp.json()
    assert body["status"] == "generated"
    assert body["qr_stl_path"] is not None
    qr_path = Path(body["qr_stl_path"])
    assert qr_path.is_file() and qr_path.stat().st_size > 0

    file_resp = await client.get(f"/organizations/{org_id}/designs/{design_id}/files/qr", headers=headers)
    assert file_resp.status_code == 200
    assert file_resp.headers["content-type"] == "model/stl"
    assert len(file_resp.content) > 0


async def test_unlinked_design_has_no_qr_file(client: AsyncClient, tmp_path, monkeypatch) -> None:
    """Regression check at the API level (the geometry package has its own
    equivalent unit test): a design with no tool_id must never produce a
    qr_stl_path, and the qr file endpoint must 404, not error."""
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    _, label_style_id = await _create_magnet_and_label_style(client, org_id, headers)

    create_resp = await client.post(
        f"/organizations/{org_id}/designs",
        json={"name": "Plain Label", "text": "Wrenches", "label_style_profile_id": label_style_id},
        headers=headers,
    )
    design_id = create_resp.json()["id"]
    assert create_resp.json()["tool_id"] is None

    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))
    await worker_tasks._generate_design(design_id)

    get_resp = await client.get(f"/organizations/{org_id}/designs/{design_id}", headers=headers)
    assert get_resp.json()["qr_stl_path"] is None

    file_resp = await client.get(f"/organizations/{org_id}/designs/{design_id}/files/qr", headers=headers)
    assert file_resp.status_code == 404


async def test_design_create_rejects_unknown_tool_id(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]
    _, label_style_id = await _create_magnet_and_label_style(client, org_id, headers)

    import uuid

    resp = await client.post(
        f"/organizations/{org_id}/designs",
        json={
            "name": "Bad Tool Link",
            "text": "Wrenches",
            "label_style_profile_id": label_style_id,
            "tool_id": str(uuid.uuid4()),
        },
        headers=headers,
    )
    assert resp.status_code == 404
    assert "tool" in resp.json()["detail"].lower()
