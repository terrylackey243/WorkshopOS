from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Timestamped, UUIDPk


class Shop(UUIDPk, Timestamped, Base):
    __tablename__ = "shops"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_shop_org_slug"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)


class Toolbox(UUIDPk, Timestamped, Base):
    __tablename__ = "toolboxes"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class Drawer(UUIDPk, Timestamped, Base):
    """Physical drawer instance living in a toolbox, sized via a DrawerProfile preset."""

    __tablename__ = "drawers"

    toolbox_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("toolboxes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    drawer_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawer_profiles.id"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    position_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_in_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
