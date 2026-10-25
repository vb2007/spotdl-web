"""api_keys table

Revision ID: f6b2d8e4a1c9
Revises: cab1bff456eb
Create Date: 2026-10-24 18:00:00.000000

v53: per-user API keys for the browser extension. Additive only: a new table, no existing
row is read or rewritten. `hash` is the SHA-256 of the whole key (the key itself is never
stored); a user's keys go with the user (ON DELETE CASCADE).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6b2d8e4a1c9'
down_revision: Union[str, Sequence[str], None] = 'cab1bff456eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'api_keys',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('prefix', sa.String(length=8), nullable=False),
        sa.Column('hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('hash'),
    )
    op.create_index(op.f('ix_api_keys_user_id'), 'api_keys', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_api_keys_user_id'), table_name='api_keys')
    op.drop_table('api_keys')
