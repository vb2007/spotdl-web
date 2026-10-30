"""user_settings job_notifications preference

Revision ID: e4b8d2f6a1c3
Revises: c5f1a7e3b9d2
Create Date: 2026-10-30 12:00:00.000000

v66: the per-user switch for a browser notification when one of the user's own jobs settles.
Additive only: every existing row gets the default (off) and no data is rewritten.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4b8d2f6a1c3'
down_revision: Union[str, Sequence[str], None] = 'c5f1a7e3b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'user_settings',
        sa.Column('job_notifications', sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_settings', 'job_notifications')
