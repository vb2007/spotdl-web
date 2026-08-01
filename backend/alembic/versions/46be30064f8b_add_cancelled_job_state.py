"""add cancelled job state

Revision ID: 46be30064f8b
Revises: ebc1d43e2c21
Create Date: 2026-08-01 21:56:50.204067

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '46be30064f8b'
down_revision: Union[str, Sequence[str], None] = 'ebc1d43e2c21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction that later uses the
    # new value, but it's fine for it to be the only statement in this migration's
    # transaction (Postgres 12+) — no data touches 'cancelled' until a later migration/app
    # code does.
    op.execute("ALTER TYPE job_state ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres has no `DROP VALUE` for enums — recreate the type without 'cancelled' and
    # swap the column over, same technique as v02's enum-type gotchas but for a value
    # rather than a whole type. Any row already in 'cancelled' is remapped to 'failed'
    # (the closest existing terminal-ish state) so the column swap never fails.
    op.execute("UPDATE jobs SET state = 'failed' WHERE state = 'cancelled'")
    op.execute("ALTER TYPE job_state RENAME TO job_state_old")
    op.execute("CREATE TYPE job_state AS ENUM ('expanding', 'expanded', 'failed')")
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN state TYPE job_state USING state::text::job_state"
    )
    op.execute("DROP TYPE job_state_old")
