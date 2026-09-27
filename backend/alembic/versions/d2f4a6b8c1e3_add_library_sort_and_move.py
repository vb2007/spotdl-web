"""add library sort & move settings, ledger flag, and sort-run tracking

Revision ID: d2f4a6b8c1e3
Revises: a1c7f4d8e2b0
Create Date: 2026-08-17 00:00:00.000000

v28: admin-configurable library target dir / folder template / quarantine settings
(reusing app_settings's singleton row, same shape as its existing output-format
fields), downloaded_tracks.in_library (the distinct stored state marking a ledger row's
file as sorted into the real library, separate from any job's archived_at), and
library_sort_runs (single-row progress/report tracking for the admin-triggered sweep,
same get-or-create shape as worker_state).

The live DB is disposable (locked v3 decision) -- output_template's stored default is
reset directly rather than conditionally patched, to the new
"{track-number} - {artists} - {title}.{output-ext}" default matching the existing
library's naming convention.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'd2f4a6b8c1e3'
down_revision: Union[str, Sequence[str], None] = 'a1c7f4d8e2b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'app_settings',
        sa.Column(
            'library_target_dir', sa.Text(), nullable=False,
            server_default='/mnt/raid1/media/music',
        ),
    )
    op.add_column(
        'app_settings',
        sa.Column(
            'library_folder_template', sa.Text(), nullable=False,
            server_default='{artist} - {album} - ({year})',
        ),
    )
    op.add_column(
        'app_settings',
        sa.Column(
            'library_quarantine_enabled', sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        'app_settings',
        sa.Column(
            'library_quarantine_dir', sa.Text(), nullable=False,
            server_default='/downloads/quarantine',
        ),
    )
    # See this migration's own docstring -- the live DB is disposable (locked v3
    # decision), so the new filename-template default is reset directly rather than
    # conditionally patched only where it still matches the old default.
    op.execute(
        "UPDATE app_settings SET output_template = "
        "'{track-number} - {artists} - {title}.{output-ext}'"
    )

    op.add_column(
        'downloaded_tracks',
        sa.Column('in_library', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        'library_sort_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column(
            'state',
            sa.Enum('idle', 'running', name='library_sort_state'),
            nullable=False,
        ),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total', sa.Integer(), nullable=False),
        sa.Column('processed', sa.Integer(), nullable=False),
        sa.Column('moved', sa.Integer(), nullable=False),
        sa.Column('skipped_present', sa.Integer(), nullable=False),
        sa.Column('quarantined', sa.Integer(), nullable=False),
        sa.Column('errors', JSONB(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('library_sort_runs')
    op.execute('DROP TYPE library_sort_state')
    op.drop_column('downloaded_tracks', 'in_library')
    op.drop_column('app_settings', 'library_quarantine_dir')
    op.drop_column('app_settings', 'library_quarantine_enabled')
    op.drop_column('app_settings', 'library_folder_template')
    op.drop_column('app_settings', 'library_target_dir')
