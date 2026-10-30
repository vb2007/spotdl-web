import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select, update

from app.db import SessionLocal
from app.models import Job, JobState, Track, TrackState
from app.services import events, expansion, job_status, watch
from app.services.serializers import track_song_meta
from app.tasks.celery_app import celery_app
from app.tasks.download import download_track

logger = logging.getLogger(__name__)


# v56 (E1): how long a run's claim on its tracks (below) keeps beat away. Only a run that died
# between its claim and its sends ever lets one run out: beat then dispatches those tracks (in
# no particular order: they share the one lease timestamp).
DISPATCH_LEASE = timedelta(minutes=10)


def _mark_due(tracks: list[Track], now: datetime) -> None:
    """The outbox marker (v56, E1): a `pending` track with a `scheduled_at` is due to be
    handed to the broker, and beat's `dispatch_due_tracks` hands it over if nothing else has.
    A microsecond apart, so beat keeps their order (it sorts by `scheduled_at`)."""
    for index, track in enumerate(tracks):
        track.scheduled_at = now + timedelta(microseconds=index)


def _dispatch_due(db, job: Job, track_ids: list[uuid.UUID]) -> None:
    """Hands `track_ids` (those still `pending` and due) to the broker, in this order.

    v56 (E1): the tracks are claimed first, by moving their marker DISPATCH_LEASE ahead in
    one committed UPDATE: beat only takes a track whose marker is due, so on the happy path
    it never sends one of these a second time, and a track beat already took is no longer
    `pending`, so this run skips it. A broker error part-way puts the unsent tracks' marker
    back to now (beat's next tick sends them), instead of leaving them `pending` forever under
    an acked task (v34.1's gap, docs/GOTCHAS.md). The sent ones lose their marker last. Every
    write is conditional on the claim still being this run's: the track may have been
    cancelled or downloaded meanwhile."""
    now = datetime.now(timezone.utc)
    lease = now + DISPATCH_LEASE
    _lock_job(db, job)
    claimed = set(
        db.execute(
            update(Track)
            .where(
                Track.id.in_(track_ids),
                Track.state == TrackState.PENDING,
                Track.scheduled_at <= now,
            )
            .values(scheduled_at=lease)
            .returning(Track.id)
            .execution_options(synchronize_session=False)
        ).scalars()
    )
    db.commit()
    ordered = [track_id for track_id in track_ids if track_id in claimed]
    sent = 0
    try:
        for track_id in ordered:
            download_track.delay(str(track_id))
            sent += 1
    except Exception as exc:
        logger.warning(
            "expand_job: job %s: the broker refused a track (%s); %d of %d sent, the rest go "
            "on beat's next dispatch",
            job.id,
            exc,
            sent,
            len(ordered),
        )
        _set_marker(db, job, ordered[sent:], lease, datetime.now(timezone.utc))
    _set_marker(db, job, ordered[:sent], lease, None)


def _due_case(track_ids: list[uuid.UUID], at: datetime):
    """A marker per track, a microsecond apart in `track_ids`' order (as `_mark_due`)."""
    return case(
        {track_id: at + timedelta(microseconds=index) for index, track_id in enumerate(track_ids)},
        value=Track.id,
    )


def _lock_job(db, job: Job) -> None:
    """The job's row lock, taken before this module's bulk UPDATEs of its tracks: cancel_job
    takes it before its own, so the two serialize instead of locking the same track rows in
    different orders (a deadlock)."""
    db.execute(select(Job.id).where(Job.id == job.id).with_for_update())


def _set_marker(db, job: Job, track_ids: list[uuid.UUID], lease: datetime, marker: datetime | None) -> None:
    """Ends this run's lease on `track_ids`: clears the marker (sent), or sets it due at
    `marker`, a microsecond apart in `track_ids`' order, as `_mark_due` does.

    A sent track may already be downloading or settled when its marker is cleared, so the
    clear matches the lease alone (a track download_track rescheduled has another
    `scheduled_at`). Only a still-`pending` one is put back due."""
    if not track_ids:
        return
    where = [Track.id.in_(track_ids), Track.scheduled_at == lease]
    if marker is None:
        value = None
    else:
        where.append(Track.state == TrackState.PENDING)
        value = _due_case(track_ids, marker)
    _lock_job(db, job)
    db.execute(update(Track).where(*where).values(scheduled_at=value).execution_options(synchronize_session=False))
    db.commit()


def _enqueue_pending_tracks(db, job: Job, why: str) -> None:
    """Enqueues `job`'s tracks still `pending`. For a job whose EXPANDED commit landed but
    whose enqueue loop never ran to the end -- the task was killed (and redelivered), or
    the refresh/publish right after the commit raised. Each is marked due first (v56,
    E1), so one this run can't send is beat's. A pending track that the interrupted run
    did enqueue gets a second message; download_track drops any message whose track has
    already moved on to `waiting`/`lookup_failed`, so it can't jump the retry ladder."""
    pending = [
        track_id
        for (track_id,) in db.query(Track.id)
        .filter(Track.job_id == job.id, Track.state == TrackState.PENDING)
        .order_by(Track.scheduled_at.asc().nulls_last())
    ]
    logger.info("expand_job: job %s %s; enqueueing %d pending tracks", job.id, why, len(pending))
    if not pending:
        return
    # A conditional UPDATE, not the loaded rows written back: one may have been dispatched
    # and rescheduled since (worker-dl's `waiting` slot must stay as it set it).
    _lock_job(db, job)
    db.execute(
        update(Track)
        .where(Track.id.in_(pending), Track.state == TrackState.PENDING)
        .values(scheduled_at=_due_case(pending, datetime.now(timezone.utc)))
        .execution_options(synchronize_session=False)
    )
    db.commit()
    _dispatch_due(db, job, pending)


def _reexpand(db, job_id: str) -> None:
    """v63's re-expand mode: reads the job's link again and adds only the tracks whose Spotify
    id the job doesn't have yet. A track gone from the playlist stays in the job. A new track
    already in the ledger is added all the same, and download_track resolves it as
    `skipped_duplicate` at once. Its new tracks go through the same outbox marker as a first
    expansion's, and wait out the breaker like any other.

    An error reading the link leaves the job as it was: the next scheduled run tries again.

    Every run that read the job ends with its `expanded` event, new tracks or not, so the row
    re-reads its watch (the next check moved when the run was claimed)."""
    job = db.get(Job, uuid.UUID(job_id))
    if job is None or job.state != JobState.EXPANDED or job.archived_at is not None:
        logger.info("expand_job: job %s isn't an expanded, unarchived job; not re-expanding", job_id)
        return
    source_url, user_id = job.source_url, job.user_id
    # The Spotify round trips can take minutes: never with a transaction open across them.
    db.commit()
    try:
        songs = expansion.expand(source_url)
    except Exception as exc:
        logger.warning("expand_job: job %s couldn't be re-expanded: %s", job_id, exc)
        events.publish_job_event(user_id, job.id, JobState.EXPANDED.value, watch=True)
        return

    # The job's row lock, as a first expansion's commit and cancel_job take it: a cancel
    # either lands first (and nothing is added) or cancels these tracks too.
    _lock_job(db, job)
    db.refresh(job)
    if job.state != JobState.EXPANDED or job.archived_at is not None:
        db.rollback()
        logger.info("expand_job: job %s is %s meanwhile; not re-expanding", job_id, job.state.value)
        return
    known = set(db.execute(select(Track.spotify_track_id).where(Track.job_id == job.id)).scalars())
    # One stamp for the whole batch, read off the clock rather than the transaction's `now()`:
    # watch.new_track_counts tells a re-expansion's tracks from the first expansion's by being
    # later, and a batch's by sharing it (a job whose first expansion found nothing counts its
    # first re-expansion's tracks as its first).
    stamp = db.execute(select(func.clock_timestamp())).scalar_one()
    tracks = []
    for song in songs:
        if not song.song_id or song.song_id in known:
            continue
        known.add(song.song_id)
        track = Track(job_id=job.id, spotify_track_id=song.song_id, song_json=song.json, created_at=stamp)
        db.add(track)
        tracks.append(track)
    _mark_due(tracks, datetime.now(timezone.utc))
    db.commit()
    logger.info(
        "expand_job: job %s re-expanded: %d new of %d tracks read", job_id, len(tracks), len(songs)
    )
    # The row re-reads its counts (and an open job its tracks) on `expanded`, the event a
    # first expansion sends; with new tracks its rollup moves back to `active` (v62's job.status).
    # With none, only the row re-reads (`watch`): an open job's list keeps its loaded pages.
    events.publish_job_event(user_id, job.id, job.state.value, watch=not tracks)
    if not tracks:
        return
    job_status.publish_change(db, job.id)
    _dispatch_due(db, job, [track.id for track in tracks])


# v53: nothing reads its result, and storing one made every enqueue wait on the result
# backend: with Redis down, its 20 reconnect retries held a job create about 19s.
@celery_app.task(name="app.tasks.expand.expand_job", ignore_result=True)
def expand_job(job_id: str, reexpand: bool = False) -> None:
    """`reexpand` (v63): a watched job's scheduled run or "check now" (see _reexpand)."""
    if reexpand:
        db = SessionLocal()
        try:
            _reexpand(db, job_id)
        finally:
            db.close()
            watch.release_run(job_id)
        return
    db = SessionLocal()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None:
            logger.warning("expand_job: job %s not found", job_id)
            return
        # Cancelled while still queued for worker-expand: the user said "don't download
        # this", so don't even spend the Spotify round trips (minutes, for an artist).
        # `failed` likewise has nothing left to do.
        if job.state in (JobState.CANCELLED, JobState.FAILED):
            logger.info("expand_job: job %s is %s, not expanding; skipping", job_id, job.state.value)
            return
        # A redelivery (acks_late) of a run that committed EXPANDED but died before it
        # finished enqueueing: the tracks exist, so don't re-expand (that would insert
        # every track a second time).
        if job.state == JobState.EXPANDED:
            _enqueue_pending_tracks(db, job, "already expanded (redelivery)")
            # v62 (F1): its expanding -> active move may never have been announced (review round 6).
            job_status.publish_change(db, job.id)
            return

        events.publish_job_event(job.user_id, job.id, job.state.value)

        try:
            songs = expansion.expand(job.source_url)
            tracks = []
            for song in songs:
                track = Track(
                    job_id=job.id,
                    spotify_track_id=song.song_id,
                    song_json=song.json,
                )
                db.add(track)
                tracks.append(track)

            # A conditional UPDATE, not a blind attribute assignment: expansion is a
            # multi-second Spotify round trip, long enough for a `DELETE /api/jobs/{id}`
            # cancel to land mid-flight. A plain `job.state = EXPANDED; db.commit()` would
            # silently clobber that cancel back to `expanded`. The WHERE clause makes the
            # write a no-op if the row moved on while we were running, and db.refresh
            # reads the row's real current state afterward rather than trusting the
            # `job` object loaded at task start.
            result = db.execute(
                update(Job)
                .where(Job.id == job.id, Job.state == JobState.EXPANDING)
                .values(state=JobState.EXPANDED)
            )
            if result.rowcount == 1:
                # Due only once the job is really EXPANDED: a job cancelled mid-expansion
                # commits its tracks unmarked (they're cancelled just below), so beat can't
                # send one in between.
                _mark_due(tracks, datetime.now(timezone.utc))
            if result.rowcount == 0:
                db.refresh(job)
                already_has_tracks = (
                    db.query(Track.id).filter(Track.job_id == job.id).first() is not None
                )
                if job.state != JobState.CANCELLED or already_has_tracks:
                    # Another run of this same job (a redelivery overlapping the
                    # original) already expanded it -- and possibly the user cancelled it
                    # since: its tracks are the real ones, so drop this run's uncommitted
                    # copies instead of committing a second set.
                    db.rollback()
                    logger.info(
                        "expand_job: job %s was expanded by another run; discarding this one's tracks",
                        job_id,
                    )
                    return
            db.commit()
            db.refresh(job)

            if job.state == JobState.CANCELLED:
                for track in tracks:
                    track.state = TrackState.CANCELLED
                db.commit()
                for track in tracks:
                    events.publish_track_event(
                        job.user_id,
                        track.id,
                        track.job_id,
                        track.state.value,
                        **track_song_meta(track.song_json),
                    )
                return

            events.publish_job_event(job.user_id, job.id, job.state.value)
            job_status.publish_change(db, job.id)
        except Exception as exc:
            # Covers both expansion.expand() itself (assorted exception types spotdl raises
            # for malformed/unreachable URLs) and any DB error while inserting tracks (e.g. a
            # NOT NULL violation from a song missing spotify_track_id) — either way the job
            # must land in `failed` with a readable error, never hang in `expanding` forever.
            logger.warning("expand_job: job %s failed to expand: %s", job_id, exc)
            db.rollback()
            # Conditional for the same reason as the success path's UPDATE: a cancel that
            # landed mid-expansion must stay `cancelled`. The user already said "don't
            # download this"; relabelling it `failed` afterwards would put it back in
            # their incoming list as an error they never asked about.
            result = db.execute(
                update(Job)
                .where(Job.id == job.id, Job.state == JobState.EXPANDING)
                .values(state=JobState.FAILED, error=str(exc))
            )
            db.commit()
            if result.rowcount == 0:
                db.refresh(job)
                if job.state == JobState.EXPANDED:
                    # The failure came *after* the EXPANDED commit (e.g. the refresh or
                    # a publish above raised): the tracks are committed, so enqueue them
                    # rather than leave them `pending` forever under an acked task.
                    _enqueue_pending_tracks(db, job, "failed after its EXPANDED commit")
                    # v62 (F1): its expanding -> active move may never have been announced (review round 6).
                    job_status.publish_change(db, job.id)
                    return
                logger.info(
                    "expand_job: job %s is %s, not expanding; not marking it failed",
                    job_id,
                    job.state.value,
                )
                return
            db.refresh(job)
            events.publish_job_event(job.user_id, job.id, job.state.value, error=job.error)
            job_status.publish_change(db, job.id)
        else:
            _dispatch_due(db, job, [track.id for track in tracks])
    finally:
        db.close()
