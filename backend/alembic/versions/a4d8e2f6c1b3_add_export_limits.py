"""app_settings job export limits

Revision ID: a4d8e2f6c1b3
Revises: c5f1a7e3b9d2
Create Date: 2026-10-30 12:00:00.000000

v64: the job zip export's file-count and size limits, as admin overrides on the existing
app_settings singleton. Additive only: both columns are nullable and start NULL (the env
defaults EXPORT_MAX_FILES/EXPORT_MAX_GB apply), so no data is rewritten.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4d8e2f6c1b3'
down_revision: Union[str, Sequence[str], None] = 'c5f1a7e3b9d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('app_settings', sa.Column('export_max_files', sa.Integer(), nullable=True))
    op.add_column('app_settings', sa.Column('export_max_gb', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('app_settings', 'export_max_gb')
    op.drop_column('app_settings', 'export_max_files')
