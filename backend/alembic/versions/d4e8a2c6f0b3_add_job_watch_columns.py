"""add the watched-job columns and the manual_override attempt outcome

Revision ID: d4e8a2c6f0b3
Revises: c5f1a7e3b9d2
Create Date: 2026-10-30 12:00:00.000000

v63: `jobs.watch_interval_hours` (null = not watched), `jobs.last_expanded_at` and
`jobs.next_expand_at`, with a partial index for beat's watched-job selection, plus the
`manual_override` value of `track_attempt_outcome` (an admin's "retry failed" including
not-found tracks). Additive only: three nullable columns, an index and an enum value; no
existing row is rewritten.

downgrade() maps any `manual_override` row to `held` (the other outcome that never touched
the network, so the tracks' counters stay right) before it recreates the type without it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e8a2c6f0b3'
down_revision: Union[str, Sequence[str], None] = 'c5f1a7e3b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nothing here uses the new value, but it runs on its own all the same, as a35c0e1f7b21's.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE track_attempt_outcome ADD VALUE IF NOT EXISTS 'manual_override'")
    op.add_column('jobs', sa.Column('watch_interval_hours', sa.Integer(), nullable=True))
    op.add_column('jobs', sa.Column('last_expanded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('jobs', sa.Column('next_expand_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        'ix_jobs_next_expand_at_watched',
        'jobs',
        ['next_expand_at'],
        postgresql_where=sa.text('watch_interval_hours IS NOT NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_jobs_next_expand_at_watched', table_name='jobs')
    op.drop_column('jobs', 'next_expand_at')
    op.drop_column('jobs', 'last_expanded_at')
    op.drop_column('jobs', 'watch_interval_hours')
    # Postgres has no DROP VALUE: recreate the type without it (a35c0e1f7b21's technique).
    op.execute("UPDATE track_attempts SET outcome = 'held' WHERE outcome = 'manual_override'")
    op.execute("ALTER TYPE track_attempt_outcome RENAME TO track_attempt_outcome_old")
    op.execute(
        "CREATE TYPE track_attempt_outcome AS ENUM "
        "('completed', 'failed', 'cancelled', 'skipped_duplicate', 'held')"
    )
    op.execute(
        "ALTER TABLE track_attempts ALTER COLUMN outcome "
        "TYPE track_attempt_outcome USING outcome::text::track_attempt_outcome"
    )
    op.execute("DROP TYPE track_attempt_outcome_old")
