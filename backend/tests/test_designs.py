from __future__ import annotations

import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from httpx import AsyncClient
from workshop_geometry import inspect_3mf

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


async def test_list_designs_sorted_by_name(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    _, label_style_id = await _create_magnet_and_label_style(client, org_id, headers)

    for name in ["Wrenches", "Allen Keys", "Pliers"]:
        resp = await client.post(
            f"/organizations/{org_id}/designs",
            json={"name": name, "text": name, "label_style_profile_id": label_style_id},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text

    list_resp = await client.get(f"/organizations/{org_id}/designs", headers=headers)
    assert [d["name"] for d in list_resp.json()] == ["Allen Keys", "Pliers", "Wrenches"]


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


async def test_design_3mf_combines_outline_and_text(client: AsyncClient, tmp_path, monkeypatch) -> None:
    """The combined-3MF download: same outline+text pair as the separate
    STL downloads, but as one file -- built by the worker directly from
    the in-memory CSG result (see workshop_geometry.label_engine.
    export_label), stored as Design.threemf_path, and just served like any
    other generated file.

    No per-object color: a real third-party slicer with an unusually
    strict/limited 3MF reader was confirmed to reject files containing a
    `<basematerials>` resource outright (rejecting the whole file as having
    "no geometry data", not just ignoring the color) -- see
    label_engine.py's EXPORT_3MF_INCLUDE_COLORS. Broad slicer compatibility
    won out over auto-assigned color."""
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    _, label_style_id = await _create_magnet_and_label_style(client, org_id, headers)

    create_resp = await client.post(
        f"/organizations/{org_id}/designs",
        json={"name": "Wrenches Label", "text": "Wrenches", "label_style_profile_id": label_style_id},
        headers=headers,
    )
    design_id = create_resp.json()["id"]

    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))
    await worker_tasks._generate_design(design_id)

    file_resp = await client.get(f"/organizations/{org_id}/designs/{design_id}/files/3mf", headers=headers)
    assert file_resp.status_code == 200, file_resp.text
    assert file_resp.headers["content-type"] == "model/3mf"
    assert file_resp.headers["cache-control"] == "no-store"

    threemf_path = tmp_path / "downloaded.3mf"
    threemf_path.write_bytes(file_resp.content)

    report = inspect_3mf(threemf_path)
    assert report.object_count == 2
    assert report.build_item_count == 2
    assert {o.name for o in report.objects} == {"outline", "text"}

    with zipfile.ZipFile(io.BytesIO(file_resp.content)) as z:
        root = ET.fromstring(z.read("3D/3dmodel.model"))
    ns = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
    assert root.findall(f"{ns}resources/{ns}basematerials") == []
    for obj in root.findall(f"{ns}resources/{ns}object"):
        assert "pid" not in obj.attrib and "pindex" not in obj.attrib


async def test_design_3mf_404s_before_generation(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    _, label_style_id = await _create_magnet_and_label_style(client, org_id, headers)
    create_resp = await client.post(
        f"/organizations/{org_id}/designs",
        json={"name": "Wrenches Label", "text": "Wrenches", "label_style_profile_id": label_style_id},
        headers=headers,
    )
    design_id = create_resp.json()["id"]

    file_resp = await client.get(f"/organizations/{org_id}/designs/{design_id}/files/3mf", headers=headers)
    assert file_resp.status_code == 404


async def test_design_stl_bundle_zips_both_files(client: AsyncClient, tmp_path, monkeypatch) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    _, label_style_id = await _create_magnet_and_label_style(client, org_id, headers)
    create_resp = await client.post(
        f"/organizations/{org_id}/designs",
        json={"name": "Wrenches Label", "text": "Wrenches", "label_style_profile_id": label_style_id},
        headers=headers,
    )
    design_id = create_resp.json()["id"]

    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))
    await worker_tasks._generate_design(design_id)

    file_resp = await client.get(f"/organizations/{org_id}/designs/{design_id}/files/stl-bundle", headers=headers)
    assert file_resp.status_code == 200, file_resp.text
    assert file_resp.headers["content-type"] == "application/zip"
    assert file_resp.headers["cache-control"] == "no-store"

    with zipfile.ZipFile(io.BytesIO(file_resp.content)) as z:
        names = set(z.namelist())
        assert names == {"outline.stl", "text.stl"}
        assert len(z.read("outline.stl")) > 0
        assert len(z.read("text.stl")) > 0


async def test_design_stl_bundle_404s_before_generation(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    _, label_style_id = await _create_magnet_and_label_style(client, org_id, headers)
    create_resp = await client.post(
        f"/organizations/{org_id}/designs",
        json={"name": "Wrenches Label", "text": "Wrenches", "label_style_profile_id": label_style_id},
        headers=headers,
    )
    design_id = create_resp.json()["id"]

    file_resp = await client.get(f"/organizations/{org_id}/designs/{design_id}/files/stl-bundle", headers=headers)
    assert file_resp.status_code == 404


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


async def test_regenerate_picks_up_label_style_profile_edits(client: AsyncClient, tmp_path, monkeypatch) -> None:
    """The whole point of /regenerate: parameters_json is a frozen snapshot
    from create_design, so editing the label style profile afterwards must
    NOT change an already-generated design until regenerate is explicitly
    called -- and once it is, the new value must actually be in effect."""
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
    original_hash = create_resp.json()["content_hash"]
    assert create_resp.json()["parameters_json"]["text_height_mm"] == 15.843

    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))
    await worker_tasks._generate_design(design_id)

    # Edit the profile the design was built from -- this alone must not
    # touch the design at all.
    patch_resp = await client.patch(
        f"/organizations/{org_id}/profiles/label-styles/{label_style_id}",
        json={"text_height_mm": "20"},
        headers=headers,
    )
    assert patch_resp.status_code == 200, patch_resp.text

    unchanged = await client.get(f"/organizations/{org_id}/designs/{design_id}", headers=headers)
    assert unchanged.json()["parameters_json"]["text_height_mm"] == 15.843
    assert unchanged.json()["content_hash"] == original_hash
    assert unchanged.json()["status"] == "generated"

    regen_resp = await client.post(
        f"/organizations/{org_id}/designs/{design_id}/regenerate", headers=headers
    )
    assert regen_resp.status_code == 200, regen_resp.text
    regen_body = regen_resp.json()
    assert regen_body["status"] == "queued"
    assert regen_body["parameters_json"]["text_height_mm"] == 20.0
    assert regen_body["content_hash"] != original_hash

    await worker_tasks._generate_design(design_id)
    final = await client.get(f"/organizations/{org_id}/designs/{design_id}", headers=headers)
    assert final.json()["status"] == "generated"
    assert final.json()["error_message"] is None


async def test_regenerate_unknown_design_returns_404(client: AsyncClient) -> None:
    import uuid

    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    resp = await client.post(
        f"/organizations/{org_id}/designs/{uuid.uuid4()}/regenerate", headers=headers
    )
    assert resp.status_code == 404


async def test_update_design_changes_fields_and_requeues(client: AsyncClient, tmp_path, monkeypatch) -> None:
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
    original_hash = create_resp.json()["content_hash"]

    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))
    await worker_tasks._generate_design(design_id)

    patch_resp = await client.patch(
        f"/organizations/{org_id}/designs/{design_id}",
        json={"name": "Sockets Label", "text": "Sockets", "label_style_profile_id": label_style_id},
        headers=headers,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    body = patch_resp.json()
    assert body["name"] == "Sockets Label"
    assert body["text"] == "Sockets"
    assert body["status"] == "queued"
    assert body["content_hash"] != original_hash

    await worker_tasks._generate_design(design_id)
    final = await client.get(f"/organizations/{org_id}/designs/{design_id}", headers=headers)
    assert final.json()["status"] == "generated"
    assert final.json()["name"] == "Sockets Label"


async def test_update_design_rejects_unknown_label_style(client: AsyncClient) -> None:
    import uuid

    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]
    _, label_style_id = await _create_magnet_and_label_style(client, org_id, headers)

    create_resp = await client.post(
        f"/organizations/{org_id}/designs",
        json={"name": "Wrenches Label", "text": "Wrenches", "label_style_profile_id": label_style_id},
        headers=headers,
    )
    design_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/organizations/{org_id}/designs/{design_id}",
        json={"name": "Wrenches Label", "text": "Wrenches", "label_style_profile_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_update_unknown_design_returns_404(client: AsyncClient) -> None:
    import uuid

    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]
    _, label_style_id = await _create_magnet_and_label_style(client, org_id, headers)

    resp = await client.patch(
        f"/organizations/{org_id}/designs/{uuid.uuid4()}",
        json={"name": "Ghost", "text": "Ghost", "label_style_profile_id": label_style_id},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_design_with_sealed_magnet_generates_successfully(client: AsyncClient, tmp_path, monkeypatch) -> None:
    """End-to-end: a "sealed" (print-in-place) magnet profile's seal_cap_mm
    must flow all the way through build_label_parameters -> the geometry
    engine's capped-pocket path -> a real generated STL, not just pass
    schema validation."""
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    magnet_resp = await client.post(
        f"/organizations/{org_id}/profiles/magnets",
        json={
            "name": "Sealed 6x2.5mm",
            "diameter_mm": "6",
            "thickness_mm": "2.5",
            "fit_type": "sealed",
            "seal_cap_mm": "0.6",
        },
        headers=headers,
    )
    assert magnet_resp.status_code == 201, magnet_resp.text
    magnet_id = magnet_resp.json()["id"]

    label_resp = await client.post(
        f"/organizations/{org_id}/profiles/label-styles",
        json={"name": "Sealed Style", "default_magnet_profile_id": magnet_id},
        headers=headers,
    )
    assert label_resp.status_code == 201, label_resp.text
    label_style_id = label_resp.json()["id"]

    create_resp = await client.post(
        f"/organizations/{org_id}/designs",
        json={"name": "Sealed Label", "text": "Wrenches", "label_style_profile_id": label_style_id},
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    assert create_resp.json()["parameters_json"]["magnets"]["seal_cap_mm"] == 0.6
    design_id = create_resp.json()["id"]

    monkeypatch.setattr(worker_tasks.settings, "generated_files_dir", str(tmp_path))
    await worker_tasks._generate_design(design_id)

    get_resp = await client.get(f"/organizations/{org_id}/designs/{design_id}", headers=headers)
    assert get_resp.json()["status"] == "generated"
    assert get_resp.json()["error_message"] is None


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
