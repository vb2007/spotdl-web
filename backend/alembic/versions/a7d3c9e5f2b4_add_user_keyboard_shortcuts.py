"""user_settings keyboard shortcuts preference

Revision ID: a7d3c9e5f2b4
Revises: c4e8a2f1d9b7
Create Date: 2026-10-18 12:00:00.000000

v45: the per-user off switch for single-character keyboard shortcuts (WCAG 2.1.4). Additive
only: the column has a server_default of true, so every existing settings row reads "on" and no
data is rewritten.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d3c9e5f2b4'
down_revision: Union[str, Sequence[str], None] = 'c4e8a2f1d9b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'user_settings',
        sa.Column('keyboard_shortcuts', sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_settings', 'keyboard_shortcuts')
