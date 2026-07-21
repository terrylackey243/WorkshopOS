from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_membership
from ..models import Design, Drawer, DrawerLayout, InsertDesign, Membership, Shop, Toolbox
from ..schemas.failed_jobs import FailedJobRead

router = APIRouter(prefix="/organizations/{organization_id}/failed-jobs", tags=["failed-jobs"])


@router.get("", response_model=list[FailedJobRead])
async def list_failed_jobs(
    organization_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    session: AsyncSession = Depends(get_session),
) -> list[FailedJobRead]:
    """Second cross-entity aggregation endpoint in this app (after the
    Dashboard). Failure detection can't be uniform across job types:
    `Design`/`InsertDesign` have a real `status` column, but plate STL
    failures live inside `DrawerLayout.layout_json["plates"][i]["status"]`
    -- `DrawerLayout.status` itself has no 'failed' value at all. Unions a
    simple query each for the first two, plus an app-side walk of the third.
    """
    failed_designs = list(
        await session.scalars(
            select(Design).where(Design.organization_id == organization_id, Design.status == "failed")
        )
    )
    failed_inserts = list(
        await session.scalars(
            select(InsertDesign).where(
                InsertDesign.organization_id == organization_id, InsertDesign.status == "failed"
            )
        )
    )
    layout_rows = (
        await session.execute(
            select(DrawerLayout, Shop.id, Toolbox.id, Drawer.id)
            .join(Drawer, DrawerLayout.drawer_id == Drawer.id)
            .join(Toolbox, Drawer.toolbox_id == Toolbox.id)
            .join(Shop, Toolbox.shop_id == Shop.id)
            .where(Shop.organization_id == organization_id)
        )
    ).all()

    results: list[FailedJobRead] = []

    for design in failed_designs:
        results.append(
            FailedJobRead(
                kind="label",
                id=str(design.id),
                name=design.name,
                error_message=design.error_message,
                failed_at=design.updated_at,
                link=f"/label-designer/{design.id}",
            )
        )

    for insert_design in failed_inserts:
        results.append(
            FailedJobRead(
                kind="insert",
                id=str(insert_design.id),
                name=insert_design.name,
                error_message=insert_design.error_message,
                failed_at=insert_design.updated_at,
                link=f"/inserts/{insert_design.id}",
            )
        )

    for layout, shop_id, toolbox_id, drawer_id in layout_rows:
        for plate in (layout.layout_json or {}).get("plates", []):
            if plate.get("status") != "failed":
                continue
            plate_index = plate.get("plate_index")
            results.append(
                FailedJobRead(
                    kind="plate",
                    id=f"{layout.id}:{plate_index}",
                    name=f"Plate {plate_index} (export)",
                    error_message=plate.get("error_message"),
                    failed_at=layout.updated_at,
                    link=f"/shops/{shop_id}/toolboxes/{toolbox_id}/drawers/{drawer_id}",
                )
            )

    results.sort(key=lambda job: job.failed_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return results
