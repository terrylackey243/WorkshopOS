from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Timestamped, UUIDPk


class Design(UUIDPk, Timestamped, Base):
    """A generated (or queued-to-generate) label design.

    Schema + migration only in M1 -- no router yet. `parameters_json` stores a
    full `LabelParameters` snapshot; `engine_version`/`content_hash` map
    directly onto `generation_manifest()["engine_version"]` and
    `parameter_checksum_sha256` from workshop_geometry.label_engine.
    """

    __tablename__ = "designs"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'queued', 'generated', 'failed')", name="ck_design_status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shop_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Optional link to a specific Tool -- when set, generation also produces
    # a QR-code body (qr_stl_path) encoding a deep link to that tool's page.
    # Unlinked labels (the common case) are unaffected; existing behavior
    # unchanged. See workshop_geometry.label_engine's `_qr_geometry`.
    tool_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tools.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    label_style_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("label_style_profiles.id"), nullable=True
    )
    magnet_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("magnet_profiles.id"), nullable=True
    )
    parameters_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(50), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    outline_stl_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    text_stl_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    qr_stl_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Combined, per-object-colored outline+text 3MF -- written by the worker
    # directly from the in-memory CSG result alongside the STL pair (see
    # workshop_geometry.label_engine.export_label), not reconstructed later
    # from the STL files: re-loading STL's lossy 32-bit-float geometry was
    # confirmed to silently introduce duplicate reversed-winding faces that
    # break manifoldness, which stricter 3MF readers (e.g. some printer
    # manufacturers' bundled slicers) reject outright.
    threemf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
