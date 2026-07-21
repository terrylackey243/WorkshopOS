"""design tool link + qr stl path

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-17

Adds `Design.tool_id` (optional link to a Tool, so a label can encode a QR
code deep-linking to that tool's page) and `Design.qr_stl_path` (the third
generated body, alongside outline/text, produced only when `tool_id` is
set). See `app/routers/designs.py` and
`workshop_geometry.label_engine::_qr_geometry`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "designs",
        sa.Column("tool_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tools.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_designs_tool_id", "designs", ["tool_id"])
    op.add_column("designs", sa.Column("qr_stl_path", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("designs", "qr_stl_path")
    op.drop_index("ix_designs_tool_id", table_name="designs")
    op.drop_column("designs", "tool_id")
