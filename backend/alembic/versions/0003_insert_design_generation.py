"""insert design generation

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-15

Turns `insert_designs` from the M1 schema-only stub into a real generation
target, mirroring `designs`' M2 shape: `status`/`error_message`/
`parameters_json`/`engine_version`/`content_hash`/`generated_at`. Unlike
`designs`, `parameters_json` stays nullable here -- it's null for the future
`upload`/`tooltrace` sources (this phase only ever populates it for
`source="generated"` rows). The pre-existing `bounds_json` column is
repurposed (not touched by this migration -- no schema change needed) as
computed footprint metadata (`{width_mm, depth_mm, height_mm}`) so the future
packing phase can read footprint dimensions uniformly regardless of source.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "insert_designs",
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
    )
    op.add_column("insert_designs", sa.Column("error_message", sa.String(2000), nullable=True))
    op.add_column("insert_designs", sa.Column("parameters_json", postgresql.JSONB(), nullable=True))
    op.add_column("insert_designs", sa.Column("engine_version", sa.String(50), nullable=True))
    op.add_column("insert_designs", sa.Column("content_hash", sa.String(64), nullable=True))
    op.add_column(
        "insert_designs", sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_insert_design_status",
        "insert_designs",
        "status IN ('draft', 'queued', 'generated', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_insert_design_status", "insert_designs", type_="check")
    op.drop_column("insert_designs", "generated_at")
    op.drop_column("insert_designs", "content_hash")
    op.drop_column("insert_designs", "engine_version")
    op.drop_column("insert_designs", "parameters_json")
    op.drop_column("insert_designs", "error_message")
    op.drop_column("insert_designs", "status")
