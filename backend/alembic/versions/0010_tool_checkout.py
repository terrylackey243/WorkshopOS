"""tool checkout tracking

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-21

Adds Tool.checked_out_to/checked_out_at/checkout_due_at. `checked_out_to`
is free text, not a User FK -- no real multi-user support exists yet
(Member invites is a separate, still-unbuilt roadmap item). See
app/routers/tools.py's checkout/return endpoints.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tools", sa.Column("checked_out_to", sa.String(200), nullable=True))
    op.add_column("tools", sa.Column("checked_out_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tools", sa.Column("checkout_due_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tools", "checkout_due_at")
    op.drop_column("tools", "checked_out_at")
    op.drop_column("tools", "checked_out_to")
