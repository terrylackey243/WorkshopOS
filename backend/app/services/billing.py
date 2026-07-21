from __future__ import annotations

import stripe

from ..config import get_settings
from ..models import Organization, Plan

# Thin wrappers around the Stripe Python SDK -- kept as their own functions
# (rather than inlined in the router) specifically so `verify_webhook_signature`
# is independently unit-testable offline with a hand-constructed+signed
# payload (see tests/test_billing_webhook.py), which is the correct boundary
# for an automated test: this app's own verification/dispatch logic, not
# live Stripe itself.


def _configure_stripe() -> None:
    """Point the stripe SDK at the current secret key.

    Read fresh from settings on every call (rather than once at import time)
    so a test process that never sets STRIPE_SECRET_KEY doesn't blow up at
    import, and so the key always reflects the live Settings singleton.
    """
    stripe.api_key = get_settings().stripe_secret_key


def create_checkout_session(organization: Organization, plan: Plan, customer_email: str) -> str:
    """Create a Stripe Checkout Session (mode=subscription) for `organization`
    to subscribe to `plan`, returning the hosted Checkout URL.

    Redirect-based Checkout, not embedded Elements: the frontend does a
    plain `window.location.assign(url)` -- no @stripe/stripe-js dependency,
    no PCI-scope UI, no client-secret plumbing.

    Reuses `organization.stripe_customer_id` if this org has already checked
    out before (keeps a single Stripe Customer per org across repeat
    attempts); otherwise lets Stripe create one from `customer_email`.
    `metadata` carries `organization_id`/`tier` so the webhook handler can
    key off it without any other lookup.
    """
    _configure_stripe()
    settings = get_settings()

    kwargs: dict = {
        "mode": "subscription",
        "line_items": [{"price": plan.stripe_price_id, "quantity": 1}],
        "success_url": f"{settings.app_public_url}/settings?checkout=success",
        "cancel_url": f"{settings.app_public_url}/settings?checkout=cancel",
        "metadata": {"organization_id": str(organization.id), "tier": plan.key},
        "subscription_data": {"metadata": {"organization_id": str(organization.id), "tier": plan.key}},
    }
    if organization.stripe_customer_id:
        kwargs["customer"] = organization.stripe_customer_id
    else:
        kwargs["customer_email"] = customer_email

    session = stripe.checkout.Session.create(**kwargs)
    return session.url


def create_portal_session(organization: Organization) -> str:
    """Create a Stripe Billing Portal session for an org that already has a
    `stripe_customer_id`, returning the hosted portal URL."""
    _configure_stripe()
    settings = get_settings()

    session = stripe.billing_portal.Session.create(
        customer=organization.stripe_customer_id,
        return_url=f"{settings.app_public_url}/settings",
    )
    return session.url


def verify_webhook_signature(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify a raw webhook request body against Stripe's HMAC signature
    header, returning the parsed `stripe.Event` on success.

    Raises `stripe.error.SignatureVerificationError` (a `stripe.error.StripeError`)
    on any failure -- bad signature, wrong secret, tampered payload, or a
    stale timestamp outside Stripe's default tolerance window. Callers
    should catch broadly and respond 400; never leak which specific check
    failed, same defensive posture as `license.py`'s `InvalidLicenseError`.
    """
    return stripe.Webhook.construct_event(payload, sig_header, get_settings().stripe_webhook_secret)
