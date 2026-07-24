from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Timestamped, UUIDPk

# Fixed, well-known IDs for the three seeded plans so the migration's bulk_insert
# and the ORM-side default on Organization.plan_id agree without a lookup.
FREE_PLAN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
PRO_PLAN_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
ENTERPRISE_PLAN_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


class Plan(UUIDPk, Timestamped, Base):
    __tablename__ = "plans"

    key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    max_shops: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_toolboxes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_drawers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tools: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # NULL for Free (never purchasable); Pro/Enterprise get real Stripe
    # test-mode Price IDs pasted in by hand post-migration (see 0007's
    # docstring) -- the migration can't know these in advance.
    stripe_price_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Organization(UUIDPk, Timestamped, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id"), nullable=False, default=FREE_PLAN_ID
    )
    # Self-hosted license-activation fields. `license_key` is the raw
    # activated JWT (kept for support/debugging visibility); `license_tier`
    # is what the license CLAIMS, kept distinct from `plan_id` since
    # `plan_id` is also the Stripe-sync field on SaaS orgs.
    license_key: Mapped[str | None] = mapped_column(String, nullable=True)
    license_tier: Mapped[str | None] = mapped_column(String(50), nullable=True)
    license_activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # SaaS/Stripe-sync fields. `stripe_customer_id` is unique+nullable
    # (Postgres allows multiple NULLs under a unique constraint) so
    # `billing.py` can reuse the same Stripe Customer across repeat checkout
    # attempts, and webhook handlers can look the org up (webhooks carry no
    # org-scoped URL).
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # AI Import (see app/routers/ai_import.py): the org's own Anthropic API
    # key (BYOK -- WorkshopOS never pays for or proxies these calls),
    # Fernet-encrypted via app/services/crypto.py. Never the plaintext key.
    anthropic_api_key_ciphertext: Mapped[str | None] = mapped_column(String, nullable=True)


class User(UUIDPk, Timestamped, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Membership(UUIDPk, Timestamped, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
        CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_membership_role"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="owner")
