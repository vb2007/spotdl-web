"""add track_attempts.network_path

Revision ID: e7c1f9a4d2b6
Revises: d2f4a6b8c1e3
Create Date: 2026-09-27 00:00:00.000000

v29: which network path (direct-ipv4 / direct-ipv6 / proxy) an attempt actually used.
Nullable -- rows that never touched the network (breaker-active, dedup-skip,
cancelled-before-dispatch) leave it NULL, see app/tasks/download.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e7c1f9a4d2b6'
down_revision: Union[str, Sequence[str], None] = 'd2f4a6b8c1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Unlike every prior enum in this project (all created as part of their table's own
    # create_table), this one is added to an *existing* table via a plain ALTER TABLE ADD
    # COLUMN -- SQLAlchemy's DDL compiler only auto-creates an enum type as a side effect
    # of create_table, so the type needs an explicit create() first here or ADD COLUMN
    # fails with "type track_network_path does not exist" (confirmed against real Postgres).
    network_path_enum = postgresql.ENUM(
        'direct-ipv4', 'direct-ipv6', 'proxy',
        name='track_network_path',
    )
    network_path_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'track_attempts',
        sa.Column('network_path', network_path_enum, nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('track_attempts', 'network_path')
    op.execute("DROP TYPE track_network_path")
