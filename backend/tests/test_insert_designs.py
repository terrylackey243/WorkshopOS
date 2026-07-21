from __future__ import annotations

import os

from pathlib import Path

import pytest
import trimesh
from httpx import AsyncClient

from app.workers import tasks as worker_tasks

from .conftest import auth_headers, register_org


async def _create_magnet_profile(client: AsyncClient, org_id: str, headers: dict) -> str:
    resp = await client.post(
        f"/organizations/{org_id}/profiles/magnets",
        json={"name": "6x2mm", "diameter_mm": "6", "thickness_mm": "2"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_create_bin_returns_queued_with_real_hash(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    resp = await client.post(
        f"/organizations/{org_id}/insert-designs/generate-bin",
        json={"name": "Small Bin", "grid_width_units": 2, "grid_depth_units": 3, "height_units": 3},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["engine_version"] == "0.1.0"
    assert isinstance(body["content_hash"], str) and len(body["content_hash"]) == 64
    int(body["content_hash"], 16)  # real hex digest, not a placeholder
    assert body["bounds_json"] == {"width_mm": 83.5, "depth_mm": 125.5, "height_mm": 30.15}

    list_resp = await client.get(f"/organizations/{org_id}/insert-designs", headers=headers)
    assert list_resp.status_code == 200
    assert any(d["id"] == body["id"] for d in list_resp.json())


async def test_create_bin_with_magnet_profile(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    magnet_id = await _create_magnet_profile(client, org_id, headers)

    resp = await client.post(
        f"/organizations/{org_id}/insert-designs/generate-bin",
        json={
            "name": "Magnet Bin",
            "grid_width_units": 1,
            "grid_depth_units": 1,
            "height_units": 2,
            "magnet_profile_id": magnet_id,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["parameters_json"]["magnet_diameter_mm"] == 6.0


async def test_create_bin_with_uneven_compartments_returns_422(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    resp = await client.post(
        f"/organizations/{org_id}/insert-designs/generate-bin",
        json={
            "name": "Bad Bin",
            "grid_width_units": 2,
            "grid_depth_units": 1,
            "height_units": 1,
            "compartments_x": 3,
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert "compartments_x" in resp.json()["detail"]


async def test_create_bin_with_zero_grid_units_returns_422(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    resp = await client.post(
        f"/organizations/{org_id}/insert-designs/generate-bin",
        json={"name": "Bad Bin", "grid_width_units": 0, "grid_depth_units": 1, "height_units": 1},
        headers=headers,
    )
    # Pydantic's ge=1 constraint rejects this before it ever reaches
    # BinParameters.validate() -- still a 422, just from a different layer.
    assert resp.status_code == 422, resp.text


async def test_create_bin_with_magnet_profile_from_other_org_returns_404(client: AsyncClient) -> None:
    data_a = await register_org(client)
    headers_a = auth_headers(data_a["access_token"])
    org_a = data_a["organization_id"]

    data_b = await register_org(client)
    headers_b = auth_headers(data_b["access_token"])
    org_b = data_b["organization_id"]

    magnet_id = await _create_magnet_profile(client, org_b, headers_b)

    resp = await client.post(
        f"/organizations/{org_a}/insert-designs/generate-bin",
        json={
            "name": "Cross-org Bin",
            "grid_width_units": 1,
            "grid_depth_units": 1,
            "height_units": 1,
            "magnet_profile_id": magnet_id,
        },
        headers=headers_a,
    )
    assert resp.status_code == 404, resp.text


async def test_generate_bin_design_writes_stl_file(client: AsyncClient, tmp_path, monkeypatch) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    create_resp = await client.post(
        f"/organizations/{org_id}/insert-designs/generate-bin",
        json={
            "name": "Real Bin",
            "grid_width_units": 2,
            "grid_depth_units": 3,
            "height_units": 3,
            "include_stacking_lip": True,
        },
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    insert_design_id = create_resp.json()["id"]

    # Redirect generated files to a temp directory for this test instead of
    # the real /data/generated (which won't exist outside the container).
    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))

    # Call the async worker implementation directly against the real test
    # Postgres, bypassing Dramatiq/Redis entirely -- same pattern as
    # test_designs.py::test_generate_design_writes_stl_files.
    await worker_tasks._generate_bin_design(insert_design_id)

    get_resp = await client.get(f"/organizations/{org_id}/insert-designs/{insert_design_id}", headers=headers)
    assert get_resp.status_code == 200, get_resp.text
    body = get_resp.json()
    assert body["status"] == "generated"
    assert body["error_message"] is None
    assert body["generated_at"] is not None

    stl_path = Path(body["stl_path"])
    assert stl_path.is_file() and stl_path.stat().st_size > 0

    mesh = trimesh.load(stl_path)
    assert mesh.is_watertight
    bounds = mesh.bounds
    width = bounds[1][0] - bounds[0][0]
    depth = bounds[1][1] - bounds[0][1]
    height = bounds[1][2] - bounds[0][2]
    assert width == pytest.approx(83.5, abs=0.2)
    assert depth == pytest.approx(125.5, abs=0.2)
    assert height == pytest.approx(4.75 + 3 * 7 + 4.4, abs=0.2)

    # File-download endpoint serves real binary STL content.
    file_resp = await client.get(f"/organizations/{org_id}/insert-designs/{insert_design_id}/file", headers=headers)
    assert file_resp.status_code == 200
    assert len(file_resp.content) > 0


def _stl_bytes(width: float = 30.0, depth: float = 20.0, height: float = 10.0) -> bytes:
    """A tiny hand-built box STL (known dimensions) for upload-path tests --
    avoids depending on the bin engine's CSG pipeline just to exercise file
    upload/parsing."""
    mesh = trimesh.creation.box(extents=(width, depth, height))
    data = mesh.export(file_type="stl")
    return data if isinstance(data, bytes) else data.encode()


async def test_upload_insert_design_returns_queued(client: AsyncClient, tmp_path, monkeypatch) -> None:
    from app.routers import insert_designs as insert_designs_router

    monkeypatch.setattr(insert_designs_router.settings, "generated_files_dir", str(tmp_path))

    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    resp = await client.post(
        f"/organizations/{org_id}/insert-designs/upload",
        data={"name": "Community Tool Tray", "source_reference": "tooltrace.ai"},
        files={"file": ("cube.stl", _stl_bytes(), "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["source"] == "upload"
    assert body["source_reference"] == "tooltrace.ai"
    assert body["bounds_json"] is None
    assert body["stl_path"] is not None
    assert Path(body["stl_path"]).is_file()

    list_resp = await client.get(f"/organizations/{org_id}/insert-designs", headers=headers)
    assert list_resp.status_code == 200
    assert any(d["id"] == body["id"] for d in list_resp.json())


async def test_process_uploaded_insert_computes_bounds(client: AsyncClient, tmp_path, monkeypatch) -> None:
    from app.routers import insert_designs as insert_designs_router

    monkeypatch.setattr(insert_designs_router.settings, "generated_files_dir", str(tmp_path))

    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    content = _stl_bytes(30.0, 20.0, 10.0)
    resp = await client.post(
        f"/organizations/{org_id}/insert-designs/upload",
        data={"name": "Known Cube"},
        files={"file": ("cube.stl", content, "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    insert_design_id = resp.json()["id"]

    # Call the async worker implementation directly against the real test
    # Postgres, bypassing Dramatiq/Redis entirely -- same pattern as
    # test_generate_bin_design_writes_stl_file above.
    await worker_tasks._process_uploaded_insert(insert_design_id)

    get_resp = await client.get(f"/organizations/{org_id}/insert-designs/{insert_design_id}", headers=headers)
    assert get_resp.status_code == 200, get_resp.text
    body = get_resp.json()
    assert body["status"] == "generated"
    assert body["error_message"] is None
    assert body["generated_at"] is not None
    bounds = body["bounds_json"]
    assert bounds["width_mm"] == pytest.approx(30.0, abs=0.05)
    assert bounds["depth_mm"] == pytest.approx(20.0, abs=0.05)
    assert bounds["height_mm"] == pytest.approx(10.0, abs=0.05)

    # File-download endpoint serves back byte-identical content to what was
    # uploaded.
    file_resp = await client.get(f"/organizations/{org_id}/insert-designs/{insert_design_id}/file", headers=headers)
    assert file_resp.status_code == 200
    assert file_resp.content == content


async def test_process_uploaded_insert_marks_corrupt_file_failed(client: AsyncClient, tmp_path, monkeypatch) -> None:
    from app.routers import insert_designs as insert_designs_router

    monkeypatch.setattr(insert_designs_router.settings, "generated_files_dir", str(tmp_path))

    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    resp = await client.post(
        f"/organizations/{org_id}/insert-designs/upload",
        data={"name": "Garbage File"},
        files={
            "file": (
                "garbage.stl",
                b"this is definitely not a valid STL file, just random bytes" * 10,
                "application/octet-stream",
            )
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    insert_design_id = body["id"]

    # Must not raise -- the worker boundary swallows the parse failure and
    # records it on the row instead of crashing the worker process.
    await worker_tasks._process_uploaded_insert(insert_design_id)

    get_resp = await client.get(f"/organizations/{org_id}/insert-designs/{insert_design_id}", headers=headers)
    assert get_resp.status_code == 200, get_resp.text
    failed_body = get_resp.json()
    assert failed_body["status"] == "failed"
    assert failed_body["error_message"]
    assert "Traceback" not in failed_body["error_message"]


async def test_upload_insert_design_rejects_non_stl_filename(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    resp = await client.post(
        f"/organizations/{org_id}/insert-designs/upload",
        data={"name": "Wrong Extension"},
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text

    list_resp = await client.get(f"/organizations/{org_id}/insert-designs", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json() == []


async def test_upload_insert_design_rejects_oversized_file(client: AsyncClient, tmp_path, monkeypatch) -> None:
    from app.routers import insert_designs as insert_designs_router

    monkeypatch.setattr(insert_designs_router.settings, "generated_files_dir", str(tmp_path))
    # Lower the cap for a fast, reliable test instead of constructing a real
    # 25MB+ file.
    monkeypatch.setattr(insert_designs_router, "MAX_UPLOAD_BYTES", 1024)

    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    resp = await client.post(
        f"/organizations/{org_id}/insert-designs/upload",
        data={"name": "Too Big"},
        files={"file": ("big.stl", os.urandom(2048), "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code == 413, resp.text

    # The partial file and DB row must both be cleaned up, not left dangling.
    list_resp = await client.get(f"/organizations/{org_id}/insert-designs", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json() == []
