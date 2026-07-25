"""Tests for AI Import: BYOK API-key storage and prompt-to-preview extraction.

`extract_rows` (the actual Anthropic call) is always monkeypatched here --
no test makes a real network call. Endpoint tests exercise everything
around it: key storage/encryption, the "no key configured" guard, and
name-conflict flagging against existing profiles.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient

import io

from PIL import Image

from app.config import get_settings
from app.models import DrawerProfile
from app.services.crypto import decrypt_secret, encrypt_secret
from app.services.ai_profile_extraction import convert_and_map
from app.services.ai_tool_extraction import _prepare_image

from .conftest import auth_headers, register_org


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "settings_encryption_key", Fernet.generate_key().decode())


async def test_set_get_and_clear_api_key(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    resp = await client.get(f"/organizations/{org_id}", headers=headers)
    assert resp.json()["anthropic_api_key_configured"] is False

    resp = await client.post(
        f"/organizations/{org_id}/ai-settings", json={"anthropic_api_key": "sk-ant-test-key"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["anthropic_api_key_configured"] is True
    assert "sk-ant-test-key" not in resp.text  # never echo the raw key back
    assert "anthropic_api_key" not in body  # and no ciphertext field either

    resp = await client.get(f"/organizations/{org_id}", headers=headers)
    assert resp.json()["anthropic_api_key_configured"] is True

    resp = await client.delete(f"/organizations/{org_id}/ai-settings", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["anthropic_api_key_configured"] is False


async def test_extract_requires_api_key(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    resp = await client.post(
        f"/organizations/{org_id}/ai-import/extract",
        json={"profile_type": "drawer_profile", "unit": "in", "prompt": "22x14.5x2 drawer"},
        headers=headers,
    )
    assert resp.status_code == 400


async def test_extract_surfaces_bad_api_key_as_400(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected Anthropic key should read as a clean 400, not a raw 500 --
    found by hand while verifying the real deployment with a fake key."""
    import anthropic
    import httpx

    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    await client.post(f"/organizations/{org_id}/ai-settings", json={"anthropic_api_key": "sk-ant-bad"}, headers=headers)

    async def _raise_auth_error(api_key: str, profile_type: str, unit: str, prompt: str):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(401, request=request)
        raise anthropic.AuthenticationError("invalid x-api-key", response=response, body=None)

    monkeypatch.setattr("app.routers.ai_import.extract_rows", _raise_auth_error)

    resp = await client.post(
        f"/organizations/{org_id}/ai-import/extract",
        json={"profile_type": "drawer_profile", "unit": "in", "prompt": "22x14.5x2 drawer"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "API key" in resp.json()["detail"]


async def test_extract_flags_name_conflict(
    client: AsyncClient, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    await client.post(f"/organizations/{org_id}/ai-settings", json={"anthropic_api_key": "sk-ant-test-key"}, headers=headers)

    db_session.add(
        DrawerProfile(
            organization_id=org_id,
            name="22x14.5x2",
            inside_width_mm=Decimal("558.8"),
            inside_depth_mm=Decimal("368.3"),
            inside_height_mm=Decimal("50.8"),
        )
    )
    await db_session.commit()

    async def _fake_extract_rows(api_key: str, profile_type: str, unit: str, prompt: str) -> list[dict]:
        return [
            {"name": "22x14.5x2", "inside_width": 22, "inside_depth": 14.5, "inside_height": 2},
            {"inside_width": 22, "inside_depth": 16, "inside_height": 3},  # no name -- should stay unnamed
        ]

    monkeypatch.setattr("app.routers.ai_import.extract_rows", _fake_extract_rows)

    resp = await client.post(
        f"/organizations/{org_id}/ai-import/extract",
        json={"profile_type": "drawer_profile", "unit": "in", "prompt": "two drawers"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert len(rows) == 2
    assert rows[0]["name"] == "22x14.5x2"
    assert rows[0]["name_conflict"] is True
    # Decimal fields serialize to JSON strings (Pydantic v2 default, preserves
    # precision) -- cast before comparing.
    assert float(rows[0]["fields"]["inside_width_mm"]) == pytest.approx(558.8)
    assert rows[1]["name"] is None
    assert rows[1]["name_conflict"] is False


def test_convert_and_map_converts_dimensional_fields_only() -> None:
    rows = [{"name": "Bambu X1C", "build_width": 10, "build_depth": 10, "build_height": 10, "nozzle_diameter": 0.4}]
    mapped = convert_and_map(rows, "printer", "in")[0]
    assert mapped["build_width_mm"] == Decimal("254.0")
    assert mapped["nozzle_diameter_mm"] == Decimal("0.4")  # never unit-converted


def test_convert_and_map_passes_through_mm_unchanged() -> None:
    rows = [{"name": "22x14.5x2", "inside_width": 558.8, "inside_depth": 368.3, "inside_height": 50.8}]
    mapped = convert_and_map(rows, "drawer_profile", "mm")[0]
    assert mapped["inside_width_mm"] == Decimal("558.8")


def test_encrypt_decrypt_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "settings_encryption_key", Fernet.generate_key().decode())
    ciphertext = encrypt_secret("sk-ant-super-secret")
    assert ciphertext != "sk-ant-super-secret"
    assert decrypt_secret(ciphertext) == "sk-ant-super-secret"


# --- AI Add Tool (vision extraction) -----------------------------------
# `extract_tool_rows` (the actual Anthropic vision call) is always
# monkeypatched here, same rule as `extract_rows` above -- no test makes a
# real network call or touches disk (the endpoint never persists the photo).

_FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100  # content doesn't matter -- never decoded server-side


async def test_extract_tools_requires_api_key(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    resp = await client.post(
        f"/organizations/{org_id}/tools/ai-import/extract",
        files={"file": ("sheet.jpg", _FAKE_JPEG, "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 400


async def test_extract_tools_rejects_bad_extension(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    await client.post(f"/organizations/{org_id}/ai-settings", json={"anthropic_api_key": "sk-ant-test-key"}, headers=headers)

    resp = await client.post(
        f"/organizations/{org_id}/tools/ai-import/extract",
        files={"file": ("sheet.txt", b"not a photo", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_extract_tools_accepts_heic_extension(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.heic is what iPhones shoot by default -- it must pass the extension
    gate (unlike a genuinely unsupported type like .txt above) so
    `_prepare_image` gets a chance to transcode it. The extraction call
    itself is mocked here (this is a router-level test, not exercising real
    HEIC decoding -- see test_prepare_image_converts_unsupported_media_type
    for that), so any bytes work; what's under test is that the router
    forwards media_type="image/heic" instead of rejecting the upload."""
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    await client.post(f"/organizations/{org_id}/ai-settings", json={"anthropic_api_key": "sk-ant-test-key"}, headers=headers)

    async def _fake_extract_tool_rows(api_key: str, image_bytes: bytes, media_type: str) -> list[dict]:
        assert media_type == "image/heic"
        return [{"name": "Wrench", "quantity": 1, "confidence": 80}]

    monkeypatch.setattr("app.routers.ai_import.extract_tool_rows", _fake_extract_tool_rows)

    resp = await client.post(
        f"/organizations/{org_id}/tools/ai-import/extract",
        files={"file": ("sheet.heic", b"not really heic bytes", "image/heic")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"][0]["name"] == "Wrench"


async def test_extract_tools_rejects_oversize_file(client: AsyncClient) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    await client.post(f"/organizations/{org_id}/ai-settings", json={"anthropic_api_key": "sk-ant-test-key"}, headers=headers)

    oversize = b"0" * (10 * 1024 * 1024 + 1)
    resp = await client.post(
        f"/organizations/{org_id}/tools/ai-import/extract",
        files={"file": ("sheet.jpg", oversize, "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 413


async def test_extract_tools_surfaces_bad_api_key_as_400(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import anthropic
    import httpx

    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    await client.post(f"/organizations/{org_id}/ai-settings", json={"anthropic_api_key": "sk-ant-bad"}, headers=headers)

    async def _raise_auth_error(api_key: str, image_bytes: bytes, media_type: str):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(401, request=request)
        raise anthropic.AuthenticationError("invalid x-api-key", response=response, body=None)

    monkeypatch.setattr("app.routers.ai_import.extract_tool_rows", _raise_auth_error)

    resp = await client.post(
        f"/organizations/{org_id}/tools/ai-import/extract",
        files={"file": ("sheet.jpg", _FAKE_JPEG, "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "API key" in resp.json()["detail"]


async def test_extract_tools_happy_path(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    await client.post(f"/organizations/{org_id}/ai-settings", json={"anthropic_api_key": "sk-ant-test-key"}, headers=headers)

    async def _fake_extract_tool_rows(api_key: str, image_bytes: bytes, media_type: str) -> list[dict]:
        assert media_type == "image/jpeg"
        return [
            {
                "name": "10mm Combination Wrench",
                "category": "Wrench",
                "manufacturer": "Cobalt",
                "notes": None,
                "quantity": 3,
                "confidence": 92,
            },
            {"name": "Unlabeled screwdriver", "quantity": 1, "confidence": 40},
        ]

    monkeypatch.setattr("app.routers.ai_import.extract_tool_rows", _fake_extract_tool_rows)

    resp = await client.post(
        f"/organizations/{org_id}/tools/ai-import/extract",
        files={"file": ("sheet.jpg", _FAKE_JPEG, "image/jpeg")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert len(rows) == 2
    assert rows[0]["name"] == "10mm Combination Wrench"
    assert rows[0]["quantity"] == 3
    assert rows[0]["confidence"] == 92
    assert rows[0]["manufacturer"] == "Cobalt"
    assert rows[1]["category"] is None
    assert rows[1]["confidence"] == 40


def _make_png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(200, 200, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_prepare_image_leaves_small_images_unchanged() -> None:
    original = _make_png(800, 600)
    resized, media_type = _prepare_image(original, "image/png")
    assert resized == original
    assert media_type == "image/png"


def test_prepare_image_converts_unsupported_media_type() -> None:
    """HEIC (what iPhones shoot by default) isn't a format Anthropic's vision
    API accepts -- `_prepare_image` must transcode it to JPEG regardless of
    size. Real HEIC bytes aren't needed to exercise this: `Image.open` sniffs
    the format from the bytes themselves, not the `media_type` label, so a
    small PNG mislabeled "image/heic" exercises the same "unsupported
    media_type" branch a real HEIC upload would hit."""
    original = _make_png(200, 150)
    resized, media_type = _prepare_image(original, "image/heic")
    assert resized != original
    assert media_type == "image/jpeg"
    with Image.open(io.BytesIO(resized)) as img:
        assert img.format == "JPEG"
        assert img.size == (200, 150)


def test_prepare_image_downscales_oversized_images() -> None:
    """A full-resolution phone-camera photo (e.g. a 6048x8064 iPhone portrait
    shot) exceeds Anthropic's 8000px-per-dimension hard limit and gets
    rejected with a 400 before ever reaching the model -- found by hand
    testing this feature against real camera photos. `_prepare_image` must
    downscale anything over `_MAX_LONG_EDGE_PX` before it's sent."""
    original = _make_png(6048, 8064)
    resized, media_type = _prepare_image(original, "image/png")
    assert resized != original
    assert media_type == "image/jpeg"
    with Image.open(io.BytesIO(resized)) as img:
        assert max(img.size) <= 1568
        # Aspect ratio preserved (portrait stays portrait).
        assert img.size[1] > img.size[0]
