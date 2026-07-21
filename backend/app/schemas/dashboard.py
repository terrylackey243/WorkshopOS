from __future__ import annotations

from pydantic import BaseModel

from .tool import ToolRead


class DashboardRead(BaseModel):
    overdue_checkouts: list[ToolRead]
    active_checkouts: list[ToolRead]
    maintenance_due: list[ToolRead]
