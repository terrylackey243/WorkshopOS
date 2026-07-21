from __future__ import annotations

from sqlalchemy import CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Timestamped, UUIDPk


class RoadmapItem(UUIDPk, Timestamped, Base):
    """A single entry on the product roadmap.

    Deliberately NOT organization-scoped -- this tracks WorkshopOS's own
    development progress (a product roadmap), not per-tenant user data, so
    every authenticated user sees the same shared list. `position` is a
    plain integer used for manual ordering (see the router's move-up/
    move-down actions) rather than timestamp-based ordering, since the user
    explicitly wants to insert/rearrange items over time independent of
    when they were created.
    """

    __tablename__ = "roadmap_items"
    __table_args__ = (CheckConstraint("status IN ('planned', 'in_progress', 'done')", name="ck_roadmap_item_status"),)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    position: Mapped[int] = mapped_column(Integer, nullable=False)
