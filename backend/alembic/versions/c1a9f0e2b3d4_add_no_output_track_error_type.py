"""add no_output track error type

Revision ID: c1a9f0e2b3d4
Revises: b6dde562e77a
Create Date: 2026-08-14 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a9f0e2b3d4'
down_revision: Union[str, Sequence[str], None] = 'b6dde562e77a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction that later uses the
    # new value, but it's fine for it to be the only statement in this migration's
    # transaction (Postgres 12+) — same technique as 46be30064f8b_add_cancelled_job_state.
    op.execute("ALTER TYPE track_error_type ADD VALUE IF NOT EXISTS 'no_output'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres has no `DROP VALUE` for enums — recreate the type without 'no_output' and
    # swap the column over. Any row already classified 'no_output' is remapped to
    # 'other', the bucket it fell into before this version, so the column swap never
    # fails on real data.
    op.execute(
        "UPDATE tracks SET last_error_type = 'other' WHERE last_error_type = 'no_output'"
    )
    op.execute("ALTER TYPE track_error_type RENAME TO track_error_type_old")
    op.execute("CREATE TYPE track_error_type AS ENUM ('audio_provider', 'lookup', 'other')")
    op.execute(
        "ALTER TABLE tracks ALTER COLUMN last_error_type "
        "TYPE track_error_type USING last_error_type::text::track_error_type"
    )
    op.execute("DROP TYPE track_error_type_old")
