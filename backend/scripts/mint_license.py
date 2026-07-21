#!/usr/bin/env python
"""Standalone CLI to mint a WorkshopOS self-hosted license key.

Run locally from a venv (`pip install pyjwt[crypto]`) -- never imported by
the app, never runs inside a container (`backend/Dockerfile` only COPYs
`app/`, `alembic/`, `alembic.ini`, so this file never ships in the runtime
image), and nothing under `app/` imports it.

Usage:

    python backend/scripts/mint_license.py \\
        --private-key ~/.workshopos/license_ed25519_private.pem \\
        --licensee "Acme Corp" \\
        --tier pro \\
        [--expires-days 365]

Prints the signed JWT to stdout. Paste it into the target deployment's
Settings > License panel (self-hosted mode only).
"""

from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timedelta, timezone

import jwt

LICENSE_ISSUER = "workshopos-license"
VALID_TIERS = ("pro", "enterprise")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--private-key", required=True, help="Path to the Ed25519 private key PEM file.")
    parser.add_argument("--licensee", required=True, help="Name/identifier of the licensee (JWT 'sub' claim).")
    parser.add_argument("--tier", required=True, choices=VALID_TIERS, help="Plan tier to grant.")
    parser.add_argument(
        "--expires-days",
        type=int,
        default=None,
        help=(
            "Optional expiry, in days from now. Omit for a perpetual key "
            "(no 'exp' claim) -- the default, and today the only kind this "
            "app actually enforces (see app/services/license.py's docstring "
            "on why exp isn't enforced yet)."
        ),
    )
    args = parser.parse_args()

    with open(args.private_key, "r", encoding="utf-8") as fh:
        private_key_pem = fh.read()

    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "iss": LICENSE_ISSUER,
        "sub": args.licensee,
        "tier": args.tier,
        "iat": now,
        "jti": str(uuid.uuid4()),
    }
    if args.expires_days is not None:
        payload["exp"] = now + timedelta(days=args.expires_days)

    token = jwt.encode(payload, private_key_pem, algorithm="EdDSA")
    print(token)


if __name__ == "__main__":
    main()
