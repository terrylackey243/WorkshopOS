from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Timestamped, UUIDPk

# `DrawerLayout`/`InsertPlacement` remain schema-only stubs reserved for the
# future auto-layout/packing phase. `InsertDesign` graduated out of stub
# status in M3 Phase 1 (Gridfinity Bin Generator) -- see
# `workshop_geometry.bin_engine` and `app/routers/insert_designs.py`.


class InsertDesign(UUIDPk, Timestamped, Base):
    __tablename__ = "insert_designs"
    __table_args__ = (
        CheckConstraint("source IN ('upload', 'tooltrace', 'generated')", name="ck_insert_design_source"),
        CheckConstraint("status IN ('draft', 'queued', 'generated', 'failed')", name="ck_insert_design_status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stl_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Computed footprint metadata (`{width_mm, depth_mm, height_mm}`) -- kept
    # separate from the full `parameters_json` snapshot below so the future
    # packing phase can read footprint dimensions uniformly regardless of
    # whether a row came from generation or (later) upload/import.
    bounds_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Generation pipeline fields, mirroring `Design` (M2) -- see
    # `app/services/bin_params.py` and `app/workers/tasks.py::generate_bin_design`.
    parameters_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DrawerLayout(UUIDPk, Timestamped, Base):
    __tablename__ = "drawer_layouts"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'computed', 'exported')", name="ck_drawer_layout_status"),
    )

    drawer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    layout_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    printer_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("printer_profiles.id"), nullable=True
    )


class InsertPlacement(UUIDPk, Timestamped, Base):
    __tablename__ = "insert_placements"

    drawer_layout_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawer_layouts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    insert_design_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("insert_designs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    x_mm: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False, default=Decimal("0"))
    y_mm: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False, default=Decimal("0"))
    rotation_deg: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=Decimal("0"))
