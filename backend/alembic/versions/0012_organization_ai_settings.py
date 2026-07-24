"""organization AI import settings

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-23

Adds Organization.anthropic_api_key_ciphertext (BYOK: each org supplies its
own Anthropic API key for the AI Import feature, encrypted at rest via
app/services/crypto.py -- WorkshopOS never stores or proxies the plaintext
key). See app/routers/ai_import.py.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("anthropic_api_key_ciphertext", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "anthropic_api_key_ciphertext")
