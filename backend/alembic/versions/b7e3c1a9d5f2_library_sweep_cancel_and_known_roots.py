"""library sweep cancel flags and known library roots

Revision ID: b7e3c1a9d5f2
Revises: f6b2d8e4a1c9
Create Date: 2026-10-26 18:00:00.000000

v57 (L1, L6). Additive: `library_sort_runs` gains `cancel_requested`/`cancelled` (false by
default) and `app_settings` gains `library_known_roots`. The settings row's new list is filled
once with its current `library_target_dir`, the only root this install is known to have used;
no existing value is read for anything else or rewritten, so no `pg_backup` beyond the deploy's
own is needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b7e3c1a9d5f2'
down_revision: Union[str, Sequence[str], None] = 'f6b2d8e4a1c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'library_sort_runs',
        sa.Column('cancel_requested', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        'library_sort_runs',
        sa.Column('cancelled', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        'app_settings',
        sa.Column(
            'library_known_roots',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.execute("UPDATE app_settings SET library_known_roots = jsonb_build_array(library_target_dir)")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('app_settings', 'library_known_roots')
    op.drop_column('library_sort_runs', 'cancelled')
    op.drop_column('library_sort_runs', 'cancel_requested')
