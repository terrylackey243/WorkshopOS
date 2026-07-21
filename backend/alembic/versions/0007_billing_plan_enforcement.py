"""billing / plan enforcement

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-16

Finalizes the pricing tier limits (locked-in table below) and adds the two
upgrade mechanisms for the two distribution channels: a self-hosted
Ed25519-signed license key, and a SaaS Stripe subscription.

Locked-in tier table (this migration changes existing seed data, not just
additive -- see the plan doc's Context section for the full rationale):

    |            | Free | Pro       | Enterprise |
    |------------|------|-----------|------------|
    | Shops      | 1    | 1         | Unlimited  |
    | Toolboxes  | 1    | Unlimited | Unlimited  |
    | Drawers    | 10   | Unlimited | Unlimited  |
    | Tools      | 100  | Unlimited | Unlimited  |
    | Users      | 1    | Unlimited | Unlimited  |

`max_users` stays unenforced at the API layer (no invite/member-creation
flow exists yet -- separate roadmap item) but is still seeded here for
schema completeness / future use.

`Plan.stripe_price_id` stays NULL for all three plans after this migration --
Free is never purchasable, and Pro/Enterprise need real Stripe test-mode
Price IDs pasted in by hand (`UPDATE plans SET stripe_price_id = ...`) after
creating the corresponding Products/Prices, which this migration can't know
in advance.

Retroactive impact, stated explicitly: Free's `max_drawers` 5->10 only
loosens (no risk). Pro's `max_shops` unlimited->1 tightens --
`enforce_plan_limit` only runs on *create*, so any existing dev org with 2+
shops on Pro isn't blocked/deleted, it just can't add a third. Pre-launch,
no real customers -- safe to just spot-check local data after migrating.
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FREE_PLAN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
PRO_PLAN_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
ENTERPRISE_PLAN_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


def upgrade() -> None:
    op.add_column("plans", sa.Column("max_tools", sa.Integer(), nullable=True))
    op.add_column("plans", sa.Column("stripe_price_id", sa.String(255), nullable=True))

    op.add_column("organizations", sa.Column("license_key", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("license_tier", sa.String(50), nullable=True))
    op.add_column(
        "organizations", sa.Column("license_activated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("organizations", sa.Column("stripe_customer_id", sa.String(255), nullable=True))
    op.add_column("organizations", sa.Column("stripe_subscription_id", sa.String(255), nullable=True))
    op.create_unique_constraint(
        "uq_organizations_stripe_customer_id", "organizations", ["stripe_customer_id"]
    )

    plans_table = sa.table(
        "plans",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("key", sa.String),
        sa.column("name", sa.String),
        sa.column("max_shops", sa.Integer),
        sa.column("max_toolboxes", sa.Integer),
        sa.column("max_drawers", sa.Integer),
        sa.column("max_tools", sa.Integer),
        sa.column("max_users", sa.Integer),
    )

    op.execute(
        plans_table.update()
        .where(plans_table.c.id == FREE_PLAN_ID)
        .values(max_shops=1, max_toolboxes=1, max_drawers=10, max_tools=100, max_users=1)
    )
    op.execute(
        plans_table.update()
        .where(plans_table.c.id == PRO_PLAN_ID)
        .values(max_shops=1, max_toolboxes=None, max_drawers=None, max_tools=None, max_users=None)
    )

    op.bulk_insert(
        plans_table,
        [
            {
                "id": ENTERPRISE_PLAN_ID,
                "key": "enterprise",
                "name": "Enterprise",
                "max_shops": None,
                "max_toolboxes": None,
                "max_drawers": None,
                "max_tools": None,
                "max_users": None,
            },
        ],
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM plans WHERE id = :id").bindparams(id=str(ENTERPRISE_PLAN_ID)))

    op.execute(
        sa.text(
            "UPDATE plans SET max_shops = 1, max_toolboxes = 1, max_drawers = 5, max_users = 1 "
            "WHERE id = :id"
        ).bindparams(id=str(FREE_PLAN_ID))
    )
    op.execute(
        sa.text(
            "UPDATE plans SET max_shops = NULL, max_toolboxes = NULL, max_drawers = NULL, max_users = NULL "
            "WHERE id = :id"
        ).bindparams(id=str(PRO_PLAN_ID))
    )

    op.drop_constraint("uq_organizations_stripe_customer_id", "organizations", type_="unique")
    op.drop_column("organizations", "stripe_subscription_id")
    op.drop_column("organizations", "stripe_customer_id")
    op.drop_column("organizations", "license_activated_at")
    op.drop_column("organizations", "license_tier")
    op.drop_column("organizations", "license_key")

    op.drop_column("plans", "stripe_price_id")
    op.drop_column("plans", "max_tools")
