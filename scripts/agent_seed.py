"""v50: the e2e fixture for an agent slot's fresh database (`scripts/agent_stack.sh <slot> seed`).

The Playwright suite was written against the owner's long-lived dev database, and leans on what
it has accumulated: ledger rows (with files) for every track a default run submits, so each job
resolves as a duplicate and never downloads, and the e2e admin's history. A slot's database
starts empty, so this recreates both, idempotently. Run it with `scripts/agent_stack.sh <slot>
seed`, which pipes it into the slot's `worker-meta` (it has the database and both file roots
mounted). It refuses any database but a slot's (`spotdlweb_s1`..`spotdlweb_s4`), so it never
writes fixtures into the owner's `spotdlwebtest`.

Stand-in files are one-second silent MP3s: "already exists" is folder + filename only, so a
stand-in counts as present. Every row it creates says "agent fixture" in its path or URL.
"""

import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db import SessionLocal
from app.models import DownloadedTrack
from app.models.job import Job, JobSourceType, JobState
from app.models.track import Track, TrackState
from app.models.track_attempt import NetworkPath, TrackAttempt, TrackAttemptOutcome
from app.models.user import User
from app.services import app_settings
from app.services.users import get_or_create_user, normalize_email

# Ledger hits the specs submit: LEDGER_TRACKS (support/stack.ts), CANCEL_TRACKS and
# SUBMISSION_TRACKS (spec 12), HELD_TRACKS and NEIGHBOUR_TRACK (spec 14). Filed (`in_library`), so a library sweep leaves
# them alone and spec 12's sweep doesn't step aside, but kept under /downloads: spec 9 takes the
# first two in-library files under the library root by id, and these ids sort first.
SUBMITTED = [
    "69kOkLUCkxIZYexIgSG8rq",
    "2KHRENHQzTIQ001nlP9Gdc",
    "79koEJRtKOOGJ0VSAF3FMk",
    "0k1xMUwn9sb7bZiqdT9ygx",
    "0C80GCp0mMuBzLf3EAXqxv",
    "6Th6ND8RQPywiyelecP5Lf",
    "6rAy2MsMUabbqu2VygrblP",
    "5XeMsYb1rWxQL1bUUaZajn",
    "098ttCNmncrO4YvqWUNMvn",
    "186hvCTyrni4KT9nwIQ7zS",
    "2LD2gT7gwAurzdQDQtILds",
    "08mG3Y1vljYA6bvDt4Wqkj",
    "2SiXAy7TuUkycRVbbWDEpo",
]
# Spec 9's two tracks the library sort moved: filed under the library root.
MOVED = ["0DiWol3AO6WpXZgp0goxAV", "5W3cjX2J3tjhG8zb6u0qHn"]
FIXTURE_DIR = "agent fixture"
# The admin's history, which the owner's long-lived dev database has and a fresh slot doesn't:
# spec 14 pages through three pages of jobs (50 each), opens a job of twelve or more tracks,
# and spec 3 needs a track whose attempt recorded a network path. Archived, so the dashboard
# shows them only with "show archived". The album and the network-path job are the oldest, as on
# the owner's database: spec 14 waits for its search to list the album, and a row already on the
# first unfiltered page would satisfy that wait before the search's own re-render removes it.
HISTORY_JOBS = 120
ALBUM_TRACKS = 14
HISTORY_URL = "https://open.spotify.com/{kind}/agentfixture{n:04d}"


def stand_in(path: Path, title: str) -> None:
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            "1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            "-metadata",
            f"title={title}",
            str(path),
        ],
        check=True,
    )


settings = get_settings()
database = make_url(settings.database_url).database or ""
if settings.spotdl_env != "dev" or not re.fullmatch(r"spotdlweb_s[1-4]", database):
    sys.exit(f"agent_seed: refusing database {database!r}: only an agent slot's (spotdlweb_s1-4)")
db = SessionLocal()
# What the connection really reached (a `?dbname=` in the URL would override its path).
connected = db.execute(text("select current_database()")).scalar()
if connected != database:
    sys.exit(f"agent_seed: refusing: the URL names {database!r} but connects to {connected!r}")
library = Path(app_settings.get_library_settings(db).library_target_dir) / FIXTURE_DIR
downloads = Path(settings.download_output_dir) / FIXTURE_DIR
ledger = [(i, downloads) for i in SUBMITTED] + [(i, library) for i in MOVED]
for spotify_id, folder in ledger:
    row = db.get(DownloadedTrack, spotify_id)
    if row is not None and Path(row.file_path).is_file():
        continue
    path = folder / f"{spotify_id}.mp3"
    stand_in(path, spotify_id)
    values = {"file_path": str(path), "format": "mp3", "bitrate": "128k", "in_library": True}
    db.execute(
        insert(DownloadedTrack)
        .values(spotify_track_id=spotify_id, **values)
        .on_conflict_do_update(index_elements=["spotify_track_id"], set_=values)
    )
    print(f"seed: ledger {spotify_id} -> {path}")
db.commit()

email = normalize_email(settings.admin_email)
admin = db.query(User).filter(User.email == email).one_or_none() or get_or_create_user(db, email)
if db.query(Job).filter(Job.user_id == admin.id, Job.source_url.like("%/agentfixture%")).first():
    print(f"seed: {email}'s history is already there")
else:
    start = datetime.now(timezone.utc) - timedelta(days=30)

    def add_job(
        n, kind, titles, *, track_state=TrackState.SKIPPED_DUPLICATE, list_name=None, attempts=0
    ):
        created = start + timedelta(minutes=n)
        job = Job(
            user_id=admin.id,
            source_url=HISTORY_URL.format(kind=kind.value, n=n),
            source_type=kind,
            state=JobState.EXPANDED,
            created_at=created,
            archived_at=created + timedelta(hours=1),
        )
        db.add(job)
        db.flush()
        tracks = []
        for i, title in enumerate(titles):
            song = {"name": title, "artists": ["agent fixture"], "album_name": "agent fixture"}
            if list_name:
                song["list_name"] = list_name
            track = Track(
                job_id=job.id,
                spotify_track_id=f"agentfixture{n:04d}t{i:02d}",
                song_json=song,
                state=track_state,
                created_at=created + timedelta(seconds=i),
                # As attempts.record_attempt leaves a first-try success (v35): one attempt made,
                # no failure (attempt_count is the ladder's failure count).
                attempts_made=attempts,
            )
            db.add(track)
            tracks.append(track)
        db.flush()
        return tracks

    add_job(
        0,
        JobSourceType.ALBUM,
        [f"Album fixture track {i:02d}" for i in range(1, ALBUM_TRACKS + 1)],
        list_name="Album fixture",
    )
    (track,) = add_job(
        1,
        JobSourceType.TRACK,
        ["Network path fixture"],
        track_state=TrackState.COMPLETED,
        attempts=1,
    )
    finished = start + timedelta(minutes=1, seconds=30)
    for n in range(2, HISTORY_JOBS + 2):
        add_job(n, JobSourceType.TRACK, [f"History fixture {n:03d}"])
    db.add(
        TrackAttempt(
            track_id=track.id,
            attempt_number=1,
            started_at=finished - timedelta(seconds=20),
            finished_at=finished,
            outcome=TrackAttemptOutcome.COMPLETED,
            network_path=NetworkPath.DIRECT_IPV4,
        )
    )
    db.commit()
    print(
        f"seed: {email}'s history: {HISTORY_JOBS} archived jobs, a {ALBUM_TRACKS}-track album, "
        "a track with a network path"
    )
