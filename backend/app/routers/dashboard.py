from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_membership
from ..models import Membership, Tool
from ..schemas.dashboard import DashboardRead

router = APIRouter(prefix="/organizations/{organization_id}/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardRead)
async def get_dashboard(
    organization_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> DashboardRead:
    """First cross-entity aggregation endpoint in this app -- every other
    list endpoint is strictly single-entity-type and org- or
    drawer-scoped. Every bucket here is still Tool-only, so this stays a
    plain SELECT plus Python-side filtering, not a more general
    aggregation framework -- revisit if a genuinely cross-table source is
    ever added.
    """
    now = datetime.now(timezone.utc)

    checked_out_rows = list(
        await session.scalars(
            select(Tool)
            .where(Tool.organization_id == organization_id, Tool.checked_out_to.is_not(None))
            .order_by(Tool.checked_out_at)
        )
    )
    overdue = [t for t in checked_out_rows if t.checkout_due_at is not None and t.checkout_due_at < now]
    overdue_ids = {t.id for t in overdue}
    active = [t for t in checked_out_rows if t.id not in overdue_ids]

    # Fetch broadly (interval_days IS NOT NULL) then filter in Python --
    # matches the checkout buckets' own style above, and sidesteps doing
    # per-row interval arithmetic in the SQL layer for a value that's a
    # column, not a constant.
    maintenance_candidates = list(
        await session.scalars(
            select(Tool).where(
                Tool.organization_id == organization_id, Tool.maintenance_interval_days.is_not(None)
            )
        )
    )
    maintenance_due = [
        t
        for t in maintenance_candidates
        if t.last_maintained_at is None
        or t.last_maintained_at + timedelta(days=t.maintenance_interval_days) < now
    ]

    from ..routers.tools import _attach_derived_fields

    await _attach_derived_fields(session, overdue + active + maintenance_due)

    return DashboardRead(overdue_checkouts=overdue, active_checkouts=active, maintenance_due=maintenance_due)
