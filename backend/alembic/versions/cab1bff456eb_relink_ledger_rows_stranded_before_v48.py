"""v48: relink ledger rows stranded by pre-v48 library sweeps (F34 repair)

Revision ID: cab1bff456eb
Revises: d2f7a9c4e1b8
Create Date: 2026-10-20 08:00:00.000000

Data only, no schema change; it runs once, right after the deploy's pre-deploy pg_backup.
Before v48 a sweep moved a file shared by two ledger rows (two Spotify ids, e.g. a single and
its album cut) for the first row and stranded the second on the deleted /downloads path: an
error on every later sweep, a track whose file can't be downloaded, and a row reconcile_disk
prunes into a re-download at the first boot that finds /downloads non-empty. Production had
47 of them (2026-10-20).

A row is repaired only when all of these hold, so nothing but that legacy shape is touched:
- the last sweep listed its path as "source file missing on disk" (a sweep checked the disk),
- it isn't in the library, and was recorded before that sweep started (not re-downloaded since),
- exactly one in-library ledger file has the same basename (the sweep keeps a source's
  basename, so that's the copy its sibling was filed as; two candidates are left alone).
The row then points at that library file, like its sibling, and so does every completed or
skipped-duplicate track still on the old path. No job is archived. Rows that don't qualify
keep erroring, as before. Downgrade leaves the repair in place: the old code reads a
relinked row like any other in-library row.
"""
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cab1bff456eb'
down_revision: Union[str, Sequence[str], None] = 'd2f7a9c4e1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MISSING = "source file missing on disk"

# Only the columns this repair reads or writes (portable Core, not the app's models, which
# move on with later revisions).
_runs = sa.table("library_sort_runs", sa.column("id"), sa.column("started_at"), sa.column("errors", sa.JSON))
_ledger = sa.table(
    "downloaded_tracks",
    sa.column("spotify_track_id"),
    sa.column("file_path"),
    sa.column("in_library"),
    sa.column("downloaded_at"),
)
_tracks = sa.table("tracks", sa.column("spotify_track_id"), sa.column("output_path"), sa.column("state"))


def upgrade() -> None:
    bind = op.get_bind()
    run = bind.execute(sa.select(_runs.c.started_at, _runs.c.errors).where(_runs.c.id == 1)).first()
    if run is None or run.started_at is None or not run.errors:
        return
    missing = sorted({entry.get("file") for entry in run.errors if entry.get("error") == _MISSING} - {None})
    if not missing:
        return

    filed_by_name: dict[str, set[str]] = defaultdict(set)
    for (path,) in bind.execute(sa.select(_ledger.c.file_path).where(_ledger.c.in_library.is_(True))):
        filed_by_name[PurePosixPath(path).name].add(path)

    relinked = 0
    for source in missing:
        candidates = filed_by_name.get(PurePosixPath(source).name, set())
        if len(candidates) != 1:
            continue
        (dest,) = candidates
        stranded = _ledger.c.file_path == source, _ledger.c.in_library.is_(False), _ledger.c.downloaded_at < run.started_at
        ids = list(bind.execute(sa.select(_ledger.c.spotify_track_id).where(*stranded)).scalars())
        if not ids:
            continue
        bind.execute(sa.update(_ledger).where(*stranded).values(file_path=dest, in_library=True))
        bind.execute(
            sa.update(_tracks)
            .where(
                _tracks.c.output_path == source,
                _tracks.c.spotify_track_id.in_(ids),
                # Cast: tracks.state is a native enum on Postgres, and a bound string
                # parameter won't compare with it.
                sa.cast(_tracks.c.state, sa.String).in_(["completed", "skipped_duplicate"]),
            )
            .values(output_path=dest)
        )
        relinked += len(ids)
    print(f"v48: relinked {relinked} stranded ledger row(s) to their library copy")


def downgrade() -> None:
    """The relink stays: there's no stranded state worth restoring."""
