"""tool maintenance reminders

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-21

Adds Tool.maintenance_interval_days/last_maintained_at. A single
interval/last-done pair per tool, not a separate reminder-type table --
kept simple, matches the plan's explicit scope limit. See
app/routers/tools.py's mark-maintenance-done endpoint and
app/routers/dashboard.py's maintenance_due bucket.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tools", sa.Column("maintenance_interval_days", sa.Integer(), nullable=True))
    op.add_column("tools", sa.Column("last_maintained_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tools", "last_maintained_at")
    op.drop_column("tools", "maintenance_interval_days")
