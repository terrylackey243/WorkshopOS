from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from .base import ORMModel

# NOTE: none of these Create schemas accept `organization_id` from the client.
# The generic profile CRUD engine in app/routers/profiles.py sources it from
# the authenticated `get_current_membership` dependency instead -- this is
# the fix for the old codebase's client-supplied `organization_id` vulnerability.


class ProfileUpdateBase(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_default: bool | None = None


# --- Printer -----------------------------------------------------------------


class PrinterProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    manufacturer: str | None = None
    model: str | None = None
    build_width_mm: Decimal = Field(gt=0)
    build_depth_mm: Decimal = Field(gt=0)
    build_height_mm: Decimal = Field(gt=0)
    nozzle_diameter_mm: Decimal = Field(default=Decimal("0.4"), gt=0)
    usable_margin_mm: Decimal = Field(default=Decimal("2.0"), ge=0)
    is_default: bool = False


class PrinterProfileUpdate(ProfileUpdateBase):
    manufacturer: str | None = None
    model: str | None = None
    build_width_mm: Decimal | None = Field(default=None, gt=0)
    build_depth_mm: Decimal | None = Field(default=None, gt=0)
    build_height_mm: Decimal | None = Field(default=None, gt=0)
    nozzle_diameter_mm: Decimal | None = Field(default=None, gt=0)
    usable_margin_mm: Decimal | None = Field(default=None, ge=0)


class PrinterProfileRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    manufacturer: str | None
    model: str | None
    build_width_mm: Decimal
    build_depth_mm: Decimal
    build_height_mm: Decimal
    nozzle_diameter_mm: Decimal
    usable_margin_mm: Decimal
    is_default: bool


# --- Magnet --------------------------------------------------------------------


class MagnetProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    diameter_mm: Decimal = Field(gt=0)
    thickness_mm: Decimal = Field(gt=0)
    diameter_clearance_mm: Decimal = Field(default=Decimal("0.2"), ge=0)
    depth_clearance_mm: Decimal = Field(default=Decimal("0.2"), ge=0)
    fit_type: Literal["press", "snug", "glue", "loose"] = "glue"
    is_default: bool = False


class MagnetProfileUpdate(ProfileUpdateBase):
    diameter_mm: Decimal | None = Field(default=None, gt=0)
    thickness_mm: Decimal | None = Field(default=None, gt=0)
    diameter_clearance_mm: Decimal | None = Field(default=None, ge=0)
    depth_clearance_mm: Decimal | None = Field(default=None, ge=0)
    fit_type: Literal["press", "snug", "glue", "loose"] | None = None


class MagnetProfileRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    diameter_mm: Decimal
    thickness_mm: Decimal
    diameter_clearance_mm: Decimal
    depth_clearance_mm: Decimal
    fit_type: str
    is_default: bool


# --- Material --------------------------------------------------------------------


class MaterialProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    material_type: str = Field(min_length=1, max_length=50)
    xy_compensation_mm: Decimal = Field(default=Decimal("0"), ge=Decimal("-2"), le=Decimal("2"))
    notes: str | None = None
    is_default: bool = False


class MaterialProfileUpdate(ProfileUpdateBase):
    material_type: str | None = Field(default=None, max_length=50)
    xy_compensation_mm: Decimal | None = Field(default=None, ge=Decimal("-2"), le=Decimal("2"))
    notes: str | None = None


class MaterialProfileRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    material_type: str
    xy_compensation_mm: Decimal
    notes: str | None
    is_default: bool


# --- DrawerProfile --------------------------------------------------------------------


class DrawerProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    inside_width_mm: Decimal = Field(gt=0)
    inside_depth_mm: Decimal = Field(gt=0)
    inside_height_mm: Decimal = Field(gt=0)
    grid_unit_mm: Decimal = Field(default=Decimal("42"), gt=0)
    is_default: bool = False


class DrawerProfileUpdate(ProfileUpdateBase):
    inside_width_mm: Decimal | None = Field(default=None, gt=0)
    inside_depth_mm: Decimal | None = Field(default=None, gt=0)
    inside_height_mm: Decimal | None = Field(default=None, gt=0)
    grid_unit_mm: Decimal | None = Field(default=None, gt=0)


class DrawerProfileRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    inside_width_mm: Decimal
    inside_depth_mm: Decimal
    inside_height_mm: Decimal
    grid_unit_mm: Decimal
    is_default: bool


# --- LabelStyle --------------------------------------------------------------------


class LabelStyleProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    text_height_mm: Decimal = Field(default=Decimal("15.843"), gt=0)
    body_depth_mm: Decimal = Field(default=Decimal("4.55"), gt=0)
    outline_offset_mm: Decimal = Field(default=Decimal("1.25"), gt=0)
    font_family: str = "DejaVu Sans"
    font_weight: Literal["normal", "medium", "semibold", "bold", "heavy"] = "bold"
    font_style: Literal["normal", "italic", "oblique"] = "italic"
    horizontal_scale: Decimal = Field(default=Decimal("1.0"), gt=0)
    minimum_width_mm: Decimal = Field(default=Decimal("24.0"), gt=0)
    fixed_width_mm: Decimal | None = Field(default=None, gt=0)
    magnet_count: int = Field(default=2, ge=0, le=8)
    magnet_edge_offset_mm: Decimal = Field(default=Decimal("8.0"), ge=0)
    magnet_minimum_bridge_mm: Decimal = Field(default=Decimal("0.6"), ge=0)
    magnet_support_extra_mm: Decimal = Field(default=Decimal("0.0"), ge=0)
    default_magnet_profile_id: uuid.UUID | None = None
    is_default: bool = False


class LabelStyleProfileUpdate(ProfileUpdateBase):
    text_height_mm: Decimal | None = Field(default=None, gt=0)
    body_depth_mm: Decimal | None = Field(default=None, gt=0)
    outline_offset_mm: Decimal | None = Field(default=None, gt=0)
    font_family: str | None = None
    font_weight: Literal["normal", "medium", "semibold", "bold", "heavy"] | None = None
    font_style: Literal["normal", "italic", "oblique"] | None = None
    horizontal_scale: Decimal | None = Field(default=None, gt=0)
    minimum_width_mm: Decimal | None = Field(default=None, gt=0)
    fixed_width_mm: Decimal | None = Field(default=None, gt=0)
    magnet_count: int | None = Field(default=None, ge=0, le=8)
    magnet_edge_offset_mm: Decimal | None = Field(default=None, ge=0)
    magnet_minimum_bridge_mm: Decimal | None = Field(default=None, ge=0)
    magnet_support_extra_mm: Decimal | None = Field(default=None, ge=0)
    default_magnet_profile_id: uuid.UUID | None = None


class LabelStyleProfileRead(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    text_height_mm: Decimal
    body_depth_mm: Decimal
    outline_offset_mm: Decimal
    font_family: str
    font_weight: str
    font_style: str
    horizontal_scale: Decimal
    minimum_width_mm: Decimal
    fixed_width_mm: Decimal | None
    magnet_count: int
    magnet_edge_offset_mm: Decimal
    magnet_minimum_bridge_mm: Decimal
    magnet_support_extra_mm: Decimal
    default_magnet_profile_id: uuid.UUID | None
    is_default: bool
