"""v50: the e2e fixture for an agent slot's fresh database (`scripts/agent_stack.sh <slot> seed`).

The Playwright suite was written against the owner's long-lived dev database, and leans on what
it has accumulated: ledger rows (with files) for every track a default run submits, so each job
resolves as a duplicate and never downloads, and the e2e admin's history. A slot's database
starts empty, so this recreates both, idempotently. Run inside the slot's `worker-meta` (it has
the database and both file roots mounted), never against any other stack:

    docker compose exec -T worker-meta python - < scripts/agent_seed.py

Stand-in files are one-second silent MP3s: "already exists" is folder + filename only, so a
stand-in counts as present. Every row it creates says "agent fixture" in its path or URL.
"""

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.db import SessionLocal
from app.models import DownloadedTrack
from app.models.job import Job, JobSourceType, JobState
from app.models.track import Track, TrackState
from app.models.track_attempt import NetworkPath, TrackAttempt, TrackAttemptOutcome
from app.models.user import User
from app.services import app_settings
from app.services.users import get_or_create_user, normalize_email

# Ledger hits the specs submit: LEDGER_TRACKS (support/stack.ts), CANCEL_TRACKS (spec 12),
# HELD_TRACKS and NEIGHBOUR_TRACK (spec 14). Filed (`in_library`), so a library sweep leaves
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
]
# Spec 9's two tracks the library sort moved: filed under the library root.
MOVED = ["0DiWol3AO6WpXZgp0goxAV", "5W3cjX2J3tjhG8zb6u0qHn"]
FIXTURE_DIR = "agent fixture"
# The admin's history, which the owner's long-lived dev database has and a fresh slot doesn't:
# spec 14 pages through three pages of jobs (50 each), opens a job of twelve or more tracks,
# and spec 3 needs a track whose attempt recorded a network path. Archived, so the dashboard
# shows them only with "show archived".
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


db = SessionLocal()
settings = get_settings()
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

    def add_job(n, kind, titles, *, track_state=TrackState.SKIPPED_DUPLICATE, list_name=None):
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
            )
            db.add(track)
            tracks.append(track)
        db.flush()
        return tracks

    for n in range(HISTORY_JOBS):
        add_job(n, JobSourceType.TRACK, [f"History fixture {n:03d}"])
    add_job(
        HISTORY_JOBS,
        JobSourceType.ALBUM,
        [f"Album fixture track {i:02d}" for i in range(1, ALBUM_TRACKS + 1)],
        list_name="Album fixture",
    )
    (track,) = add_job(
        HISTORY_JOBS + 1,
        JobSourceType.TRACK,
        ["Network path fixture"],
        track_state=TrackState.COMPLETED,
    )
    finished = start + timedelta(minutes=HISTORY_JOBS + 1, seconds=30)
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
