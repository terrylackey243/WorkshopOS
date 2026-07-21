"""tool photo

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-17

Adds `Tool.photo_path` -- absolute on-disk path to an uploaded photo, same
`{generated_files_dir}/{org_id}/{entity_id}/...` convention as every other
uploaded/generated file in this app. See `app/routers/tools.py`'s
`upload_tool_photo`/`delete_tool_photo`/`get_tool_photo`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tools",
        sa.Column("photo_path", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tools", "photo_path")
