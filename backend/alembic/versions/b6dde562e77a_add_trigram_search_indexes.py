"""add trigram search indexes

Revision ID: b6dde562e77a
Revises: 9e18f8d457c8
Create Date: 2026-08-10 23:28:54.089290

v18's free-text search (`app/services/search.py`) does case-insensitive substring
matching (`ILIKE '%q%'`) rather than Postgres full-text search -- the plan's explicit
choice, since two or three users searching a few hundred thousand rows don't need
`tsvector` ranking. Plain B-tree/GIN indexes don't accelerate arbitrary substring
matches; `pg_trgm`'s trigram GIN indexes do.

The `tracks` index's expression must stay byte-identical to
`search.track_search_text()`'s compiled SQL, or Postgres won't recognize it as the same
expression and will silently stop using the index -- if that function's field list ever
changes, this index needs a matching migration, not just a code change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6dde562e77a'
down_revision: Union[str, Sequence[str], None] = '9e18f8d457c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRACK_SEARCH_TEXT_SQL = (
    "coalesce((song_json ->> 'name'), '') || ' ' || "
    "coalesce((song_json ->> 'album_name'), '') || ' ' || "
    "coalesce((song_json ->> 'list_name'), '') || ' ' || "
    "coalesce((song_json ->> 'artists'), '')"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_jobs_source_url_trgm ON jobs USING gin (source_url gin_trgm_ops)"
    )
    op.execute(
        f"CREATE INDEX ix_tracks_search_trgm ON tracks USING gin (({_TRACK_SEARCH_TEXT_SQL}) gin_trgm_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_tracks_search_trgm")
    op.execute("DROP INDEX IF EXISTS ix_jobs_source_url_trgm")
    # pg_trgm is left installed -- dropping a shared extension on downgrade risks
    # breaking any other index/object that came to depend on it in the meantime, for no
    # benefit (an unused extension costs nothing sitting in pg_catalog).
