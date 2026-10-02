"""app_settings alert controls

Revision ID: f3a8c2d6e9b1
Revises: b35d4e2a9c10
Create Date: 2026-10-02 12:00:00.000000

v36: per-category Matrix alert toggles plus the spike/beat-stale thresholds and the
cooldown, on the existing app_settings singleton. Additive only: every column has a
server_default, so the existing row is filled with the documented defaults and no data is
rewritten.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a8c2d6e9b1'
down_revision: Union[str, Sequence[str], None] = 'b35d4e2a9c10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TOGGLES = (
    'alerts_breaker_enabled',
    'alerts_spike_enabled',
    'alerts_beat_stale_enabled',
    'alerts_library_enabled',
)
_NUMBERS = (
    ('alert_spike_threshold', '5'),
    ('alert_spike_window_minutes', '60'),
    ('alert_beat_stale_seconds', '180'),
    ('alert_cooldown_minutes', '60'),
)


def upgrade() -> None:
    """Upgrade schema."""
    for name in _TOGGLES:
        op.add_column(
            'app_settings',
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    for name, default in _NUMBERS:
        op.add_column(
            'app_settings',
            sa.Column(name, sa.Integer(), nullable=False, server_default=default),
        )


def downgrade() -> None:
    """Downgrade schema."""
    for name, _ in reversed(_NUMBERS):
        op.drop_column('app_settings', name)
    for name in reversed(_TOGGLES):
        op.drop_column('app_settings', name)
