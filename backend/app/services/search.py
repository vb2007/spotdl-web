"""Free-text search (v18) -- case-insensitive substring matching against the existing
`song_json` JSONB and `jobs.source_url`, per the v18 plan's explicit choice: "only reach
for Postgres full-text search if real use shows it's needed." Accelerated by pg_trgm GIN
indexes (migration `b6dde562e77a`), which compiles `track_search_text` to raw SQL so the
index expression and the query expression stay byte-identical -- Postgres only picks an
expression index when the query's expression parses to the same tree it was built from.
"""

from sqlalchemy import exists, func, or_
from sqlalchemy.sql.elements import ColumnElement

from app.models import Job, Track


def track_search_text(song_json_col: ColumnElement) -> ColumnElement:
    """One concatenated blob per track: title, album, and playlist/album name (all
    scalar JSON string fields) plus the artists array's own JSON text form -- exact
    substring matching doesn't need it unnested, and `->>` already renders a JSON array
    as its bracketed text (`'["Queen","Bowie"]'`), so a search for "Bowie" still hits."""
    return (
        func.coalesce(song_json_col["name"].astext, "")
        + " "
        + func.coalesce(song_json_col["album_name"].astext, "")
        + " "
        + func.coalesce(song_json_col["list_name"].astext, "")
        + " "
        + func.coalesce(song_json_col["artists"].astext, "")
    )


def track_matches(q: str) -> ColumnElement:
    return track_search_text(Track.song_json).ilike(f"%{q}%")


def job_matches(q: str) -> ColumnElement:
    """A job matches if its own `source_url` does, or if any of its tracks do -- so
    "find the job containing this song" works from the job-scoped listing too, not only
    the track-scoped one."""
    return or_(
        Job.source_url.ilike(f"%{q}%"),
        exists().where(Track.job_id == Job.id, track_matches(q)),
    )
