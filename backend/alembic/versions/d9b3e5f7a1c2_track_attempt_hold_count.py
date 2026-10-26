"""track_attempts.hold_count

Revision ID: d9b3e5f7a1c2
Revises: f6b2d8e4a1c9
Create Date: 2026-10-26 00:00:00.000000

v55 (E11): consecutive holds of one track (the breaker, a pause, an unmounted library root)
collapse into one `held` row whose finished_at and hold_count advance, instead of a row per
hold (about 460 in production's 2026-10-18 trip). Additive only: every existing row reads
hold_count 1, and existing runs of `held` rows are left as they are (no data rewrite).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9b3e5f7a1c2'
down_revision: Union[str, Sequence[str], None] = 'f6b2d8e4a1c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'track_attempts',
        sa.Column('hold_count', sa.Integer(), nullable=False, server_default='1'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('track_attempts', 'hold_count')
