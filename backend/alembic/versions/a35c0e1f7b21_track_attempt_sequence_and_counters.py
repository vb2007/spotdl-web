"""track_attempts: per-track attempt_number sequence, `held` outcome, track counters

Revision ID: a35c0e1f7b21
Revises: e7c1f9a4d2b6
Create Date: 2026-10-02 00:00:00.000000

v35 (a). Rewrites data on existing rows, so a pre-deploy pg_backup is required:
- breaker-hold rows (stored as `failed` with download.py's fixed hold message) become
  outcome `held`;
- attempt_number is renumbered 1..n per track in started_at order, then made unique;
- tracks.attempts_made / failure_count are added and backfilled from those rows.

downgrade() reverts the schema and maps `held` back to `failed`. The renumbered
attempt_number values stay as they are: the v24 numbering mirrored a counter that no longer
exists per row, so it can't be reconstructed, and the new values are still valid integers.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a35c0e1f7b21'
down_revision: Union[str, Sequence[str], None] = 'e7c1f9a4d2b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The exact message download.py has written on every breaker-hold row since v24.
_HOLD_MESSAGE = 'circuit breaker active; rescheduled without attempting'


def upgrade() -> None:
    """Upgrade schema."""
    # ALTER TYPE ... ADD VALUE can't share a transaction with a statement that uses the
    # new value, and the UPDATE below does -- so it runs (and commits) on its own first.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE track_attempt_outcome ADD VALUE IF NOT EXISTS 'held'")

    op.execute(
        sa.text(
            "UPDATE track_attempts SET outcome = 'held' "
            "WHERE outcome = 'failed' AND network_path IS NULL AND error_message = :msg"
        ).bindparams(msg=_HOLD_MESSAGE)
    )

    op.drop_index('ix_track_attempts_track_id_attempt_number', table_name='track_attempts')
    op.execute(
        """
        UPDATE track_attempts AS ta SET attempt_number = numbered.n
        FROM (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY track_id ORDER BY started_at, created_at, id
            ) AS n
            FROM track_attempts
        ) AS numbered
        WHERE ta.id = numbered.id
        """
    )
    op.create_unique_constraint(
        'uq_track_attempts_track_id_attempt_number',
        'track_attempts',
        ['track_id', 'attempt_number'],
    )

    op.add_column(
        'tracks',
        sa.Column('attempts_made', sa.Integer(), server_default='0', nullable=False),
    )
    op.add_column(
        'tracks',
        sa.Column('failure_count', sa.Integer(), server_default='0', nullable=False),
    )
    # Same rule as attempts.record_attempt: completed/failed always tried the network, a
    # cancelled row only when it carries a network_path (cancelled mid-download).
    op.execute(
        """
        UPDATE tracks AS t SET
            attempts_made = agg.attempts_made,
            failure_count = agg.failure_count
        FROM (
            SELECT
                track_id,
                COUNT(*) FILTER (
                    WHERE outcome IN ('completed', 'failed')
                       OR (outcome = 'cancelled' AND network_path IS NOT NULL)
                ) AS attempts_made,
                COUNT(*) FILTER (WHERE outcome = 'failed') AS failure_count
            FROM track_attempts
            GROUP BY track_id
        ) AS agg
        WHERE t.id = agg.track_id
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tracks', 'failure_count')
    op.drop_column('tracks', 'attempts_made')
    op.drop_constraint(
        'uq_track_attempts_track_id_attempt_number', 'track_attempts', type_='unique'
    )
    op.create_index(
        'ix_track_attempts_track_id_attempt_number',
        'track_attempts',
        ['track_id', 'attempt_number'],
        unique=False,
    )
    # Postgres has no DROP VALUE -- recreate the type without 'held' (same technique as
    # 46be30064f8b's downgrade), after mapping held rows back to how v24 stored them.
    op.execute("UPDATE track_attempts SET outcome = 'failed' WHERE outcome = 'held'")
    op.execute("ALTER TYPE track_attempt_outcome RENAME TO track_attempt_outcome_old")
    op.execute(
        "CREATE TYPE track_attempt_outcome AS ENUM "
        "('completed', 'failed', 'cancelled', 'skipped_duplicate')"
    )
    op.execute(
        "ALTER TABLE track_attempts ALTER COLUMN outcome TYPE track_attempt_outcome "
        "USING outcome::text::track_attempt_outcome"
    )
    op.execute("DROP TYPE track_attempt_outcome_old")
