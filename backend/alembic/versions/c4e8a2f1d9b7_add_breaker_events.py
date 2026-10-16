"""add breaker_events

Revision ID: c4e8a2f1d9b7
Revises: f3a8c2d6e9b1
Create Date: 2026-10-16 12:00:00.000000

v44: an append-only history of circuit-breaker transitions (tripped / escalated /
released), the source of the admin stats page's breaker chart. worker_state only ever
held the current breaker. A new table only: no existing row is read or rewritten.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e8a2f1d9b7'
down_revision: Union[str, Sequence[str], None] = 'f3a8c2d6e9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'breaker_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column(
            'kind',
            sa.Enum('tripped', 'escalated', 'released', name='breaker_event_kind'),
            nullable=False,
        ),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('step_seconds', sa.Integer(), nullable=True),
        sa.Column('trip_count', sa.Integer(), nullable=True),
        sa.Column('paused_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('manual', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_breaker_events_occurred_at'), 'breaker_events', ['occurred_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_breaker_events_occurred_at'), table_name='breaker_events')
    op.drop_table('breaker_events')
    # op.drop_table() never drops the native enum it created (docs/GOTCHAS.md v02).
    op.execute("DROP TYPE breaker_event_kind")
