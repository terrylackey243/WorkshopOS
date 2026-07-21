"""design error_message

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-15

Adds a nullable `error_message` column to `designs`, surfacing why a rare
worker-side CSG failure happened (the geometry engine's ValueErrors are
already user-actionable messages, e.g. "Label is too narrow for the
requested magnet supports").
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("designs", sa.Column("error_message", sa.String(2000), nullable=True))


def downgrade() -> None:
    op.drop_column("designs", "error_message")
