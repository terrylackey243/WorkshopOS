"""tool insert design linkage

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-16

Links a Tool to the InsertDesign (STL) that holds it -- the prerequisite the
user identified before drawer auto-layout can work: layout generation needs
to know which insert geometry belongs to which tool in a drawer's tool list.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tools",
        sa.Column("insert_design_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tools_insert_design_id",
        "tools",
        "insert_designs",
        ["insert_design_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tools_insert_design_id", "tools", ["insert_design_id"])


def downgrade() -> None:
    op.drop_index("ix_tools_insert_design_id", table_name="tools")
    op.drop_constraint("fk_tools_insert_design_id", "tools", type_="foreignkey")
    op.drop_column("tools", "insert_design_id")
