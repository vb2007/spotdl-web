"""user_settings language preference

Revision ID: b8e4d1f6a3c7
Revises: a7d3c9e5f2b4
Create Date: 2026-10-18 18:00:00.000000

v46: the per-user interface language. Additive only: NULL means "no saved preference" (the
browser's language decides), so every existing settings row keeps today's behavior and no data
is rewritten. A plain string, not a native enum: the allowed values are checked at the API
(`hu`/`en`), and adding a language later needs no type swap.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e4d1f6a3c7'
down_revision: Union[str, Sequence[str], None] = 'a7d3c9e5f2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user_settings', sa.Column('language', sa.String(length=8), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_settings', 'language')
