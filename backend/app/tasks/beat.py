import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, or_, select, update

from app.config import get_settings
from app.db import SessionLocal
from app.models import Job, JobState, Track, TrackAttemptOutcome, TrackState, UserSettings
from app.services import alerts, archive, attempts, events, job_status, retry, watch
from app.services.serializers import track_song_meta
from app.tasks.celery_app import celery_app
from app.tasks.download import download_track
# A module, not the task: celery_app imports this module while tasks.expand is still loading.
from app.tasks import expand as expand_tasks

logger = logging.getLogger(__name__)


def stale_track_after() -> timedelta:
    """A track stuck in DOWNLOADING/QUEUED past this long means whatever was supposed to
    finish it (a crashed worker, a container restart during a hard-killed download) never
    did. celery_app.py's task_acks_late + visibility_timeout is the primary redelivery
    mechanism for this; the sweep below is the independent DB-level safety net for cases
    that mechanism doesn't cover (e.g. a message already acked by a pre-fix worker, or the
    broker losing state). Read from settings (not a module constant) so
    STALE_TRACK_AFTER_SECONDS can be shortened for verification the same way
    LADDER_SECONDS already is — the 1800s production default would otherwise make manually
    confirming this sweep fires a 30-minute wait. With worker-dl's --concurrency=1,
    reclaiming a track that's genuinely still running just means a duplicate message,
    which download_track's finished/waiting gates drop once the first invocation is done
    (v35 (c), v34.1); the running invocation's real outcome then
    supersedes the reclaim's `failed` row (v55, E3), so its attempt is counted once."""
    return timedelta(seconds=get_settings().stale_track_after_seconds)


def _reclaim_stale_tracks(db) -> None:
    now = datetime.now(timezone.utc)
    threshold = stale_track_after()
    stale_cutoff = now - threshold

    # Snapshot state/updated_at *before* the update below, rather than reading
    # them back via that update's own RETURNING -- SQLAlchemy 2.0's ORM-enabled bulk
    # UPDATE (built from the mapped class, as below) still populates a column's
    # Python-side `onupdate` for every row it touches even when that column is never
    # named in `.values()`, so `Track.updated_at` in the RETURNING result would already
    # be "now", not the moment this track actually got stuck.
    stale_before = {
        row.id: (row.state, row.updated_at)
        for row in db.execute(
            select(Track.id, Track.state, Track.updated_at).where(
                Track.state.in_([TrackState.DOWNLOADING, TrackState.QUEUED]),
                Track.updated_at < stale_cutoff,
            )
        )
    }
    if not stale_before:
        return

    # v55 (E2): the UPDATE re-checks each row's snapshotted state and staleness, so a track
    # that moved on after the snapshot (a download committing `completed`, a queued message
    # starting its `downloading` write) is left alone. Postgres re-evaluates this WHERE on
    # the newest row version once a concurrent writer's lock is released, so the check holds
    # even when the two commits race on the same row.
    stuck_ids_by_state = {
        state: [track_id for track_id, (snap, _) in stale_before.items() if snap == state]
        for state in (TrackState.DOWNLOADING, TrackState.QUEUED)
    }
    reclaimed = db.execute(
        update(Track)
        .where(
            or_(
                *(
                    and_(Track.id.in_(ids), Track.state == state)
                    for state, ids in stuck_ids_by_state.items()
                    if ids
                )
            ),
            Track.updated_at < stale_cutoff,
        )
        .values(state=TrackState.WAITING, scheduled_at=now)
        .returning(Track.id, Track.job_id, Track.song_json)
    ).all()
    if not reclaimed:
        db.commit()
        return

    # One bulk lookup for every reclaimed track's owner, never a per-row query
    # (CLAUDE.md invariant) -- the RETURNING clause above only has job_id to offer.
    job_ids = {job_id for _, job_id, _ in reclaimed}
    owner_by_job = dict(db.execute(select(Job.id, Job.user_id).where(Job.id.in_(job_ids))).all())
    recorded_by_track = {}
    for track_id, job_id, song_json in reclaimed:
        stuck_state, stuck_since = stale_before[track_id]
        logger.warning(
            "dispatch_due_tracks: reclaimed stale track %s (stuck past %s)",
            track_id,
            threshold,
        )
        # v31: this sweep used to be the one code path that could silently swallow an
        # attempt -- a track stuck past the staleness threshold got reset with no
        # `track_attempts` row at all, an invisible gap in the per-attempt history v24
        # exists specifically to close. Whatever invocation got this track stuck never
        # reached its own record_attempt call (that's what "stuck" means here), so this
        # sweep records it on that invocation's behalf: FAILED, no known error_type since
        # the real cause (crashed worker, hard-killed container) was never observed.
        if stuck_state == TrackState.DOWNLOADING:
            recorded = attempts.record_attempt(
                db,
                track_id,
                stuck_since,
                now,
                TrackAttemptOutcome.FAILED,
                error_message=f"{attempts.RECLAIM_PREFIX}stuck past staleness threshold ({threshold})",
            )
        else:
            # v35: stuck `queued` means its message hadn't reached the network yet (it
            # never ran, or is still in download_track's pacing wait) -- rescheduled
            # without an attempt, which is what `held` records. Neither an attempt nor a
            # failure, and not rendered as one. A message that hasn't started yet is then
            # dropped by download_track's waiting gate; one mid-pacing-wait sees this row
            # after its sleep and exits without downloading (v55, E4).
            recorded = attempts.record_attempt(
                db,
                track_id,
                stuck_since,
                now,
                TrackAttemptOutcome.HELD,
                warning_message=(
                    f"{attempts.RECLAIM_PREFIX}still queued past staleness threshold ({threshold})"
                ),
            )
        recorded_by_track[track_id] = recorded
    # v55 (E3): one commit for the reset and its rows. v35 committed the reset first and each
    # row after, which left a window where a still-running download's real outcome could land
    # between them, find no reclaim row to supersede, and be counted a second time. The UPDATE
    # above already holds every reclaimed row's lock, so record_attempt's locks wait on
    # nothing new (the deadlock v35 avoided needed a lock taken per track inside the loop).
    db.commit()
    for track_id, job_id, song_json in reclaimed:
        recorded = recorded_by_track[track_id]
        events.publish_track_event(
            owner_by_job[job_id],
            track_id,
            job_id,
            TrackState.WAITING.value,
            scheduled_at=now,
            attempts_made=recorded.attempts_made,
            failure_count=recorded.failure_count,
            **track_song_meta(song_json),
        )
    # v62 (F1): a reclaim can turn a job `waiting`; one bulk status check for its jobs.
    job_status.publish_changes(db, job_ids)


def _dispatch_due_watched_jobs(db) -> None:
    """v63: starts the re-expansion of each watched job that is due, within the hourly cap
    (`REEXPAND_MAX_PER_HOUR`, counting every re-expansion started in the last hour, "check now"
    included). The rest stay due, and a later tick starts them once the hour has room: their
    `next_expand_at` is the only schedule (Postgres, never a Celery ETA). A due job with a
    re-expansion already queued or running ("check now") is left to it; that run has moved its
    `next_expand_at` on already.

    Runs whether or not the breaker holds: a re-expansion reads metadata only, and its new
    tracks wait like any other."""
    now = datetime.now(timezone.utc)
    watch.lock_cap(db)
    budget = get_settings().reexpand_max_per_hour - watch.started_this_hour(db, now)
    if budget <= 0:
        db.commit()
        return
    due = (
        db.execute(
            select(Job)
            .where(
                Job.watch_interval_hours.is_not(None),
                Job.next_expand_at <= now,
                Job.archived_at.is_(None),
                Job.state == JobState.EXPANDED,
                Job.source_type.in_(watch.WATCHABLE_SOURCE_TYPES),
            )
            .order_by(Job.next_expand_at.asc())
            # Room for jobs whose marker is held (skipped below) without locking every due row.
            .limit(budget + 20)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    started = []
    for job in due:
        # A job whose run is already queued or running ("check now") takes no slot of the
        # hour's budget (review round 6): the next due one does.
        if len(started) >= budget:
            break
        try:
            token = watch.claim_run(job.id)
        except watch.MarkerUnavailable as exc:
            logger.warning("dispatch_due_tracks: no watched job started, Redis unavailable: %s", exc)
            break
        if token is None:
            continue
        previous_last, previous_next = job.last_expanded_at, job.next_expand_at
        watch.mark_started(job, now)
        started.append((job.id, token, previous_last, previous_next, job.next_expand_at))
    try:
        db.commit()
    except Exception:
        # Nothing was queued: the markers mustn't hold these jobs "running" until they expire.
        for job_id, token, *_times in started:
            watch.release_run(job_id, token)
        raise
    for job_id, token, last_expanded_at, next_expand_at, ours_next in started:
        try:
            expand_tasks.expand_job.delay(str(job_id), reexpand=True, marker=token)
        except Exception as exc:
            # The broker refused it: due again on the next tick, and not counted. Only what
            # this tick wrote is put back: an interval changed (or a watch stopped) meanwhile
            # keeps its own next check.
            logger.warning("dispatch_due_tracks: watched job %s not started: %s", job_id, exc)
            db.execute(
                update(Job)
                .where(Job.id == job_id, Job.last_expanded_at == now)
                .values(
                    last_expanded_at=last_expanded_at,
                    next_expand_at=case(
                        (Job.next_expand_at.is_not_distinct_from(ours_next), next_expand_at),
                        else_=Job.next_expand_at,
                    ),
                )
            )
            db.commit()
            watch.release_run(job_id, token)
            continue
        logger.info("dispatch_due_tracks: watched job %s re-expansion started", job_id)


@celery_app.task(name="app.tasks.beat.dispatch_due_tracks")
def dispatch_due_tracks() -> None:
    # v36: written first, on every tick -- the alert watchdog (worker-meta, not beat)
    # reads its age to notice a dead beat. A tick that then errors still proves beat alive.
    alerts.record_beat_heartbeat()
    db = SessionLocal()
    try:
        # Independent of the breaker/pause gate below — a stuck track needs reclaiming
        # regardless, it just won't be re-dispatched until the breaker clears.
        _reclaim_stale_tracks(db)

        now = datetime.now(timezone.utc)
        worker_state = retry.get_worker_state(db)
        # v44: a trip's pause that has run out is recorded as released (breaker_events),
        # by the first tick to see it. Checked unlocked first: the locked re-read inside
        # only happens once per trip, never on an ordinary tick.
        if worker_state.breaker_tripped_until is not None and not retry.breaker_tripped(
            worker_state, now
        ):
            retry.record_breaker_release(db, now, end_running=False)
        db.commit()
        # v63: before the breaker's gate (metadata only), and never in the way of the tracks'.
        try:
            _dispatch_due_watched_jobs(db)
        except Exception:
            logger.exception("dispatch_due_tracks: the watched-job pass failed")
            db.rollback()
        if retry.breaker_active(worker_state, now):
            # No query at all while tripped/paused — avoids a thundering herd of tracks
            # all becoming due at once right when the breaker releases.
            return

        due_rows = db.execute(
            select(Track, Job.user_id)
            .join(Job, Track.job_id == Job.id)
            # v56 (E1): `pending` too, with expand_job's outbox marker (tasks/expand.py): a
            # track its broker send never reached is due here, never stranded.
            .where(Track.state.in_((TrackState.WAITING, TrackState.PENDING)), Track.scheduled_at <= now)
            .order_by(Job.priority.desc(), Track.scheduled_at.asc())
            .with_for_update(skip_locked=True, of=Track)
        ).all()
        due_tracks = [track for track, _ in due_rows]
        for track in due_tracks:
            track.state = TrackState.QUEUED
        db.commit()

        for track, user_id in due_rows:
            events.publish_track_event(
                user_id,
                track.id,
                track.job_id,
                track.state.value,
                attempt_count=track.attempt_count,
                **track_song_meta(track.song_json),
            )

        # v62 (F1): a `waiting` track's dispatch can turn its job `active` again; one bulk
        # status check for the jobs dispatched. Before the sends (the commit above already made
        # the moves), so a broker error part-way can't leave them unpublished (review round 2);
        # it ends the transaction, so the ids are read first.
        track_ids = [str(track.id) for track in due_tracks]
        job_status.publish_changes(db, {track.job_id for track in due_tracks})

        for track_id in track_ids:
            download_track.delay(track_id)
    finally:
        db.close()


@celery_app.task(name="app.tasks.beat.archive_due_jobs")
def archive_due_jobs() -> None:
    """Hourly (not every 30s like dispatch_due_tracks -- this is housekeeping, and it
    competes with that task for the same worker-meta process). Iterates every user with
    a non-null `retention_days` and archives their eligible jobs older than that many
    days; a null retention_days (the default) means this user is never touched."""
    db = SessionLocal()
    try:
        user_rows = db.execute(
            select(UserSettings.user_id, UserSettings.retention_days).where(
                UserSettings.retention_days.is_not(None)
            )
        ).all()
        for user_id, retention_days in user_rows:
            jobs = archive.archive_jobs(db, user_id, older_than=timedelta(days=retention_days))
            for job in jobs:
                logger.info("archive_due_jobs: archived job %s for user %s", job.id, user_id)
                events.publish_job_event(user_id, job.id, job.state.value, archived=True)
    finally:
        db.close()
