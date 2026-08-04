"""add app_settings table

Revision ID: 321fd6d33d82
Revises: 46be30064f8b
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '321fd6d33d82'
down_revision: Union[str, Sequence[str], None] = '46be30064f8b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # No seed row inserted here -- app.services.app_settings.get_output_settings() creates
    # id=1 on first read, seeded from the DEFAULT_FORMAT/DEFAULT_BITRATE/DOWNLOAD_OUTPUT_DIR
    # env vars at that moment (same get-or-create shape as worker_state).
    op.create_table(
        'app_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('default_format', sa.Text(), nullable=False),
        sa.Column('default_bitrate', sa.Text(), nullable=False),
        sa.Column('output_dir', sa.Text(), nullable=False),
        sa.Column('output_template', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('app_settings')
