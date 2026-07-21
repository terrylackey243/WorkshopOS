"""tool insert quantity

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-16

Adds `Tool.insert_quantity` -- how many insert slots this tool needs in a
generated drawer layout, independent of `quantity` (total owned). Meaningful
only when `insert_design_id` is set; defaulted to 1 and validated
(0 <= insert_quantity <= quantity) at the API layer (see
`app/routers/tools.py`), not via a DB-level default or check constraint.
This is the last prerequisite for M3 Phase 3 (drawer auto-layout / packing) --
see `app/services/drawer_layout.py` and `app/routers/drawer_layouts.py`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tools",
        sa.Column("insert_quantity", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tools", "insert_quantity")
