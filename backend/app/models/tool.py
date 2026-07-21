from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Timestamped, UUIDPk


class Tool(UUIDPk, Timestamped, Base):
    __tablename__ = "tools"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    drawer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drawers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    insert_design_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("insert_designs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Meaningful only when `insert_design_id` is set: how many insert slots
    # this tool needs in a generated drawer layout (independent of
    # `quantity`, the total owned). Defaulted to 1 and validated
    # (0 <= insert_quantity <= quantity) at the API layer -- see
    # app/routers/tools.py.
    insert_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Absolute on-disk path to the uploaded photo, same
    # `{generated_files_dir}/{org_id}/{entity_id}/...` convention as every
    # other uploaded/generated file in this app. Never exposed directly to
    # the client (see ToolRead.has_photo) -- only served via the dedicated
    # /tools/{id}/photo endpoint.
    photo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Checkout / loan tracking. `checked_out_to` is free text (no real
    # multi-user support exists yet -- Member invites is a separate,
    # still-unbuilt roadmap item -- so this can't be a User FK). All three
    # fields are set/cleared together via the dedicated checkout/return
    # endpoints in app/routers/tools.py, never via plain PATCH, so an
    # inconsistent state (e.g. checked_out_at set but checked_out_to blank)
    # can't happen.
    checked_out_to: Mapped[str | None] = mapped_column(String(200), nullable=True)
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checkout_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Maintenance reminders. A single interval/last-done pair, not a
    # separate multi-reminder-type table (see the plan's explicit scope
    # limit) -- `maintenance_interval_days` is a plain field (updatable via
    # normal PATCH), `last_maintained_at` is only ever set by the dedicated
    # mark-done endpoint in app/routers/tools.py.
    maintenance_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_maintained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
