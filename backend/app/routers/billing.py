from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..deps import get_current_organization, get_current_user
from ..models import FREE_PLAN_ID, Organization, Plan, User
from ..schemas.billing import CheckoutRequest, CheckoutResponse, LicenseActivateRequest, PortalResponse
from ..schemas.org import OrganizationDetailRead, PlanRead
from ..services import billing as billing_service
from ..services.license import InvalidLicenseError, verify_license_key

# Two distribution channels, two upgrade mechanisms, sharing one router:
# self-hosted license activation and SaaS Stripe checkout/portal/webhook.
# Each non-webhook route path is scoped under /organizations/{organization_id}
# like every other org-scoped mutation in this app; the webhook is top-level
# since it carries no org-scoped URL (Stripe looks the org up itself, by
# stripe_customer_id).
router = APIRouter(tags=["billing"])


def _not_found_unless_mode(expected_mode: str) -> None:
    """404s (not 403) when this deployment isn't in `expected_mode` --
    indistinguishable from "route doesn't exist" for the wrong channel."""
    if get_settings().deployment_mode != expected_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


def _organization_detail(organization: Organization, plan: Plan) -> OrganizationDetailRead:
    return OrganizationDetailRead(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        plan_id=organization.plan_id,
        plan=PlanRead.model_validate(plan),
        license_tier=organization.license_tier,
        license_activated_at=organization.license_activated_at,
        anthropic_api_key_configured=organization.anthropic_api_key_ciphertext is not None,
    )


@router.post("/organizations/{organization_id}/license", response_model=OrganizationDetailRead)
async def activate_license(
    organization_id: uuid.UUID,
    payload: LicenseActivateRequest,
    # Gated by get_current_organization same as every other org-scoped
    # mutation -- no new role check (matches "no platform-superadmin" scope
    # limit in the plan doc).
    organization: Organization = Depends(get_current_organization),
    session: AsyncSession = Depends(get_session),
) -> OrganizationDetailRead:
    _not_found_unless_mode("self_hosted")

    settings = get_settings()
    try:
        claims = verify_license_key(payload.license_key, settings.license_public_key or "")
    except InvalidLicenseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    plan = await session.scalar(select(Plan).where(Plan.key == claims.tier))
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown license tier '{claims.tier}'."
        )

    organization.plan_id = plan.id
    organization.license_key = payload.license_key
    organization.license_tier = claims.tier
    organization.license_activated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(organization)
    return _organization_detail(organization, plan)


@router.post("/organizations/{organization_id}/billing/checkout", response_model=CheckoutResponse)
async def create_checkout(
    organization_id: uuid.UUID,
    payload: CheckoutRequest,
    organization: Organization = Depends(get_current_organization),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CheckoutResponse:
    _not_found_unless_mode("saas")

    plan = await session.scalar(select(Plan).where(Plan.key == payload.tier))
    if plan is None or plan.stripe_price_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Plan '{payload.tier}' is not available for checkout.",
        )

    checkout_url = billing_service.create_checkout_session(organization, plan, current_user.email)
    return CheckoutResponse(checkout_url=checkout_url)


@router.post("/organizations/{organization_id}/billing/portal", response_model=PortalResponse)
async def create_portal(
    organization_id: uuid.UUID,
    organization: Organization = Depends(get_current_organization),
) -> PortalResponse:
    _not_found_unless_mode("saas")

    if not organization.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No billing account exists yet for this organization. Complete a checkout first.",
        )

    portal_url = billing_service.create_portal_session(organization)
    return PortalResponse(portal_url=portal_url)


@router.post("/billing/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    """Stripe webhook receiver. No auth dependency -- Stripe can't send a
    bearer token, its only protection is the HMAC signature check below.
    """
    _not_found_unless_mode("saas")

    # Read the raw body BEFORE any JSON parsing -- the signature is computed
    # over the exact bytes Stripe sent.
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = billing_service.verify_webhook_signature(payload, sig_header)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature.") from exc

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(session, data)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(session, data)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(session, data)
    # else: no-op -- Stripe expects a 2xx for event types we don't act on,
    # or it will keep retrying delivery.

    return {"received": True}


async def _handle_checkout_completed(session: AsyncSession, data: dict) -> None:
    metadata = data.get("metadata") or {}
    organization_id = metadata.get("organization_id")
    tier = metadata.get("tier")
    if not organization_id:
        return

    organization = await session.get(Organization, uuid.UUID(organization_id))
    if organization is None:
        return

    organization.stripe_customer_id = data.get("customer")
    organization.stripe_subscription_id = data.get("subscription")
    if tier:
        plan = await session.scalar(select(Plan).where(Plan.key == tier))
        if plan is not None:
            organization.plan_id = plan.id
    await session.commit()


async def _handle_subscription_updated(session: AsyncSession, data: dict) -> None:
    customer_id = data.get("customer")
    if not customer_id:
        return
    organization = await session.scalar(select(Organization).where(Organization.stripe_customer_id == customer_id))
    if organization is None:
        return

    subscription_status = data.get("status")
    if subscription_status in ("active", "trialing"):
        items = (data.get("items") or {}).get("data") or []
        price_id = items[0]["price"]["id"] if items and items[0].get("price") else None
        plan = None
        if price_id:
            plan = await session.scalar(select(Plan).where(Plan.stripe_price_id == price_id))
        if plan is not None:
            organization.plan_id = plan.id
    else:
        organization.plan_id = FREE_PLAN_ID
    await session.commit()


async def _handle_subscription_deleted(session: AsyncSession, data: dict) -> None:
    customer_id = data.get("customer")
    if not customer_id:
        return
    organization = await session.scalar(select(Organization).where(Organization.stripe_customer_id == customer_id))
    if organization is None:
        return

    organization.plan_id = FREE_PLAN_ID
    organization.stripe_subscription_id = None
    await session.commit()
