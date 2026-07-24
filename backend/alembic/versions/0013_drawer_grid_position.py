"""drawer grid position

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-24

Adds Drawer.row/order_in_row, used to render a toolbox's front-view layout
visualization (drawers grouped by physical row, split left-to-right within
a row). Additive to the existing free-text `position_label`, which is left
untouched and keeps its role as a human display label elsewhere in the app.
See app/routers/drawers.py's list ordering and move-left/move-right
endpoints.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("drawers", sa.Column("row", sa.Integer(), nullable=True))
    op.add_column("drawers", sa.Column("order_in_row", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("drawers", "order_in_row")
    op.drop_column("drawers", "row")
