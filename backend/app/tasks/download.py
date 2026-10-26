import logging
import random
import time
import uuid
from datetime import datetime, timezone

from spotdl.types.song import Song
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    DownloadedTrack,
    Job,
    NetworkPath,
    Track,
    TrackAttemptOutcome,
    TrackErrorType,
    TrackState,
)
from app.services import app_settings, attempts, dedup, downloads, events, proxies, retry, tagging
from app.services import network_path as network_path_svc
from app.services.serializers import track_song_meta
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# v55 (E12): the note on an attempt that took the proxy rung early because IPv6 isn't
# routable here (its network_path shows the proxy, or forced IPv4 with no proxy available).
IPV6_RUNG_SKIPPED = "IPv6 isn't routable from this worker; skipped the direct IPv6 rung"


def _notes(*notes: str | None) -> str | None:
    """The non-empty notes for one attempt row's warning_message, or None."""
    return "; ".join(note for note in notes if note) or None


def pacing_delay() -> float:
    """Seconds to wait before this track's download attempt -- a uniform sample from
    [PACING_MIN_SEC, PACING_MAX_SEC], or 0.0 when the hook is off (the default).

    Returns 0.0 rather than sleeping 0 so "off" means this code path never executes --
    that's what the default-behavior regression test asserts. Not underscore-prefixed
    because the sampling-window test calls it directly, same reasoning as
    beat.stale_track_after()."""
    settings = get_settings()
    if settings.pacing_max_sec <= 0:
        return 0.0
    # Belt-and-braces: config.py's model_validator rejects min > max at startup, but a
    # reversed window would otherwise make random.uniform silently sample the inverted
    # range instead of failing.
    low = max(0, min(settings.pacing_min_sec, settings.pacing_max_sec))
    return random.uniform(low, settings.pacing_max_sec)


def _lock_if_still_owned(db: Session, track: Track, entry_state: TrackState, entry_attempt: int) -> bool:
    """Row-locks the track, reloaded, and says whether this invocation still owns it: the
    state it found on entry, and no row recorded since (v55, E4/E5). A write made under the
    lock can't be overtaken by a cancel or a reclaim: theirs waits for this transaction, and
    one that committed first is seen here. The same claim as the `downloading` write, for
    the gate writes before it (review round 1: the same plain-assignment race)."""
    db.refresh(track, with_for_update=True)
    return track.state == entry_state and not db.execute(
        select(attempts.recorded_since(track.id, entry_attempt))
    ).scalar()


def _hold(
    db: Session,
    track: Track,
    owner_id: uuid.UUID,
    attempt_started_at: datetime,
    scheduled_at: datetime,
    reason: str,
    entry_state: TrackState,
    entry_attempt: int,
) -> None:
    """Puts a track back to `waiting` until `scheduled_at` without attempting it.

    Deliberately doesn't touch track.attempt_count -- doing so would make the real attempt
    that eventually follows read attempt_count >= 1 and wrongly reach for a proxy, breaking
    "attempt 1 is always direct". v35: recorded as `held`, not `failed`, so it counts as
    neither an attempt nor a failure, and it gets its own attempt_number rather than sharing
    the next real attempt's. v55 (E11): a hold straight after an identical one extends that
    row (hold_count) instead of adding another. A track cancelled since entry stays
    cancelled: a plain write here turned it back to `waiting`, to download after the hold."""
    if not _lock_if_still_owned(db, track, entry_state, entry_attempt):
        _give_up_claim(db, track, attempt_started_at, "before its hold")
        return
    track.state = TrackState.WAITING
    track.scheduled_at = scheduled_at
    attempts.record_attempt(
        db,
        track.id,
        attempt_started_at,
        datetime.now(timezone.utc),
        TrackAttemptOutcome.HELD,
        warning_message=reason,
        collapse_hold=True,
    )
    db.commit()
    events.publish_track_event(
        owner_id,
        track.id,
        track.job_id,
        track.state.value,
        scheduled_at=track.scheduled_at,
        attempt_count=track.attempt_count,
        attempts_made=track.attempts_made,
        failure_count=track.failure_count,
        **track_song_meta(track.song_json),
    )


def _give_up_claim(db: Session, track: Track, attempt_started_at: datetime, when: str) -> None:
    """This invocation lost the track to a cancel or a reclaim (v55, E4/E5) and exits without
    downloading. A cancel gets its `cancelled` row as before; a reclaim already recorded its
    own row for the track, and beat dispatches it again, so nothing more is written."""
    db.refresh(track)
    if track.state == TrackState.CANCELLED:
        logger.info("download_track: track %s was cancelled %s, skipping", track.id, when)
        attempts.record_attempt(
            db,
            track.id,
            attempt_started_at,
            datetime.now(timezone.utc),
            TrackAttemptOutcome.CANCELLED,
        )
    else:
        logger.info(
            "download_track: track %s was taken from this invocation %s (now %s), skipping",
            track.id,
            when,
            track.state.value,
        )
    db.commit()


def _record_mid_download_cancel(
    db: Session,
    track: Track,
    owner_id: uuid.UUID,
    attempt_started_at: datetime,
    proxy_id: uuid.UUID | None,
    chosen_path: NetworkPath | None,
    entry_attempt: int,
    track_meta: dict,
    rung_note: str | None,
) -> None:
    """A cancel landed while the download ran: its network attempt is recorded as
    `cancelled`, then the `cancelled` event goes out. v55 (E6): the event comes after the
    row is committed and carries the counters it moved, so a live row's counts are right
    without a reload (the event used to go out first, with none)."""
    recorded = attempts.record_attempt(
        db,
        track.id,
        attempt_started_at,
        datetime.now(timezone.utc),
        TrackAttemptOutcome.CANCELLED,
        warning_message=rung_note if chosen_path is not None else None,
        proxy_id=proxy_id,
        network_path=chosen_path,
        supersede_reclaim_after=entry_attempt,
    )
    db.commit()
    events.publish_track_event(
        owner_id,
        track.id,
        track.job_id,
        TrackState.CANCELLED.value,
        attempt_count=track.attempt_count,
        attempts_made=recorded.attempts_made,
        failure_count=recorded.failure_count,
        **track_meta,
    )


@celery_app.task(name="app.tasks.download.download_track")
def download_track(track_id: str) -> None:
    db = SessionLocal()
    try:
        # owner_id is captured as a plain UUID, not read off an ORM-attached Job, so it
        # survives the db.rollback() in the failure branch below and stays usable for
        # every publish call in this task, including the ones after a rollback.
        row = (
            db.query(Track, Job.user_id)
            .join(Job, Track.job_id == Job.id)
            .filter(Track.id == uuid.UUID(track_id))
            .one_or_none()
        )
        if row is None:
            logger.warning("download_track: track %s not found", track_id)
            return
        track, owner_id = row

        # One track_attempts row per invocation of this task (v24). Its attempt_number is
        # assigned by attempts.record_attempt as a per-track sequence (v35), independent
        # of tracks.attempt_count, which stays the ladder's failure count.
        attempt_started_at = datetime.now(timezone.utc)

        # A cancel can land between beat's dispatch (or expand_job's immediate first
        # dispatch) and this task actually executing — e.g. a track sitting `queued` in
        # Celery's broker while the user cancels its job. Nothing upstream guarantees a
        # cancelled track is never enqueued, so this is the actual gate.
        if track.state == TrackState.CANCELLED:
            logger.info("download_track: track %s was cancelled before dispatch, skipping", track_id)
            attempts.record_attempt(
                db,
                track.id,
                attempt_started_at,
                datetime.now(timezone.utc),
                TrackAttemptOutcome.CANCELLED,
            )
            db.commit()
            return

        # v34.1: a message is only ever sent for a `pending` (expand_job) or `queued`
        # (beat's dispatch) track, and a crash redelivery can find it `downloading`. One
        # that finds it `waiting` or `lookup_failed` is stray -- e.g. a duplicate sent by
        # expand_job re-enqueueing an interrupted run's pending tracks, landing after the
        # first message's attempt already failed into the ladder. Running it would jump
        # the ladder (an immediate retry, on the next rung) -- exactly the rate-limit
        # exposure this app exists to avoid -- so drop it: no attempt row, no event. Beat
        # dispatches the track again when it's actually due.
        if track.state in (TrackState.WAITING, TrackState.LOOKUP_FAILED):
            logger.info(
                "download_track: track %s is %s, not due; dropping stray message",
                track_id,
                track.state.value,
            )
            return

        # v35 (c): a redelivered message (acks_late after a worker crash, or a duplicate
        # send) for a track that already succeeded. Without this it fell through to the
        # dedup check below and rewrote a COMPLETED track to SKIPPED_DUPLICATE, its own
        # ledger row being the "duplicate". A terminal success is a no-op on redelivery:
        # no attempt row, no event, no state change.
        if track.state in (TrackState.COMPLETED, TrackState.SKIPPED_DUPLICATE):
            logger.info(
                "download_track: track %s is already %s; ignoring redelivered message",
                track_id,
                track.state.value,
            )
            return

        # v55 (E4/E5): what this invocation found, as its claim on the track. A message is
        # sent for a `pending` (expand_job) or `queued` (beat) track, and a crash redelivery
        # finds it `downloading`; it may only go on to download while the track is still in
        # that state and nothing has recorded a row for it since (beat's reclaim always does).
        entry_state = track.state
        entry_attempt = attempts.latest_attempt_number(db, track.id)

        # Covers the race where this task was already enqueued just before the breaker
        # tripped (or the worker was paused) — dispatch_due_tracks is the primary gate and
        # normally won't enqueue in this state at all.
        now = datetime.now(timezone.utc)
        worker_state = retry.get_worker_state(db)
        if retry.breaker_active(worker_state, now):
            _hold(
                db,
                track,
                owner_id,
                attempt_started_at,
                worker_state.breaker_tripped_until or (now + retry.next_delay(0)),
                "circuit breaker active; rescheduled without attempting",
                entry_state,
                entry_attempt,
            )
            return

        # v38: the ledger has a row but its file is missing under a root that looks
        # unmounted in this worker. Downloading would be the silent re-download v38 fixes
        # (worker-dl couldn't see the library at all before it); trusting the ledger would
        # mark the track a duplicate of a file nobody can confirm exists. Hold it instead,
        # like the breaker does: once the mount is back, the next dispatch resolves it.
        try:
            existing_path = dedup.is_already_downloaded(track.spotify_track_id)
        except dedup.LedgerRootUnavailable as exc:
            logger.error(
                "download_track: track %s's ledger file %s is under %s, which is missing or "
                "empty in this worker; holding it as waiting rather than downloading it again",
                track_id,
                exc.path,
                exc.root,
            )
            _hold(
                db,
                track,
                owner_id,
                attempt_started_at,
                now + retry.next_delay(0),
                f"{exc.root} is missing or empty; rescheduled without attempting",
                entry_state,
                entry_attempt,
            )
            return
        if existing_path is not None:
            if not _lock_if_still_owned(db, track, entry_state, entry_attempt):
                _give_up_claim(db, track, attempt_started_at, "before its duplicate resolved")
                return
            track.state = TrackState.SKIPPED_DUPLICATE
            track.output_path = str(existing_path)
            # v55 (E9): a resolved track keeps no stale failure.
            track.last_error = None
            track.last_error_type = None
            attempts.record_attempt(
                db,
                track.id,
                attempt_started_at,
                datetime.now(timezone.utc),
                TrackAttemptOutcome.SKIPPED_DUPLICATE,
            )
            db.commit()
            events.publish_track_event(
                owner_id,
                track.id,
                track.job_id,
                track.state.value,
                attempts_made=track.attempts_made,
                failure_count=track.failure_count,
                **track_song_meta(track.song_json),
            )
            return

        # Pacing hook (declared since v07, actually consumed as of v15). Deliberately
        # placed *after* the cancel/breaker/dedup gates above: a track that's never going
        # to touch the network must not burn wall-clock waiting to not touch it.
        # worker-dl is --concurrency=1 --prefetch-multiplier=1, so tasks run strictly
        # serially and sleeping here is literally what spaces out consecutive attempts.
        delay = pacing_delay()
        if delay > 0:
            # db.get(Track) above (and get_worker_state's possible get-or-create) opened
            # a transaction nothing has closed yet. Commit before sleeping rather than
            # pinning a pooled Postgres connection idle-in-transaction for the whole
            # window -- same get-then-commit shape dispatch_due_tracks already uses.
            db.commit()
            logger.info(
                "download_track: pacing %.1fs before track %s",
                delay,
                track_id,
            )
            time.sleep(delay)
            # A cancel or beat's stale reclaim can land during the wait. Without this the
            # download ran anyway; a reclaimed track was then downloaded twice, once here and
            # once by the message beat sends it again (v55, E4). Checked here, before the
            # proxy rung's TCP probes, as well as by the claim further down.
            owned = db.execute(
                select(Track.id).where(
                    Track.id == track.id,
                    Track.state == entry_state,
                    ~attempts.recorded_since(track.id, entry_attempt),
                )
            ).one_or_none()
            if owned is None:
                _give_up_claim(db, track, attempt_started_at, "during the pacing wait")
                return

        output_settings = app_settings.get_output_settings(db)

        # Ladder rungs (v29 inserts the forced-other-family rung before proxy, per the
        # locked "direct first -> wait out the ladder -> then proxy" strategy): attempt 1
        # is direct on the default family (IPv4 -- forced explicitly rather than left to
        # "whatever the OS picks", so this row's recorded network_path is deterministic;
        # harmless since IPv4 is already the only routable family in every environment
        # this has shipped to so far, see docs/GOTCHAS.md's v29 entry). Attempt 2 is
        # direct, forced onto the *other* family. Only attempt 3+ reaches for a proxy.
        # v55 (E12): where IPv6 isn't routable the forced-IPv6 attempt could only fail, after
        # a whole ladder wait, so attempt 2 goes straight to the proxy rung instead. The
        # ladder's delays are untouched; only the path changes, and the row says why.
        rung_note = None
        if track.attempt_count == 0:
            chosen_path = NetworkPath.DIRECT_IPV4
            proxy = None
        elif track.attempt_count == 1 and network_path_svc.ipv6_routable():
            chosen_path = NetworkPath.DIRECT_IPV6
            proxy = None
        else:
            if track.attempt_count == 1:
                rung_note = IPV6_RUNG_SKIPPED
            # pick_proxy returns None whenever every proxy is disabled/in cooldown -- a
            # routine state, not an edge case, for a handful of proxies. chosen_path must
            # be derived from what pick_proxy actually returned, not assumed, or a
            # no-proxy-available fallback attempt (a plain, unforced direct connection)
            # gets mislabeled as NetworkPath.PROXY in track_attempts even though no proxy
            # was used. Falling back to DIRECT_IPV4 (not leaving it unforced) matches
            # attempt 1's own "forced explicitly, not left to whatever the OS picks"
            # determinism above, and keeps every stored network_path value truthful.
            # v40.1: pick_proxy now TCP-probes candidates (up to 2s per dead one), so
            # commit first rather than holding this transaction open across the probes,
            # and commit the cooldowns it records right after.
            db.commit()
            proxy = proxies.pick_proxy(db)
            chosen_path = NetworkPath.PROXY if proxy is not None else NetworkPath.DIRECT_IPV4
            # Read before the commit expires the row: reloading it afterwards would raise
            # outside the try below if an admin deleted the proxy in between.
            proxy_id = proxy.id if proxy is not None else None
            proxy_url = proxy.url if proxy is not None else None
            db.commit()
        if proxy is None:
            proxy_id = None
            proxy_url = None

        # v55 (E5): a conditional transition, not a plain assignment. A cancel or a reclaim
        # committed at any point since this invocation started (during the proxy probes
        # included) makes it match no row, where the old assignment overwrote it.
        claim = {"state": TrackState.DOWNLOADING}
        if proxy_id is not None:
            claim["used_proxy_id"] = proxy_id
        # v55 (E7): everything the download needs, read here, so nothing touches the ORM
        # between the commit below and the post-download refresh. Reading an expired row (or
        # the output settings row) after that commit opened a transaction that sat
        # `idle in transaction` for the whole download, and the completed row's updated_at
        # (Postgres' now(), the transaction's start) read as the download's start.
        track_uuid, job_id = track.id, track.job_id
        song_json, attempt_count = track.song_json, track.attempt_count
        output_format = output_settings.default_format
        output_bitrate = output_settings.default_bitrate
        output_template = output_settings.output_template
        track_meta = track_song_meta(song_json)
        claimed = db.execute(
            update(Track)
            .where(
                Track.id == track_uuid,
                Track.state == entry_state,
                ~attempts.recorded_since(track_uuid, entry_attempt),
            )
            .values(**claim)
            .returning(Track.id)
            .execution_options(synchronize_session=False)
        ).one_or_none()
        if claimed is None:
            db.rollback()
            _give_up_claim(db, track, attempt_started_at, "before its download started")
            return
        if proxy_id is not None:
            logger.info(
                "download_track: track %s attempting via proxy %s",
                track_id,
                proxies.redact(proxy_url),
            )
        db.commit()
        events.publish_track_event(
            owner_id,
            track_uuid,
            job_id,
            TrackState.DOWNLOADING.value,
            progress=0,
            attempt_count=attempt_count,
            **track_meta,
        )

        try:
            song = Song.from_dict(song_json)
            # output_dir stays env-sourced (never DB-editable, see app_settings.py's
            # docstring) -- the directory a container can actually write to is fixed by
            # its volume mount at deploy time, not by an app-level setting.
            downloader = downloads.get_downloader(
                output_format,
                output_bitrate,
                get_settings().download_output_dir,
                output_template,
                proxy=proxy_url,
                network_path=chosen_path,
            )
            # worker-dl runs a single track at a time (--concurrency=1), so it's safe to
            # rebind this per attempt rather than threading track/job ids through
            # get_downloader's cache key.
            downloader.progress_handler.update_callback = events.make_progress_callback(
                owner_id, track_uuid, job_id, attempt_count=attempt_count, **track_meta
            )
            # force_family covers ytmusicapi's search calls too, which have no
            # family-forcing knob of their own (see network_path.py's docstring) -- yt-dlp's
            # own requests are additionally forced via get_downloader's yt_dlp_args above.
            # force_proxy (v30) is the ytmusicapi-side half of the proxy fix: yt-dlp's own
            # requests already got a --proxy flag baked into yt_dlp_args by get_downloader
            # above, but ytmusicapi's search client is spotdl-hardcoded with no proxy knob
            # of its own -- see proxies.force_proxy's docstring for why this has to patch
            # the client-construction classmethod rather than an already-built instance.
            with network_path_svc.force_family(chosen_path), proxies.force_proxy(proxy_url, downloader):
                downloaded = downloads.download_one(song, downloader)
            output_path = downloaded.output_path

            # search_and_download is synchronous and not cleanly interruptible, so a
            # cancel requested while this was running couldn't stop it — it instead set
            # this row's state directly (from a separate request/session) and left the
            # download to just finish. db.refresh picks up that committed change; a
            # cancelled track's result is discarded rather than overwritten back to a
            # non-terminal state. v55: under the row lock, held to the commit below, so a
            # cancel landing after this check waits for it instead of being overwritten by
            # the outcome (review round 1).
            db.refresh(track, with_for_update=True)
            if track.state == TrackState.CANCELLED:
                logger.info(
                    "download_track: track %s was cancelled mid-download, discarding result",
                    track_id,
                )
                # The progress callback above published `downloading` events straight
                # through to 100% while the real (uninterruptible) download kept
                # running after the cancel landed — it has no idea a cancel happened,
                # it just reports spotdl's own tracker. Those stray events are already
                # on the wire, so a live SSE client's last-known state for this track
                # is one of them, not `cancelled`, even though the DB has been correct
                # the whole time. Re-publishing here makes `cancelled` provably the
                # last message for this track (nothing else publishes for it after
                # download_one has returned), so a connected browser converges to the
                # right state without needing a reload. Caught by live real-stack
                # testing, not by REST-polling: REST already reflected `cancelled`,
                # only the live view was stuck.
                if downloaded.skipped_existing:  # see the skip below: nothing went out
                    proxy_id, chosen_path = None, None
                _record_mid_download_cancel(
                    db,
                    track,
                    owner_id,
                    attempt_started_at,
                    proxy_id,
                    chosen_path,
                    entry_attempt,
                    track_meta,
                    rung_note,
                )
                return

            if output_path is None:
                raise retry.NoOutputFileError(
                    "spotdl returned no output file for this track"
                )

            # v31: found live, by this version's own real-album verification --
            # search_and_download's returned path is trusted completely with no check
            # that anything actually landed there. It can point at a file that was never
            # written (the confirmed mechanism: spotdl's own output-template renderer
            # drops the `{track-number} - ` segment entirely when a song's track_number
            # is 0/None, so a template built assuming that segment is always present
            # produces a path that doesn't match the real, differently-named file spotdl
            # actually wrote -- other, rarer causes are plausible too and this check
            # doesn't need to know which one applies). Before this check existed, a
            # missing file at this point wasn't just unnoticed -- the broad `except
            # Exception` around tag verification below would silently swallow the
            # FileNotFoundError that verify_tags raises against a nonexistent path,
            # turning "the download never actually happened" into a harmless-looking
            # "tag warning" on an otherwise-COMPLETED track. Classified the same as
            # `output_path is None` -- both mean spotdl didn't actually leave a file
            # where this app was told to expect one.
            if not output_path.exists():
                raise retry.NoOutputFileError(
                    f"spotdl reported {output_path} but no file exists there"
                )

            # ID3 integrity (v26): read tags back off the actual file rather than
            # trusting song_json, and repair anything missing before marking the track
            # completed. Guarded broadly -- a tag-repair bug must never turn a
            # successfully downloaded track into a failed one; the audio is already
            # correct and on disk regardless of what happens here.
            tag_warning = None
            try:
                if not tagging.is_supported_format(output_path):
                    logger.info(
                        "download_track: track %s format %s not supported for tag "
                        "verification, skipping",
                        track_id,
                        output_path.suffix,
                    )
                else:
                    missing = tagging.verify_tags(output_path)
                    if missing:
                        logger.info(
                            "download_track: track %s missing tags %s, repairing",
                            track_id,
                            sorted(missing),
                        )
                        tag_warning = tagging.repair_tags(output_path, song, missing)
            except Exception:
                logger.exception(
                    "download_track: track %s tag verification/repair failed "
                    "unexpectedly; audio is downloaded and correct regardless",
                    track_id,
                )
                tag_warning = "tag verification/repair failed unexpectedly"

            if downloaded.skipped_existing:
                # v55 (E8): spotdl's own "file already exists" skip. The file was there
                # before this attempt and nothing went to YouTube, so it is recorded the way
                # the dedup gate above records a ledger hit: `skipped_duplicate`, no network
                # path, no counter, no proxy or breaker verdict. The ledger gains the row it
                # was missing, so the next submission resolves at the gate. Its tags were
                # verified (and repaired) above like a fresh download's, as before v55.
                track.state = TrackState.SKIPPED_DUPLICATE
                track.output_path = str(output_path)
                track.last_error = None
                track.last_error_type = None
                db.merge(
                    DownloadedTrack(
                        spotify_track_id=track.spotify_track_id,
                        file_path=str(output_path),
                        format=output_format,
                        bitrate=output_bitrate,
                        in_library=False,
                    )
                )
                recorded = attempts.record_attempt(
                    db,
                    track.id,
                    attempt_started_at,
                    datetime.now(timezone.utc),
                    TrackAttemptOutcome.SKIPPED_DUPLICATE,
                    warning_message=_notes(
                        "spotdl found the file already in place; not downloaded again",
                        f"tag warning: {tag_warning}" if tag_warning else None,
                    ),
                    supersede_reclaim_after=entry_attempt,
                )
                db.commit()
                events.publish_track_event(
                    owner_id,
                    track.id,
                    track.job_id,
                    track.state.value,
                    attempts_made=recorded.attempts_made,
                    failure_count=recorded.failure_count,
                    **track_meta,
                )
                return

            track.state = TrackState.COMPLETED
            track.output_path = str(output_path)
            # in_library is set, not left out: merge copies only the attributes given, so a row
            # whose library file went missing and was downloaded again kept in_library=True on
            # its new /downloads path, and no sweep (which reads only in_library=False) would
            # ever file it (v48).
            db.merge(
                DownloadedTrack(
                    spotify_track_id=track.spotify_track_id,
                    file_path=str(output_path),
                    format=output_format,
                    bitrate=output_bitrate,
                    in_library=False,
                )
            )
            if proxy_id is not None:
                proxies.record_proxy_result(db, proxy_id, success=True)
            retry.record_success(db, track)
            finished_at = datetime.now(timezone.utc)
            attempts.record_attempt(
                db,
                track.id,
                attempt_started_at,
                finished_at,
                TrackAttemptOutcome.COMPLETED,
                proxy_id=proxy_id,
                warning_message=_notes(rung_note, f"tag warning: {tag_warning}" if tag_warning else None),
                network_path=chosen_path,
                supersede_reclaim_after=entry_attempt,
            )
            # v55 (E7): the completion's own time, set after record_attempt (its counter
            # UPDATE expires the attribute). The onupdate now() would be this transaction's
            # start, the refresh above, a little before the attempt's finished_at.
            track.updated_at = finished_at
            db.commit()
            events.publish_track_event(
                owner_id,
                track.id,
                track.job_id,
                track.state.value,
                attempts_made=track.attempts_made,
                failure_count=track.failure_count,
                **track_meta,
            )
        except Exception as exc:
            # Some exceptions (e.g. spotdl's DownloaderError for a malformed proxy) echo
            # the proxy string verbatim — never let that reach worker logs or the
            # DB-persisted last_error a future UI (v09+) will display. exc_info substitutes
            # a sanitized exception for the final "Type: message" line while keeping the
            # real traceback object, so file/line info is untouched.
            error_message = str(exc)
            log_exc = exc
            # v31: pattern-based, not an exact match against this attempt's own
            # proxy_url -- catches a credentialed URL embedded in a re-wrapped or
            # differently-formatted exception too (docs/GOTCHAS.md's v30 entry).
            # redact_text is a no-op on a message with nothing embedded, which is the
            # common case (spotdl/yt-dlp errors rarely echo the URL at all).
            redacted_message = proxies.redact_text(error_message)
            if redacted_message != error_message:
                error_message = redacted_message
                log_exc = type(exc)(error_message)
            logger.error(
                "download_track: track %s failed",
                track_id,
                exc_info=(type(exc), log_exc, exc.__traceback__),
            )
            db.rollback()
            # v55: locked, like the success path's refresh.
            track = db.get(Track, uuid.UUID(track_id), with_for_update=True, populate_existing=True)
            if track.state == TrackState.CANCELLED:
                logger.info(
                    "download_track: track %s was cancelled before this failure landed, "
                    "leaving it cancelled",
                    track_id,
                )
                # Same stray-progress-event race as the success path above.
                _record_mid_download_cancel(
                    db,
                    track,
                    owner_id,
                    attempt_started_at,
                    proxy_id,
                    chosen_path,
                    entry_attempt,
                    track_meta,
                    rung_note,
                )
                return
            if proxy_id is not None and retry.is_proxy_transport_error(exc, via_proxy=True):
                # v40.1: the attempt died at its proxy and never reached YouTube -- the
                # proxy's own cooldown handles it; the track keeps its rung and the
                # breaker hears nothing (see retry.ProxyTransportError).
                error_type = TrackErrorType.OTHER
                error_message = attempts.TRANSPORT_FAILURE_PREFIX + error_message
                if attempts.previous_was_transport_failure(db, track.id, entry_attempt):
                    # One rung-free retry only (see record_transport_failure's docstring):
                    # the second in a row climbs the ladder. Still OTHER, so still no
                    # breaker.
                    retry.record_failure(db, track, error_type, error_message)
                else:
                    retry.record_transport_failure(db, track, error_message)
                proxies.record_proxy_result(db, proxy_id, success=False)
            else:
                error_type = retry.classify_error(exc)
                retry.record_failure(db, track, error_type, error_message)
                if proxy_id is not None:
                    # A terminal verdict (no match, age gate, unavailable video) means
                    # this proxy carried the request to YouTube and back: it worked, so
                    # it's not the proxy's failure to be cooled down for.
                    proxies.record_proxy_result(
                        db, proxy_id, success=error_type == TrackErrorType.LOOKUP
                    )
            attempts.record_attempt(
                db,
                track.id,
                attempt_started_at,
                datetime.now(timezone.utc),
                TrackAttemptOutcome.FAILED,
                error_type=error_type,
                error_message=error_message,
                warning_message=rung_note,
                proxy_id=proxy_id,
                network_path=chosen_path,
                supersede_reclaim_after=entry_attempt,
            )
            db.commit()
            events.publish_track_event(
                owner_id,
                track.id,
                track.job_id,
                track.state.value,
                scheduled_at=track.scheduled_at,
                error=track.last_error,
                attempt_count=track.attempt_count,
                attempts_made=track.attempts_made,
                failure_count=track.failure_count,
                **track_meta,
            )
    finally:
        db.close()
