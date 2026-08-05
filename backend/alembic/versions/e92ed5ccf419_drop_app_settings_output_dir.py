"""drop app_settings.output_dir

Revision ID: e92ed5ccf419
Revises: 321fd6d33d82
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e92ed5ccf419'
down_revision: Union[str, Sequence[str], None] = '321fd6d33d82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Real user testing of v13's settings UI found this field editable in name only --
    # the directory a running container can actually write to is fixed by its volume
    # mount at deploy time (DOWNLOAD_OUTPUT_DIR), not by an app-level setting. Dropped
    # rather than left as dead, never-read state.
    op.drop_column('app_settings', 'output_dir')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('app_settings', sa.Column('output_dir', sa.Text(), nullable=True))
    op.execute("UPDATE app_settings SET output_dir = '/downloads' WHERE output_dir IS NULL")
    op.alter_column('app_settings', 'output_dir', nullable=False)
