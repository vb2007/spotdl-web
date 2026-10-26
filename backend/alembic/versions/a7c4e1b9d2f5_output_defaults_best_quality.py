"""output defaults: opus at "best" when the stored ones are no longer offered

Revision ID: a7c4e1b9d2f5
Revises: f6b2d8e4a1c9
Create Date: 2026-10-26 19:00:00.000000

v54.2, owner's request. **Rewrites data**: the single `app_settings` row's
default_format/default_bitrate become opus/best when either is outside what the app now
offers (app/services/output_options.py). Production's mp3/320k is that case: a "320k" MP3 is
a re-encode of a ~130k YouTube stream. A row already on an offered pair (say m4a/128k) is
left alone. Deploy takes a pg_backup before migrating.

The offered lists are copied here, not imported: a migration must keep meaning what it meant
when it ran.

downgrade() is a no-op: the old values aren't kept, and opus/best is valid on the previous
schema too (both columns are plain text).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c4e1b9d2f5'
down_revision: Union[str, Sequence[str], None] = 'f6b2d8e4a1c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FORMATS = ("opus", "m4a", "mp3")
_BITRATES = ("best", "160k", "128k", "96k", "64k")


def upgrade() -> None:
    """Upgrade schema."""
    op.get_bind().execute(
        sa.text(
            "UPDATE app_settings SET default_format = 'opus', default_bitrate = 'best' "
            "WHERE default_format NOT IN :formats OR default_bitrate NOT IN :bitrates"
        ).bindparams(
            sa.bindparam("formats", expanding=True),
            sa.bindparam("bitrates", expanding=True),
        ),
        {"formats": list(_FORMATS), "bitrates": list(_BITRATES)},
    )


def downgrade() -> None:
    """Downgrade schema."""
