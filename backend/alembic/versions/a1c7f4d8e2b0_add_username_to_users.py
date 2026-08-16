"""add username to users

Revision ID: a1c7f4d8e2b0
Revises: 5ae734a0485b
Create Date: 2026-08-16 10:00:00.000000

v25: `users.username`, populated from upstream `GET /user` at login time. Nullable --
a row can exist before its first successful fetch (see `app/models/user.py`).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c7f4d8e2b0'
down_revision: Union[str, Sequence[str], None] = '5ae734a0485b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('username', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'username')
