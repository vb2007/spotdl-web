"""track_attempts.hold_count

Revision ID: d9b3e5f7a1c2
Revises: a7c4e1b9d2f5
Create Date: 2026-10-26 00:00:00.000000

v55 (E11): consecutive holds of one track (the breaker, a pause, an unmounted library root)
collapse into one `held` row whose finished_at and hold_count advance, instead of a row per
hold (about 460 in production's 2026-10-18 trip). Additive: every existing row reads
hold_count 1, and existing runs of `held` rows are left as they are.

v55 (E10): a `lookup_failed` track's leftover scheduled_at (from an earlier ladder failure)
is cleared, as retry.record_failure now does on the verdict. This rewrites data (that one
column, only on terminal rows, where nothing reads it), covered by the deploy's pre-migrate
pg_backup. downgrade() can't restore the old values and leaves them NULL, which every
reader already treated as "no retry"; it drops hold_count, so a collapsed hold reads as one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9b3e5f7a1c2'
down_revision: Union[str, Sequence[str], None] = 'a7c4e1b9d2f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'track_attempts',
        sa.Column('hold_count', sa.Integer(), nullable=False, server_default='1'),
    )
    op.execute(
        "UPDATE tracks SET scheduled_at = NULL "
        "WHERE state = 'lookup_failed' AND scheduled_at IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('track_attempts', 'hold_count')
