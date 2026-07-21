from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models import FREE_PLAN_ID, Membership, Organization, Plan, User
from ..schemas.auth import LoginRequest, MeResponse, OrganizationSummary, RegisterRequest, RegisterResponse, TokenResponse, UserRead
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    slug = _SLUG_INVALID_CHARS.sub("-", value.lower()).strip("-")
    return slug or "org"


async def _unique_slug(session: AsyncSession, base: str) -> str:
    slug = _slugify(base)
    candidate = slug
    suffix = 1
    while await session.scalar(select(Organization.id).where(Organization.slug == candidate)) is not None:
        suffix += 1
        candidate = f"{slug}-{suffix}"
    return candidate


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: AsyncSession = Depends(get_session)) -> RegisterResponse:
    existing = await session.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists.")

    slug = await _unique_slug(session, payload.organization_name)

    organization = Organization(name=payload.organization_name, slug=slug, plan_id=FREE_PLAN_ID)
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        display_name=payload.display_name,
    )
    session.add_all([organization, user])
    await session.flush()  # assign organization.id / user.id without committing

    membership = Membership(organization_id=organization.id, user_id=user.id, role="owner")
    session.add(membership)

    await session.commit()
    await session.refresh(user)
    await session.refresh(organization)

    token = create_access_token(subject=user.id)
    return RegisterResponse(
        user=UserRead.model_validate(user),
        organization_id=organization.id,
        organization_slug=organization.slug,
        access_token=token,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    user = await session.scalar(select(User).where(User.email == payload.email))
    if user is None or not user.is_active or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    token = create_access_token(subject=user.id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=MeResponse)
async def me(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MeResponse:
    rows = await session.execute(
        select(Membership, Organization, Plan)
        .join(Organization, Membership.organization_id == Organization.id)
        .join(Plan, Organization.plan_id == Plan.id)
        .where(Membership.user_id == current_user.id)
    )
    organizations = [
        OrganizationSummary(id=org.id, name=org.name, slug=org.slug, plan_key=plan.key, role=membership.role)
        for membership, org, plan in rows.all()
    ]
    return MeResponse(user=UserRead.model_validate(current_user), organizations=organizations)
