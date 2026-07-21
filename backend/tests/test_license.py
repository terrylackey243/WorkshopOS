"""Pure unit tests for app.services.license -- no DB, no HTTP. Generates a
throwaway Ed25519 keypair inline (distinct from any real signing key) so
these tests never depend on a real license keypair existing on disk.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.license import InvalidLicenseError, LICENSE_ISSUER, verify_license_key


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


def _mint(private_key_pem: str, *, tier: str = "pro", licensee: str = "Test Licensee", exp: datetime | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "iss": LICENSE_ISSUER,
        "sub": licensee,
        "tier": tier,
        "iat": now,
        "jti": str(uuid.uuid4()),
    }
    if exp is not None:
        payload["exp"] = exp
    return jwt.encode(payload, private_key_pem, algorithm="EdDSA")


def test_valid_license_round_trips() -> None:
    private_pem, public_pem = _generate_keypair()
    token = _mint(private_pem, tier="pro", licensee="Acme Corp")

    claims = verify_license_key(token, public_pem)

    assert claims.tier == "pro"
    assert claims.licensee == "Acme Corp"
    assert claims.license_id
    assert claims.expires_at is None


def test_enterprise_tier_round_trips() -> None:
    private_pem, public_pem = _generate_keypair()
    token = _mint(private_pem, tier="enterprise")

    claims = verify_license_key(token, public_pem)

    assert claims.tier == "enterprise"


def test_wrong_keypair_is_rejected() -> None:
    private_pem, _public_pem = _generate_keypair()
    _other_private_pem, other_public_pem = _generate_keypair()
    token = _mint(private_pem)

    with pytest.raises(InvalidLicenseError):
        verify_license_key(token, other_public_pem)


def test_tampered_payload_is_rejected() -> None:
    private_pem, public_pem = _generate_keypair()
    token = _mint(private_pem, tier="pro")

    header_b64, payload_b64, sig_b64 = token.split(".")
    # Swap in a differently-encoded (but structurally valid) payload segment
    # without re-signing -- the signature no longer matches, exactly what a
    # forger tampering with a captured token would produce.
    tampered_token = f"{header_b64}.{payload_b64[:-4]}abcd.{sig_b64}"

    with pytest.raises(InvalidLicenseError):
        verify_license_key(tampered_token, public_pem)


def test_unknown_tier_is_rejected() -> None:
    private_pem, public_pem = _generate_keypair()
    token = _mint(private_pem, tier="ultra-mega-plan")

    with pytest.raises(InvalidLicenseError):
        verify_license_key(token, public_pem)


def test_wrong_issuer_is_rejected() -> None:
    private_pem, public_pem = _generate_keypair()
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"iss": "someone-else", "sub": "Acme", "tier": "pro", "iat": now, "jti": str(uuid.uuid4())},
        private_pem,
        algorithm="EdDSA",
    )

    with pytest.raises(InvalidLicenseError):
        verify_license_key(token, public_pem)


def test_missing_required_claim_is_rejected() -> None:
    private_pem, public_pem = _generate_keypair()
    now = datetime.now(timezone.utc)
    # No 'jti'.
    token = jwt.encode(
        {"iss": LICENSE_ISSUER, "sub": "Acme", "tier": "pro", "iat": now},
        private_pem,
        algorithm="EdDSA",
    )

    with pytest.raises(InvalidLicenseError):
        verify_license_key(token, public_pem)


def test_garbage_token_is_rejected() -> None:
    _private_pem, public_pem = _generate_keypair()

    with pytest.raises(InvalidLicenseError):
        verify_license_key("not.a.jwt", public_pem)


def test_past_expiry_still_verifies_today() -> None:
    """Deliberate current behavior, not a bug: expiry is supported in the
    JWT shape but not enforced anywhere in this milestone (see
    license.py's docstring on why). A token with a long-past `exp` still
    verifies successfully today."""
    private_pem, public_pem = _generate_keypair()
    past = datetime.now(timezone.utc) - timedelta(days=3650)
    token = _mint(private_pem, tier="pro", exp=past)

    claims = verify_license_key(token, public_pem)

    assert claims.tier == "pro"
    assert claims.expires_at is not None
    assert claims.expires_at < datetime.now(timezone.utc)


def test_missing_public_key_is_rejected() -> None:
    private_pem, _public_pem = _generate_keypair()
    token = _mint(private_pem)

    with pytest.raises(InvalidLicenseError):
        verify_license_key(token, "")
