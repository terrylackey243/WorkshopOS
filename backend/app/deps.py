from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_session
from .models import Membership, Organization, User
from .security import decode_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.") from exc

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive.")
    return user


async def get_current_membership(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Membership:
    """Validate a real Membership row exists for (organization_id, current_user).

    `organization_id` here is bound from the request PATH, and is only ever
    trusted because it is cross-checked against a Membership row tied to the
    authenticated user -- never trusted as a bare, unauthenticated value.
    This is the fix for the old codebase's `organization_id` query-param
    trust bug (see `Workshop-Designer/backend/app/routers/profiles.py`).
    """
    membership = await session.scalar(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.user_id == current_user.id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization.",
        )
    return membership


async def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    """Platform-operator gate for `routers/admin.py`, entirely independent of
    both `deployment_mode` and the org-membership model -- it checks the
    caller's email against `Settings.superadmin_emails` and nothing else.
    Deliberately separate from `get_current_membership`: admin routes act
    across every organization, not one the caller belongs to."""
    if current_user.email.lower() not in get_settings().superadmin_emails_set():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized.")
    return current_user


async def get_current_organization(
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> Organization:
    """Convenience dependency: same auth guarantee as get_current_membership,
    but returns the Organization row (used by plan-limit checks)."""
    organization = await session.get(Organization, membership.organization_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
    return organization
