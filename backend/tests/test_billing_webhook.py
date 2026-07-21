"""Tests for POST /billing/webhook -- this app's own signature verification
and event-dispatch logic, exercised by hand-constructing and HMAC-signing a
Stripe event payload against a fixed test webhook secret. Deliberately does
NOT hit live Stripe: `verify_webhook_signature` is a thin wrapper on
`stripe.Webhook.construct_event`, which is Stripe SDK code, not this app's
logic -- the correct boundary for an automated test is this app's dispatch
behavior given a validly (or invalidly) signed payload, per the plan doc.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import PRO_PLAN_ID, Plan

from .conftest import auth_headers, register_org

TEST_WEBHOOK_SECRET = "whsec_test_fixed_secret_for_offline_verification"


def _sign(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.{payload.decode()}".encode()
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={signature}"


def _event_payload(event_type: str, data_object: dict) -> bytes:
    body = {
        "id": f"evt_{uuid.uuid4().hex}",
        "object": "event",
        "type": event_type,
        "data": {"object": data_object},
    }
    return json.dumps(body).encode()


@pytest.fixture
def saas_mode(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    monkeypatch.setattr(settings, "stripe_webhook_secret", TEST_WEBHOOK_SECRET)
    return settings


async def _post_webhook(client: AsyncClient, payload: bytes, sig_header: str):
    return await client.post(
        "/billing/webhook",
        content=payload,
        headers={"stripe-signature": sig_header, "content-type": "application/json"},
    )


async def test_checkout_completed_sets_customer_and_plan(client: AsyncClient, saas_mode) -> None:
    data = await register_org(client)
    org_id = data["organization_id"]
    headers = auth_headers(data["access_token"])

    payload = _event_payload(
        "checkout.session.completed",
        {
            "customer": "cus_test_abc123",
            "subscription": "sub_test_abc123",
            "metadata": {"organization_id": org_id, "tier": "pro"},
        },
    )
    resp = await _post_webhook(client, payload, _sign(payload, TEST_WEBHOOK_SECRET))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"received": True}

    org_resp = await client.get(f"/organizations/{org_id}", headers=headers)
    assert org_resp.json()["plan"]["key"] == "pro"


async def test_subscription_updated_active_resolves_plan_by_price(
    client: AsyncClient, saas_mode, db_session: AsyncSession
) -> None:
    # Give Pro a stripe_price_id to resolve against (NULL by default in test seed data).
    pro_plan = await db_session.get(Plan, PRO_PLAN_ID)
    pro_plan.stripe_price_id = "price_test_pro_123"
    await db_session.commit()

    data = await register_org(client)
    org_id = data["organization_id"]
    headers = auth_headers(data["access_token"])

    # First, a checkout.session.completed to establish stripe_customer_id
    # (webhook handlers key off customer_id, not organization_id, for
    # subscription events -- they carry no org-scoped URL).
    checkout_payload = _event_payload(
        "checkout.session.completed",
        {
            "customer": "cus_test_xyz789",
            "subscription": "sub_test_xyz789",
            "metadata": {"organization_id": org_id, "tier": "pro"},
        },
    )
    resp = await _post_webhook(client, checkout_payload, _sign(checkout_payload, TEST_WEBHOOK_SECRET))
    assert resp.status_code == 200, resp.text

    updated_payload = _event_payload(
        "customer.subscription.updated",
        {
            "customer": "cus_test_xyz789",
            "status": "active",
            "items": {"data": [{"price": {"id": "price_test_pro_123"}}]},
        },
    )
    resp = await _post_webhook(client, updated_payload, _sign(updated_payload, TEST_WEBHOOK_SECRET))
    assert resp.status_code == 200, resp.text

    org_resp = await client.get(f"/organizations/{org_id}", headers=headers)
    assert org_resp.json()["plan"]["key"] == "pro"


async def test_subscription_updated_inactive_downgrades_to_free(
    client: AsyncClient, saas_mode, db_session: AsyncSession
) -> None:
    pro_plan = await db_session.get(Plan, PRO_PLAN_ID)
    pro_plan.stripe_price_id = "price_test_pro_456"
    await db_session.commit()

    data = await register_org(client)
    org_id = data["organization_id"]
    headers = auth_headers(data["access_token"])

    checkout_payload = _event_payload(
        "checkout.session.completed",
        {
            "customer": "cus_test_inactive1",
            "subscription": "sub_test_inactive1",
            "metadata": {"organization_id": org_id, "tier": "pro"},
        },
    )
    resp = await _post_webhook(client, checkout_payload, _sign(checkout_payload, TEST_WEBHOOK_SECRET))
    assert resp.status_code == 200, resp.text

    canceled_payload = _event_payload(
        "customer.subscription.updated",
        {"customer": "cus_test_inactive1", "status": "past_due", "items": {"data": []}},
    )
    resp = await _post_webhook(client, canceled_payload, _sign(canceled_payload, TEST_WEBHOOK_SECRET))
    assert resp.status_code == 200, resp.text

    org_resp = await client.get(f"/organizations/{org_id}", headers=headers)
    assert org_resp.json()["plan"]["key"] == "free"


async def test_subscription_deleted_downgrades_to_free(client: AsyncClient, saas_mode) -> None:
    data = await register_org(client)
    org_id = data["organization_id"]
    headers = auth_headers(data["access_token"])

    checkout_payload = _event_payload(
        "checkout.session.completed",
        {
            "customer": "cus_test_del1",
            "subscription": "sub_test_del1",
            "metadata": {"organization_id": org_id, "tier": "pro"},
        },
    )
    resp = await _post_webhook(client, checkout_payload, _sign(checkout_payload, TEST_WEBHOOK_SECRET))
    assert resp.status_code == 200, resp.text

    deleted_payload = _event_payload("customer.subscription.deleted", {"customer": "cus_test_del1"})
    resp = await _post_webhook(client, deleted_payload, _sign(deleted_payload, TEST_WEBHOOK_SECRET))
    assert resp.status_code == 200, resp.text

    org_resp = await client.get(f"/organizations/{org_id}", headers=headers)
    assert org_resp.json()["plan"]["key"] == "free"


async def test_unknown_event_type_is_a_noop_200(client: AsyncClient, saas_mode) -> None:
    payload = _event_payload("payment_intent.succeeded", {"id": "pi_irrelevant"})
    resp = await _post_webhook(client, payload, _sign(payload, TEST_WEBHOOK_SECRET))
    assert resp.status_code == 200
    assert resp.json() == {"received": True}


async def test_bad_signature_returns_400(client: AsyncClient, saas_mode) -> None:
    payload = _event_payload("checkout.session.completed", {"customer": "cus_x"})
    resp = await _post_webhook(client, payload, _sign(payload, "wrong-secret-entirely"))
    assert resp.status_code == 400


async def test_tampered_payload_returns_400(client: AsyncClient, saas_mode) -> None:
    payload = _event_payload("checkout.session.completed", {"customer": "cus_x"})
    sig = _sign(payload, TEST_WEBHOOK_SECRET)
    tampered_payload = payload.replace(b"cus_x", b"cus_hacked")
    resp = await _post_webhook(client, tampered_payload, sig)
    assert resp.status_code == 400


async def test_webhook_404s_in_self_hosted_mode(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "deployment_mode", "self_hosted")
    monkeypatch.setattr(settings, "stripe_webhook_secret", TEST_WEBHOOK_SECRET)

    payload = _event_payload("checkout.session.completed", {"customer": "cus_x"})
    resp = await _post_webhook(client, payload, _sign(payload, TEST_WEBHOOK_SECRET))
    assert resp.status_code == 404
