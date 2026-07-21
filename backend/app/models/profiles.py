from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, ProfileBase


class DrawerProfile(ProfileBase, Base):
    """Reusable drawer dimension preset (not a physical instance -- see Drawer)."""

    __tablename__ = "drawer_profiles"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_drawer_profile_org_name"),)

    inside_width_mm: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    inside_depth_mm: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    inside_height_mm: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    grid_unit_mm: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("42"))


class PrinterProfile(ProfileBase, Base):
    __tablename__ = "printer_profiles"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_printer_profile_org_name"),)

    manufacturer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    build_width_mm: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    build_depth_mm: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    build_height_mm: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    nozzle_diameter_mm: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("0.4"))
    usable_margin_mm: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("2.0"))


class MagnetProfile(ProfileBase, Base):
    __tablename__ = "magnet_profiles"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_magnet_profile_org_name"),)

    diameter_mm: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    thickness_mm: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    diameter_clearance_mm: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("0.2"))
    depth_clearance_mm: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("0.2"))
    fit_type: Mapped[str] = mapped_column(String(30), nullable=False, default="glue")


class MaterialProfile(ProfileBase, Base):
    __tablename__ = "material_profiles"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_material_profile_org_name"),)

    material_type: Mapped[str] = mapped_column(String(50), nullable=False)
    xy_compensation_mm: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("0"))
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class LabelStyleProfile(ProfileBase, Base):
    """Mirrors LabelParameters / the layout half of MagnetPocketParameters from label_engine.py."""

    __tablename__ = "label_style_profiles"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_label_style_profile_org_name"),)

    text_height_mm: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("15.843"))
    body_depth_mm: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("4.55"))
    outline_offset_mm: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("1.25"))
    font_family: Mapped[str] = mapped_column(String(200), nullable=False, default="DejaVu Sans")
    font_weight: Mapped[str] = mapped_column(String(30), nullable=False, default="bold")
    font_style: Mapped[str] = mapped_column(String(30), nullable=False, default="italic")
    horizontal_scale: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("1.0"))
    minimum_width_mm: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False, default=Decimal("24.0"))
    fixed_width_mm: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    magnet_count: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    magnet_edge_offset_mm: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("8.0"))
    magnet_minimum_bridge_mm: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("0.6"))
    magnet_support_extra_mm: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False, default=Decimal("0.0"))
    default_magnet_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("magnet_profiles.id"), nullable=True
    )
