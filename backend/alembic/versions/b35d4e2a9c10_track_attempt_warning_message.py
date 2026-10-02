"""track_attempts.warning_message

Revision ID: b35d4e2a9c10
Revises: a35c0e1f7b21
Create Date: 2026-10-02 00:00:01.000000

v35 (d): a note on an attempt that didn't fail gets its own column, so error_message
only ever means a failure. Existing rows are moved over: a `completed` row's
error_message has only ever been v26's tag-repair note, and a `held` row's only ever the
breaker-hold reason (both written solely by download.py). This rewrites data, covered by
the same pre-deploy pg_backup as a35c0e1f7b21. downgrade() moves the notes back.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b35d4e2a9c10'
down_revision: Union[str, Sequence[str], None] = 'a35c0e1f7b21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('track_attempts', sa.Column('warning_message', sa.Text(), nullable=True))
    op.execute(
        "UPDATE track_attempts SET warning_message = error_message, error_message = NULL "
        "WHERE outcome IN ('completed', 'held') AND error_message IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "UPDATE track_attempts SET error_message = warning_message "
        "WHERE warning_message IS NOT NULL AND error_message IS NULL"
    )
    op.drop_column('track_attempts', 'warning_message')
