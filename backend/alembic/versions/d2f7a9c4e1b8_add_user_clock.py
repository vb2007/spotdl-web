"""user_settings clock (12/24-hour) preference

Revision ID: d2f7a9c4e1b8
Revises: b8e4d1f6a3c7
Create Date: 2026-10-18 21:00:00.000000

v46 (owner-directed): the per-user time format. Additive only: NULL means "automatic" (the
browser's region decides), so every existing row keeps today's behavior and no data is
rewritten. A plain string (`12h`/`24h`), checked at the API, not a native enum.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2f7a9c4e1b8'
down_revision: Union[str, Sequence[str], None] = 'b8e4d1f6a3c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user_settings', sa.Column('clock', sa.String(length=3), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_settings', 'clock')
