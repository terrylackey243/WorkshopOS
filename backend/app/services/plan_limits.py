from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Organization, Plan

#: Human-readable labels for the 402 error message, keyed by the Plan column name.
_FIELD_LABELS = {
    "max_shops": "shops",
    "max_toolboxes": "toolboxes",
    "max_drawers": "drawers",
    "max_tools": "tools",
    "max_users": "users",
}


async def enforce_plan_limit(
    session: AsyncSession,
    organization: Organization,
    field: str,
    count_stmt: Select,
) -> None:
    """Raise HTTP 402 if creating one more row of `field`'s kind would exceed the org's plan.

    `field` is one of Plan's nullable limit columns (e.g. "max_shops"); NULL
    means unlimited. `count_stmt` must be a `select(func.count())`-style
    statement already scoped to this organization's existing rows.
    """
    plan = await session.get(Plan, organization.plan_id)
    if plan is None:
        return

    limit = getattr(plan, field)
    if limit is None:
        return

    current_count = await session.scalar(count_stmt)
    if (current_count or 0) >= limit:
        label = _FIELD_LABELS.get(field, field)
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Plan '{plan.key}' allows at most {limit} {label}. Upgrade your plan to add more.",
        )
