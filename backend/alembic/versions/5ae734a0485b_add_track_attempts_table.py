"""add track attempts table

Revision ID: 5ae734a0485b
Revises: c1a9f0e2b3d4
Create Date: 2026-08-15 16:42:55.781216

v24: per-attempt download history. `error_type` reuses the existing `track_error_type`
enum (already owned/created by `tracks.last_error_type`) rather than declaring a second
copy -- `create_type=False` on that column is what stops this migration from trying (and
failing) to CREATE a type that already exists on a real, already-running database
(docs/GOTCHAS.md's enum gotchas). `track_attempt_outcome` is new to this table alone, so
it's created and dropped normally.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5ae734a0485b'
down_revision: Union[str, Sequence[str], None] = 'c1a9f0e2b3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'track_attempts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('track_id', sa.UUID(), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'outcome',
            sa.Enum(
                'completed', 'failed', 'cancelled', 'skipped_duplicate',
                name='track_attempt_outcome',
            ),
            nullable=False,
        ),
        sa.Column(
            'error_type',
            postgresql.ENUM(
                'audio_provider', 'lookup', 'other', 'no_output',
                name='track_error_type',
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('proxy_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id']),
        sa.ForeignKeyConstraint(['proxy_id'], ['proxies.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_track_attempts_track_id'), 'track_attempts', ['track_id'])
    op.create_index(
        'ix_track_attempts_track_id_attempt_number', 'track_attempts', ['track_id', 'attempt_number']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_track_attempts_track_id_attempt_number', table_name='track_attempts')
    op.drop_index(op.f('ix_track_attempts_track_id'), table_name='track_attempts')
    op.drop_table('track_attempts')
    # error_type's create_type=False means dropping this table never touched
    # track_error_type -- only the new outcome type is ours to drop.
    op.execute("DROP TYPE track_attempt_outcome")
