import logging
import random
import time
import uuid
from datetime import datetime, timezone

from spotdl.types.song import Song

from app.config import get_settings
from app.db import SessionLocal
from app.models import DownloadedTrack, Track, TrackState
from app.services import app_settings, dedup, downloads, events, proxies, retry
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


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


@celery_app.task(name="app.tasks.download.download_track")
def download_track(track_id: str) -> None:
    db = SessionLocal()
    try:
        track = db.get(Track, uuid.UUID(track_id))
        if track is None:
            logger.warning("download_track: track %s not found", track_id)
            return

        # A cancel can land between beat's dispatch (or expand_job's immediate first
        # dispatch) and this task actually executing — e.g. a track sitting `queued` in
        # Celery's broker while the user cancels its job. Nothing upstream guarantees a
        # cancelled track is never enqueued, so this is the actual gate.
        if track.state == TrackState.CANCELLED:
            logger.info("download_track: track %s was cancelled before dispatch, skipping", track_id)
            return

        # Covers the race where this task was already enqueued just before the breaker
        # tripped (or the worker was paused) — dispatch_due_tracks is the primary gate and
        # normally won't enqueue in this state at all.
        now = datetime.now(timezone.utc)
        worker_state = retry.get_worker_state(db)
        if retry.breaker_active(worker_state, now):
            track.state = TrackState.WAITING
            track.scheduled_at = worker_state.breaker_tripped_until or (now + retry.next_delay(0))
            db.commit()
            events.publish_track_event(
                track.id,
                track.job_id,
                track.state.value,
                scheduled_at=track.scheduled_at,
                attempt_count=track.attempt_count,
            )
            return

        existing_path = dedup.is_already_downloaded(track.spotify_track_id)
        if existing_path is not None:
            track.state = TrackState.SKIPPED_DUPLICATE
            track.output_path = str(existing_path)
            db.commit()
            events.publish_track_event(track.id, track.job_id, track.state.value)
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
            # A cancel can land during the wait. Without this the download runs anyway
            # and only the post-download refresh further down discards the result.
            db.refresh(track)
            if track.state == TrackState.CANCELLED:
                logger.info(
                    "download_track: track %s was cancelled during the pacing wait, "
                    "skipping",
                    track_id,
                )
                return

        output_settings = app_settings.get_output_settings(db)

        # Attempt 1 is always direct (per the locked "direct first -> wait out the ladder
        # -> then proxy" strategy); only the *following* attempt, once its ladder wait has
        # already elapsed, prefers a proxy.
        proxy = proxies.pick_proxy(db) if track.attempt_count >= 1 else None
        proxy_id = proxy.id if proxy is not None else None
        proxy_url = proxy.url if proxy is not None else None

        track.state = TrackState.DOWNLOADING
        if proxy_id is not None:
            track.used_proxy_id = proxy_id
            logger.info(
                "download_track: track %s attempting via proxy %s",
                track_id,
                proxies.redact(proxy_url),
            )
        db.commit()
        events.publish_track_event(track.id, track.job_id, track.state.value, progress=0)

        try:
            song = Song.from_dict(track.song_json)
            # output_dir stays env-sourced (never DB-editable, see app_settings.py's
            # docstring) -- the directory a container can actually write to is fixed by
            # its volume mount at deploy time, not by an app-level setting.
            downloader = downloads.get_downloader(
                output_settings.default_format,
                output_settings.default_bitrate,
                get_settings().download_output_dir,
                output_settings.output_template,
                proxy=proxy_url,
            )
            # worker-dl runs a single track at a time (--concurrency=1), so it's safe to
            # rebind this per attempt rather than threading track/job ids through
            # get_downloader's cache key.
            downloader.progress_handler.update_callback = events.make_progress_callback(
                track.id, track.job_id
            )
            _, output_path = downloads.download_one(song, downloader)

            # search_and_download is synchronous and not cleanly interruptible, so a
            # cancel requested while this was running couldn't stop it — it instead set
            # this row's state directly (from a separate request/session) and left the
            # download to just finish. db.refresh picks up that committed change; a
            # cancelled track's result is discarded rather than overwritten back to a
            # non-terminal state.
            db.refresh(track)
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
                events.publish_track_event(track.id, track.job_id, track.state.value)
                return

            if output_path is None:
                raise RuntimeError("spotdl returned no output file for this track")

            track.state = TrackState.COMPLETED
            track.output_path = str(output_path)
            db.merge(
                DownloadedTrack(
                    spotify_track_id=track.spotify_track_id,
                    file_path=str(output_path),
                    format=output_settings.default_format,
                    bitrate=output_settings.default_bitrate,
                )
            )
            if proxy_id is not None:
                proxies.record_proxy_result(db, proxy_id, success=True)
            retry.record_success(db, track)
            db.commit()
            events.publish_track_event(track.id, track.job_id, track.state.value)
        except Exception as exc:
            # Some exceptions (e.g. spotdl's DownloaderError for a malformed proxy) echo
            # the proxy string verbatim — never let that reach worker logs or the
            # DB-persisted last_error a future UI (v09+) will display. exc_info substitutes
            # a sanitized exception for the final "Type: message" line while keeping the
            # real traceback object, so file/line info is untouched.
            error_message = str(exc)
            log_exc = exc
            if proxy_url is not None and proxy_url in error_message:
                error_message = error_message.replace(proxy_url, proxies.redact(proxy_url))
                log_exc = type(exc)(error_message)
            logger.error(
                "download_track: track %s failed",
                track_id,
                exc_info=(type(exc), log_exc, exc.__traceback__),
            )
            db.rollback()
            track = db.get(Track, uuid.UUID(track_id))
            if track.state == TrackState.CANCELLED:
                logger.info(
                    "download_track: track %s was cancelled before this failure landed, "
                    "leaving it cancelled",
                    track_id,
                )
                # Same stray-progress-event race as the success path above.
                events.publish_track_event(track.id, track.job_id, track.state.value)
                return
            error_type = retry.classify_error(exc)
            retry.record_failure(db, track, error_type, error_message)
            if proxy_id is not None:
                proxies.record_proxy_result(db, proxy_id, success=False)
            db.commit()
            events.publish_track_event(
                track.id,
                track.job_id,
                track.state.value,
                scheduled_at=track.scheduled_at,
                error=track.last_error,
                attempt_count=track.attempt_count,
            )
    finally:
        db.close()
