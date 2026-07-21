from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from .base import ORMModel


class InsertPlacementRead(ORMModel):
    id: uuid.UUID
    insert_design_id: uuid.UUID
    x_mm: Decimal
    y_mm: Decimal
    rotation_deg: Decimal


class DrawerLayoutRead(ORMModel):
    id: uuid.UUID
    drawer_id: uuid.UUID
    status: str
    layout_json: dict | None
    printer_profile_id: uuid.UUID | None
    created_at: datetime
    placements: list[InsertPlacementRead]


class ExportLayoutCreate(ORMModel):
    printer_profile_id: uuid.UUID
