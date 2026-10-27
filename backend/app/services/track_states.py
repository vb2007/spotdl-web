"""Which track states a cancel or a retry may act on (v56, A2): one definition for both
routers, matching what the UI offers (`TrackRow.svelte`'s `CANCELLABLE_STATES`).

`lookup_failed` is terminal: the track was not found, so there is nothing in flight to stop,
and the UI never offers cancel on it. A job cancel leaves such tracks as they are, and
`DELETE /api/tracks/{id}` refuses one. It stays retryable, though: "retry" is how a user asks
for another search after a not-found."""

from datetime import timedelta

from sqlalchemy import case, func, or_

from app.config import get_settings
from app.models import Track, TrackState
from app.services.attempts import reclaim_unreported

# Every state with nothing left to happen to it unless someone retries it.
TERMINAL_TRACK_STATES = frozenset(
    {
        TrackState.COMPLETED,
        TrackState.SKIPPED_DUPLICATE,
        TrackState.CANCELLED,
        TrackState.LOOKUP_FAILED,
    }
)

# Everything else: still to be dispatched, dispatched, running, or waiting out the ladder.
# Exactly the states that make a job's rollup `active` or `waiting` (services/rollup.py), so a
# job is cancellable exactly when it has a cancellable track (or is still expanding).
CANCELLABLE_TRACK_STATES = frozenset(state for state in TrackState if state not in TERMINAL_TRACK_STATES)

RETRYABLE_TRACK_STATES = frozenset({TrackState.WAITING, TrackState.LOOKUP_FAILED})


def cancelled_used_proxy_id():
    """v56 (A4): what a cancel UPDATE writes to `used_proxy_id`. A track whose download may
    still be running keeps it (the download runs on to the end, and `proxies.proxy_in_use`
    must see that): one `downloading`, or one beat reclaimed mid-download within the
    stale-track window whose download hasn't reported back (v55: it's `waiting` meanwhile).
    Any other cancelled track drops it, or an ended attempt's proxy would hold up its delete."""
    still_running = func.now() - timedelta(seconds=get_settings().stale_track_after_seconds)
    return case(
        (or_(Track.state == TrackState.DOWNLOADING, reclaim_unreported(still_running)), Track.used_proxy_id),
        else_=None,
    )
