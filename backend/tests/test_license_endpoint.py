"""HTTP-level tests for POST /organizations/{id}/license.

Uses a throwaway Ed25519 keypair (distinct from the real signing key) and
monkeypatches the process-wide Settings singleton's `deployment_mode` /
`license_public_key` -- `get_settings()` is `lru_cache`d, so mutating the
returned instance's attributes is the correct way to flip these for a test
without touching real .env state (see app/config.py).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import AsyncClient

from app.config import get_settings
from app.services.license import LICENSE_ISSUER

from .conftest import auth_headers, register_org


def _generate_keypair() -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def _mint(private_key_pem: str, *, tier: str = "pro", licensee: str = "Test Licensee") -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "iss": LICENSE_ISSUER,
        "sub": licensee,
        "tier": tier,
        "iat": now,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, private_key_pem, algorithm="EdDSA")


@pytest.fixture
def self_hosted_mode(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """Flips the app into self_hosted mode with a throwaway license keypair
    for the duration of one test."""
    private_pem, public_pem = _generate_keypair()
    settings = get_settings()
    monkeypatch.setattr(settings, "deployment_mode", "self_hosted")
    monkeypatch.setattr(settings, "license_public_key", public_pem)
    return private_pem, public_pem


async def test_activate_pro_license_updates_plan(client: AsyncClient, self_hosted_mode: tuple[str, str]) -> None:
    private_pem, _public_pem = self_hosted_mode
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    token = _mint(private_pem, tier="pro", licensee="Acme Corp")
    resp = await client.post(f"/organizations/{org_id}/license", json={"license_key": token}, headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["plan"]["key"] == "pro"
    assert body["license_tier"] == "pro"
    assert body["license_activated_at"] is not None


async def test_activate_enterprise_license_updates_plan(client: AsyncClient, self_hosted_mode: tuple[str, str]) -> None:
    private_pem, _public_pem = self_hosted_mode
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    token = _mint(private_pem, tier="enterprise")
    resp = await client.post(f"/organizations/{org_id}/license", json={"license_key": token}, headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["plan"]["key"] == "enterprise"


async def test_garbage_license_key_returns_400(client: AsyncClient, self_hosted_mode: tuple[str, str]) -> None:
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    resp = await client.post(
        f"/organizations/{org_id}/license", json={"license_key": "not-a-real-jwt"}, headers=headers
    )
    assert resp.status_code == 400


async def test_tampered_license_key_returns_400(client: AsyncClient, self_hosted_mode: tuple[str, str]) -> None:
    private_pem, _public_pem = self_hosted_mode
    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    token = _mint(private_pem, tier="pro")
    header_b64, payload_b64, sig_b64 = token.split(".")
    tampered = f"{header_b64}.{payload_b64[:-4]}abcd.{sig_b64}"

    resp = await client.post(f"/organizations/{org_id}/license", json={"license_key": tampered}, headers=headers)
    assert resp.status_code == 400


async def test_license_endpoint_404s_in_saas_mode(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "deployment_mode", "saas")

    data = await register_org(client)
    headers = auth_headers(data["access_token"])
    org_id = data["organization_id"]

    resp = await client.post(
        f"/organizations/{org_id}/license", json={"license_key": "irrelevant"}, headers=headers
    )
    assert resp.status_code == 404
