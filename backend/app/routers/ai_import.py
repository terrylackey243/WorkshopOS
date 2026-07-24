from __future__ import annotations

import uuid

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_organization
from ..models import Organization, Plan
from ..schemas.ai_import import AiExtractedRow, AiExtractRequest, AiExtractResponse, AiSettingsUpdate
from ..schemas.org import OrganizationDetailRead, PlanRead
from ..services.ai_profile_extraction import PROFILE_TYPE_SPECS, convert_and_map, extract_rows
from ..services.crypto import decrypt_secret, encrypt_secret
from .profiles import _list as _list_profiles

# AI Import: BYOK Anthropic-key storage + prompt-to-profile-preview
# extraction. Org-scoped like every other org-scoped mutation in this app,
# gated by get_current_organization -- no extra role check, matching
# billing.py's license activation and profiles.py's CRUD engine (no
# per-role checks exist anywhere in this app today).
router = APIRouter(prefix="/organizations/{organization_id}", tags=["ai-import"])


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


@router.post("/ai-settings", response_model=OrganizationDetailRead)
async def set_ai_settings(
    organization_id: uuid.UUID,
    payload: AiSettingsUpdate,
    organization: Organization = Depends(get_current_organization),
    session: AsyncSession = Depends(get_session),
) -> OrganizationDetailRead:
    organization.anthropic_api_key_ciphertext = encrypt_secret(payload.anthropic_api_key)
    await session.commit()
    await session.refresh(organization)
    plan = await session.get(Plan, organization.plan_id)
    return _organization_detail(organization, plan)


@router.delete("/ai-settings", response_model=OrganizationDetailRead)
async def clear_ai_settings(
    organization_id: uuid.UUID,
    organization: Organization = Depends(get_current_organization),
    session: AsyncSession = Depends(get_session),
) -> OrganizationDetailRead:
    organization.anthropic_api_key_ciphertext = None
    await session.commit()
    await session.refresh(organization)
    plan = await session.get(Plan, organization.plan_id)
    return _organization_detail(organization, plan)


@router.post("/ai-import/extract", response_model=AiExtractResponse)
async def extract_profiles(
    organization_id: uuid.UUID,
    payload: AiExtractRequest,
    organization: Organization = Depends(get_current_organization),
    session: AsyncSession = Depends(get_session),
) -> AiExtractResponse:
    if organization.anthropic_api_key_ciphertext is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Anthropic API key configured for this organization.",
        )

    api_key = decrypt_secret(organization.anthropic_api_key_ciphertext)
    try:
        raw_rows = await extract_rows(api_key, payload.profile_type, payload.unit, payload.prompt)
    except anthropic.AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Anthropic rejected this API key. Check the key in Settings.",
        ) from exc
    except anthropic.APIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Anthropic API request failed: {exc.message if hasattr(exc, 'message') else exc}",
        ) from exc
    mapped_rows = convert_and_map(raw_rows, payload.profile_type, payload.unit)

    model, _ = PROFILE_TYPE_SPECS[payload.profile_type]
    existing = await _list_profiles(model, organization_id, session)
    existing_names = {row.name for row in existing}

    return AiExtractResponse(
        rows=[
            AiExtractedRow(
                name=row.get("name"),
                fields={k: v for k, v in row.items() if k != "name"},
                name_conflict=row.get("name") in existing_names if row.get("name") else False,
            )
            for row in mapped_rows
        ]
    )
