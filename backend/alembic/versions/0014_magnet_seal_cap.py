"""magnet seal cap

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-27

Adds MagnetProfile.seal_cap_mm for the new "sealed" fit_type -- a
print-in-place magnet embedding workflow (pause mid-print, drop the magnet
in, resume) where the pocket gets capped with this much solid material
instead of staying open for gluing afterward. NULL for every existing
profile (all currently "glue"), which is exactly the open-pocket behavior
they already have -- see label_engine.py's MagnetPocketParameters.seal_cap_mm
defaulting to 0.0 when absent.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("magnet_profiles", sa.Column("seal_cap_mm", sa.Numeric(6, 3), nullable=True))


def downgrade() -> None:
    op.drop_column("magnet_profiles", "seal_cap_mm")
