"""proxy FKs SET NULL; attempt proxy_label; retry_now_step; due index; retention clamp

Revision ID: a9d3c5e7f1b2
Revises: d9b3e5f7a1c2
Create Date: 2026-10-26 00:00:00.000000

v56 (A4): deleting a manual proxy an attempt (or a track's `used_proxy_id`) referenced was a
500, the two FKs having no ON DELETE. Both become ON DELETE SET NULL. So that "which proxy" isn't
lost with the row, every attempt now stores its proxy's redacted label (scheme://host:port, never
a credential), written by `attempts.record_attempt`.

v56 (A4, owner's decision): `proxies.delete_requested_at`, nullable: a delete that waits for the
proxy's in-flight download (the row is never picked again and goes once nothing uses it).

v56 (E1): `ix_tracks_scheduled_at_due`, a partial index on `scheduled_at` for `waiting` and
`pending` tracks: beat's dispatch query now takes both (expand_job's outbox marker), and the
`waiting`-only index can't serve it.

v56 (A8): `tracks.retry_now_step`, nullable, the ladder step at which a non-admin last used
"retry now" (one per step). NULL for every existing track: nobody has used one under the rule.

v56 (A5, owner's decision): `user_settings.retention_days` is clamped to the API's new bound,
1-36500: above 36500 becomes 36500, below 1 becomes NULL (never archive, as a non-positive value
was refused anyway). A value past ~739,000 days stopped the hourly archive sweep for every
later user (OverflowError), and the bound only stops new ones. **This rewrites data** (only
out-of-range rows; normally none): take a `pg_backup` first. `downgrade()` doesn't restore them.

Data otherwise: no existing value is changed or dropped. The new column is backfilled once for every
attempt that has a proxy, from that proxy's URL, with the same rule as `proxies.redact()` (a
frozen copy here, as migrations don't import app code). `downgrade()` drops both columns (the
labels of proxies deleted meanwhile go with them) and restores the plain FKs; the NULLs a deletion
left stay NULL, which those accept.
"""
from typing import Sequence, Union
from urllib.parse import urlsplit

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9d3c5e7f1b2'
down_revision: Union[str, Sequence[str], None] = 'd9b3e5f7a1c2'
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
    op.add_column('tracks', sa.Column('retry_now_step', sa.Integer(), nullable=True))
    op.add_column('proxies', sa.Column('delete_requested_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        'ix_tracks_scheduled_at_due', 'tracks', ['scheduled_at'],
        postgresql_where=sa.text("state IN ('waiting', 'pending')"),
    )
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE user_settings SET retention_days = 36500 WHERE retention_days > 36500"))
    bind.execute(sa.text("UPDATE user_settings SET retention_days = NULL WHERE retention_days < 1"))
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
    op.drop_index('ix_tracks_scheduled_at_due', table_name='tracks')
    op.drop_column('proxies', 'delete_requested_at')
    op.drop_column('tracks', 'retry_now_step')
    op.drop_column('track_attempts', 'proxy_label')
    for name, table, column in _FKS:
        op.drop_constraint(name, table, type_='foreignkey')
        op.create_foreign_key(name, table, 'proxies', [column], ['id'])
