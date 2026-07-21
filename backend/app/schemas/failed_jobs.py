from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class FailedJobRead(BaseModel):
    kind: Literal["label", "insert", "plate"]
    id: str
    name: str
    error_message: str | None
    failed_at: datetime | None
    # Real in-app route to the relevant record, when one exists -- plate
    # failures link to the drawer that owns the layout (no dedicated plate
    # detail page exists).
    link: str | None
