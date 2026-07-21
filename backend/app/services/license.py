from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import jwt

# Self-hosted license keys are Ed25519-signed JWTs, offline-verifiable
# against this app's fixed public key (Settings.license_public_key) -- no
# network call, no phone-home. Mirrors `security.py`'s `decode_access_token`
# defensive posture: algorithms is always a fixed, explicit list (never let
# the token pick its own alg -- that's the classic "alg: none" JWT forgery),
# never "EdDSA" plus anything else.
LICENSE_ISSUER = "workshopos-license"
VALID_TIERS = {"pro", "enterprise"}


class InvalidLicenseError(ValueError):
    """Raised for any license verification failure.

    Deliberately generic: bad signature, malformed payload, missing claims,
    and unknown tier all raise this same type with the same message, so a
    caller (and, in turn, an HTTP error response) can never leak *which*
    check failed. Distinguishing "bad signature" from "unknown tier" would
    hand a forger a free oracle for probing key/payload guesses.
    """


@dataclass(frozen=True)
class LicenseClaims:
    """Decoded, verified contents of an activated license key."""

    licensee: str
    tier: str
    license_id: str
    issued_at: datetime
    expires_at: datetime | None


def verify_license_key(token: str, public_key_pem: str) -> LicenseClaims:
    """Verify an Ed25519-signed license JWT offline against `public_key_pem`.

    Raises `InvalidLicenseError` for any failure: bad/missing signature,
    malformed or incomplete payload, wrong issuer, or a tier this app
    doesn't recognize.

    NOTE on expiry: the JWT shape supports an optional `exp` claim (see
    `scripts/mint_license.py --expires-days`) for future flexibility, but
    expiry is deliberately NOT enforced here. Doing so correctly requires
    distinguishing "expired license" from "no license" (only downgrading an
    org that reached its current tier *via* a license, not via Stripe), and
    there is no shipped key today that even sets `exp` -- the mint script
    defaults to perpetual, and no distribution channel exists yet where an
    expiring key would matter. Building enforcement for zero current callers
    is exactly the complexity worth deferring (see the plan doc's Scope
    limits). `verify_exp` is explicitly disabled below so this is a stated
    decision, not an accidental gap: a past-`exp` token still verifies today.
    """
    if not public_key_pem:
        raise InvalidLicenseError("License verification is not configured on this server.")

    try:
        payload = jwt.decode(
            token,
            public_key_pem,
            algorithms=["EdDSA"],
            issuer=LICENSE_ISSUER,
            options={"require": ["iss", "sub", "tier", "iat", "jti"], "verify_exp": False},
        )
    except jwt.PyJWTError as exc:
        raise InvalidLicenseError("Invalid or malformed license key.") from exc

    tier = payload.get("tier")
    if tier not in VALID_TIERS:
        raise InvalidLicenseError("Invalid or malformed license key.")

    expires_at: datetime | None = None
    if payload.get("exp") is not None:
        expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

    return LicenseClaims(
        licensee=payload["sub"],
        tier=tier,
        license_id=payload["jti"],
        issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
        expires_at=expires_at,
    )
