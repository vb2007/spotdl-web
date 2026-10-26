"""proxy FKs ON DELETE SET NULL; track_attempts.proxy_label

Revision ID: a9d3c5e7f1b2
Revises: f6b2d8e4a1c9
Create Date: 2026-10-26 00:00:00.000000

v56 (A4): deleting a manual proxy an attempt (or a track's `used_proxy_id`) referenced was a
500, the two FKs having no ON DELETE. Both become ON DELETE SET NULL. So that "which proxy" isn't
lost with the row, every attempt now stores its proxy's redacted label (scheme://host:port, never
a credential), written by `attempts.record_attempt`.

Data: no existing value is changed or dropped. The new column is backfilled once for every
attempt that has a proxy, from that proxy's URL, with the same rule as `proxies.redact()` (a
frozen copy here, as migrations don't import app code). `downgrade()` drops the column (the
labels of proxies deleted meanwhile go with it) and restores the plain FKs; the NULLs a deletion
left stay NULL, which those accept.
"""
from typing import Sequence, Union
from urllib.parse import urlsplit

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9d3c5e7f1b2'
down_revision: Union[str, Sequence[str], None] = 'f6b2d8e4a1c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FKS = [
    # (constraint, table, column)
    ('track_attempts_proxy_id_fkey', 'track_attempts', 'proxy_id'),
    ('tracks_used_proxy_id_fkey', 'tracks', 'used_proxy_id'),
]


def _label(url: str) -> str:
    try:
        parsed = urlsplit(url)
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    except ValueError:
        return "proxy"


def upgrade() -> None:
    """Upgrade schema."""
    for name, table, column in _FKS:
        op.drop_constraint(name, table, type_='foreignkey')
        op.create_foreign_key(name, table, 'proxies', [column], ['id'], ondelete='SET NULL')
    op.add_column('track_attempts', sa.Column('proxy_label', sa.Text(), nullable=True))
    bind = op.get_bind()
    # One UPDATE per proxy (a handful of rows), never per attempt.
    for proxy_id, url in bind.execute(
        sa.text("SELECT id, url FROM proxies WHERE id IN (SELECT DISTINCT proxy_id FROM track_attempts)")
    ).all():
        bind.execute(
            sa.text("UPDATE track_attempts SET proxy_label = :label WHERE proxy_id = :id"),
            {"label": _label(url), "id": proxy_id},
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('track_attempts', 'proxy_label')
    for name, table, column in _FKS:
        op.drop_constraint(name, table, type_='foreignkey')
        op.create_foreign_key(name, table, 'proxies', [column], ['id'])
