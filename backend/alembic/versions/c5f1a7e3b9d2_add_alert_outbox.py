"""add alert_outbox and the worker-down alert settings

Revision ID: c5f1a7e3b9d2
Revises: b7e3c1a9d5f2
Create Date: 2026-10-27 22:00:00.000000

v59: a Postgres outbox for Matrix alerts (one row per alert raised: pending, sent, failed or
suppressed), replacing v36's fire-and-forget Celery send. Plus the worker-down category's
toggle and threshold on the app_settings singleton. Additive only: a new table, and two
columns with a server_default, so the existing row gets the documented defaults and no data
is rewritten.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5f1a7e3b9d2'
down_revision: Union[str, Sequence[str], None] = 'b7e3c1a9d5f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'alert_outbox',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('fingerprint', sa.String(length=200), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'state',
            sa.Enum('pending', 'sent', 'failed', 'suppressed', name='alert_state'),
            nullable=False,
        ),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_alert_outbox_created_at'), 'alert_outbox', ['created_at'])
    op.create_index(
        'ix_alert_outbox_category_fingerprint',
        'alert_outbox',
        ['category', 'fingerprint', 'created_at'],
    )
    op.create_index(
        'ix_alert_outbox_pending',
        'alert_outbox',
        ['created_at'],
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.add_column(
        'app_settings',
        sa.Column('alerts_worker_down_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        'app_settings',
        sa.Column('alert_worker_down_minutes', sa.Integer(), nullable=False, server_default='15'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('app_settings', 'alert_worker_down_minutes')
    op.drop_column('app_settings', 'alerts_worker_down_enabled')
    op.drop_index('ix_alert_outbox_pending', table_name='alert_outbox')
    op.drop_index('ix_alert_outbox_category_fingerprint', table_name='alert_outbox')
    op.drop_index(op.f('ix_alert_outbox_created_at'), table_name='alert_outbox')
    op.drop_table('alert_outbox')
    # op.drop_table() never drops the native enum it created (docs/GOTCHAS.md v02).
    op.execute("DROP TYPE alert_state")
