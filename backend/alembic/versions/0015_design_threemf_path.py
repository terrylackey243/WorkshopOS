"""design threemf path

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-29

Adds Design.threemf_path, the combined per-object-colored outline+text 3MF
now written by the worker directly from the in-memory CSG result alongside
the STL pair (see workshop_geometry.label_engine.export_label). Replaces an
earlier on-demand approach that reconstructed the 3MF by re-loading the STL
files back off disk -- that round-trip was confirmed (via a slicer that
rejected the result, and independently reproduced here) to silently
introduce duplicate reversed-winding faces from STL's lossy 32-bit floats,
breaking manifoldness for meshes that were provably watertight beforehand.
NULL for every design generated before this migration; they'll get a value
next time they're edited or regenerated.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("designs", sa.Column("threemf_path", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("designs", "threemf_path")
