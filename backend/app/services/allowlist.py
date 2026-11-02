"""Who may sign in (v69): the `allowed_emails` table, managed by the admin in `/users`.

Before v69 this was the `ALLOWED_EMAILS` env list. The migration that created the table
imported it (plus `ADMIN_EMAIL`) once; since then the env list is ignored (`warn_if_env_ignored`
says so at api startup when it holds an address the table doesn't). `ADMIN_EMAIL` stays in env,
is always allowed whether or not it has a row, and can't be removed.

**Read on every check, never cached:** an address added in `/users` signs in on its very next
attempt, with no restart.

**Removing an address cuts the person off at once** (`remove`, one transaction): their sessions
are deleted, their API keys revoked, and their jobs that haven't started yet are held
(`jobs.held_at`). After the commit their open live streams are told on their own control
channel (`events.publish_control`), and the stream's heartbeat re-check (routers/stream.py) is
the safety net when that publish is lost. Their jobs and files stay, and so does their `users`
row: adding the address again (`add`) restores the same account and resumes the held jobs.

**Started vs held.** A job has started when one of its tracks is `downloading`, `completed`,
`skipped_duplicate` or `lookup_failed`, or has `attempt_count > 0` or `attempts_made > 0`: it has
had an attempt (a reclaimed or cancelled run included) or a dedup result. Only a job with
something to run is held (expanding, or a track still to download), and its lifecycle reads `held`
only while that's still so (services/rollup.py). A started job runs to the end, retry ladder and all, so no album or artist is left
half-archived. One that hasn't is held, and `download_track` attempts none of its tracks. The
removal locks the user's job rows (`FOR UPDATE`) before deciding, and `download_track` reads
`held_at` under `FOR SHARE` in the transaction that moves a track to `downloading`, so the two
serialize: whichever commits first wins, and nothing starts after a hold.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, delete, exists, func, literal, null, or_, select, union_all, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings
from app.errors import ApiError
from app.models import AllowedEmail, ApiKey, Job, JobState, Track, TrackState, User, UserSession
from app.services import events, job_status
from app.services.spotify_urls import storable
from app.services.sessions import SESSION_IDLE_TIMEOUT
from app.services.users import normalize_email

logger = logging.getLogger(__name__)

# The longest address SMTP carries (RFC 5321's path limit, less the brackets).
MAX_EMAIL_LENGTH = 254

# Track states that mean a job has started: an attempt ran (or is running), or dedup resolved a
# track. `waiting` alone doesn't: beat's stale sweep moves a reclaimed `queued` track there
# without any attempt (`_reclaim_stale_tracks`). Beside the states, a track that tried the
# network counts: `attempt_count > 0` (the plan's ladder counter) or `attempts_made > 0` (a
# reclaimed or cancelled `downloading` run, which the ladder counter doesn't see; review round 2).
STARTED_TRACK_STATES = (
    TrackState.DOWNLOADING,
    TrackState.COMPLETED,
    TrackState.SKIPPED_DUPLICATE,
    TrackState.LOOKUP_FAILED,
)
# Jobs a removal never holds: nothing of theirs can run anyway.
_UNHOLDABLE_JOB_STATES = (JobState.CANCELLED, JobState.FAILED)

# How long a resume's claim on the held jobs' tracks keeps beat from sending them a second time
# (the same lease, and the same reason, as expand_job's first dispatch: tasks/expand.py).
DISPATCH_LEASE = timedelta(minutes=10)

# A removed user's ended sessions, by token hash, for as long as one could have lived: a request
# still carrying one answers 401 `access_removed` (not `not_authenticated`), so every tab of theirs
# says why, not only the one whose stream got `revoked` (review: live round 1).
REVOKED_SESSION_PREFIX = "spotdl:revoked-session:"


_revoked_client = None


def _redis():
    """Its own client with short timeouts (job_status' pattern): this runs on a 401, and a stalled
    Redis must cost a request half a second, never a socket's whole wait."""
    global _revoked_client
    if _revoked_client is None:
        import redis
        from redis.backoff import NoBackoff
        from redis.retry import Retry

        _revoked_client = redis.Redis.from_url(
            get_settings().redis_url,
            socket_timeout=0.5,
            socket_connect_timeout=0.5,
            retry=Retry(NoBackoff(), 0),
        )
    return _revoked_client


def _token_key(token: str) -> str:
    return REVOKED_SESSION_PREFIX + hashlib.sha256(token.encode()).hexdigest()


def _remember_revoked(user_id: uuid.UUID, tokens: list[str]) -> None:
    """Best effort: with Redis down, a removed user's tab says "session ended" instead. The
    value is the owner, so the record stops counting once the address is added back."""
    if not tokens:
        return
    try:
        pipe = _redis().pipeline(transaction=False)
        for token in tokens:
            pipe.set(_token_key(token), str(user_id), ex=int(SESSION_IDLE_TIMEOUT.total_seconds()))
        pipe.execute()
    except Exception:
        logger.warning("allowlist: couldn't record the removed user's ended sessions", exc_info=True)


def session_was_revoked(db: Session, token: str | None) -> bool:
    """Whether `token` belonged to a session a removal ended, and its owner's address is still
    off the allowlist (added back, it's an ordinary ended session). False when Redis can't say."""
    if not token or not storable(token):
        return False
    try:
        owner = _redis().get(_token_key(token))
    except Exception:
        return False
    if owner is None:
        return False
    try:
        email = db.execute(
            select(User.email).where(User.id == uuid.UUID(owner.decode() if isinstance(owner, bytes) else owner))
        ).scalar_one_or_none()
    except ValueError:
        return False
    return email is not None and not is_allowed(db, email)


IGNORED_ENV_WARNING = (
    "ALLOWED_EMAILS is ignored since v69, manage users in /users "
    "(%d address(es) in it aren't in the allowlist table)"
)


def admin_address() -> str:
    return normalize_email(get_settings().admin_email)


def is_allowed(db: Session, email: str, *, lock: bool = False) -> bool:
    """Whether `email` may sign in: it's `ADMIN_EMAIL`, or it has a row. Read from the database
    every time. `lock` (the login) takes `FOR SHARE` on the row until the caller's transaction
    ends, so a removal committing meanwhile waits for that login's session to exist, and then
    deletes it with the others (`remove`)."""
    normalized = normalize_email(email)
    if normalized == admin_address():
        return True
    stmt = select(AllowedEmail.email).where(AllowedEmail.email == normalized)
    if lock:
        stmt = stmt.with_for_update(read=True)
    return db.execute(stmt).first() is not None


def owner_allowed(user_email: ColumnElement, allowed_email: ColumnElement) -> ColumnElement:
    """The condition for a query that joins `users` and outer-joins `allowed_emails` on the
    user's address: the owner may sign in (beat's watched-job selection, `tasks/beat.py`)."""
    return or_(allowed_email.is_not(None), user_email == admin_address())


def validate_email(email: str) -> str:
    """The address normalized, or 422 `invalid_email`: minimal syntax only (one `@`, a dot in the
    domain, no whitespace), since the upstream account system decides what's real."""
    normalized = normalize_email(email) if isinstance(email, str) else ""
    local, at, domain = normalized.partition("@")
    if (
        not normalized
        or len(normalized) > MAX_EMAIL_LENGTH
        or not storable(normalized)
        or any(char.isspace() for char in normalized)
        # Not in a path segment: `DELETE /api/admin/allowlist/{email}` could never match it.
        or "/" in normalized
        or normalized.count("@") != 1
        or not local
        or "." not in domain
        or domain.startswith(".")
        or domain.endswith(".")
    ):
        raise ApiError(422, "invalid_email", "Not a valid e-mail address")
    return normalized


def _job_started() -> ColumnElement:
    """Correlated on `Job`: one of its tracks has had an attempt or a dedup result."""
    return exists().where(
        Track.job_id == Job.id,
        or_(Track.state.in_(STARTED_TRACK_STATES), Track.attempt_count > 0, Track.attempts_made > 0),
    )


def _job_has_work() -> ColumnElement:
    """Correlated on `Job`: a track still to download (what a hold would stop)."""
    return exists().where(
        Track.job_id == Job.id,
        Track.state.in_((TrackState.PENDING, TrackState.QUEUED, TrackState.WAITING)),
    )


def _lock_user_jobs(db: Session, user_id: uuid.UUID) -> None:
    """The user's job rows, locked in id order (as job_status locks them), before deciding
    anything about them: `download_track`'s `FOR SHARE` on a job waits for this transaction."""
    db.execute(select(Job.id).where(Job.user_id == user_id).order_by(Job.id).with_for_update())


@dataclass
class Removal:
    user_id: uuid.UUID | None
    held_job_ids: list[uuid.UUID] = field(default_factory=list)
    sessions_ended: int = 0
    keys_revoked: int = 0


def remove(db: Session, email: str) -> Removal:
    """Takes `email` off the allowlist and cuts its user off, in one transaction (committed
    here), then tells their open streams. `ADMIN_EMAIL` is 409 `cannot_remove_admin`; an
    address with no row is 404 `allowed_email_not_found`."""
    normalized = normalize_email(email) if isinstance(email, str) else ""
    if normalized == admin_address():
        raise ApiError(409, "cannot_remove_admin", "The admin's address can't be removed")
    # An address Postgres can't even compare (a NUL) is on no list.
    if not storable(normalized):
        raise ApiError(404, "allowed_email_not_found", "That address isn't on the allowlist")
    # The row first: a login holding it `FOR SHARE` (is_allowed's lock) commits its session
    # before this goes on, so the session delete below sees it.
    deleted = db.execute(
        delete(AllowedEmail).where(AllowedEmail.email == normalized).returning(AllowedEmail.email)
    ).scalar_one_or_none()
    if deleted is None:
        db.rollback()
        raise ApiError(404, "allowed_email_not_found", "That address isn't on the allowlist")

    user_id = db.execute(select(User.id).where(User.email == normalized)).scalar_one_or_none()
    removal = Removal(user_id=user_id)
    if user_id is not None:
        _lock_user_jobs(db, user_id)
        ended_tokens = list(
            db.execute(
                delete(UserSession).where(UserSession.user_id == user_id).returning(UserSession.token)
            ).scalars()
        )
        removal.sessions_ended = len(ended_tokens)
        removal.keys_revoked = db.execute(
            update(ApiKey)
            .where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
            .values(revoked_at=func.now())
        ).rowcount
        # One UPDATE for every job, never a per-job loop. A new statement, so it sees every
        # commit that the lock above waited for (a track that moved to `downloading` first).
        removal.held_job_ids = list(
            db.execute(
                update(Job)
                .where(
                    Job.user_id == user_id,
                    Job.held_at.is_(None),
                    Job.state.not_in(_UNHOLDABLE_JOB_STATES),
                    Job.archived_at.is_(None),
                    ~_job_started(),
                    # Only a job with something left to run: one still expanding, or with a
                    # track to download. An empty or fully cancelled one has nothing to hold.
                    or_(Job.state == JobState.EXPANDING, _job_has_work()),
                )
                .values(held_at=func.now())
                .returning(Job.id)
                .execution_options(synchronize_session=False)
            ).scalars()
        )
    db.commit()
    logger.info(
        "allowlist: an address was removed (user %s: %d session(s) ended, %d key(s) revoked, "
        "%d job(s) held)",
        user_id,
        removal.sessions_ended,
        removal.keys_revoked,
        len(removal.held_job_ids),
    )
    if user_id is not None:
        _remember_revoked(user_id, ended_tokens)
        events.publish_control(user_id, events.CONTROL_REVOKED)
        # Their rollup moved to `held` (the admin's "others" view shows it): the chips move on
        # `job.status`, and an open row re-reads itself on `job.state` (review round 4).
        _announce_jobs(db, user_id, removal.held_job_ids)
    return removal


@dataclass
class Addition:
    row: AllowedEmail
    user_id: uuid.UUID | None
    resumed_job_ids: list[uuid.UUID] = field(default_factory=list)
    enqueued: int = 0


def add(db: Session, email: str, by: User) -> Addition:
    """Puts `email` on the allowlist (committed here): it signs in on its next attempt. An
    address that already has a user row gets that same account back, and its held jobs resume
    in the same transaction: `held_at` is cleared and their `pending` tracks are claimed, then
    enqueued after the commit (`_send_resumed`). 422 `invalid_email`, 409
    `email_already_allowed` (`ADMIN_EMAIL` included: it's always allowed)."""
    normalized = validate_email(email)
    if normalized == admin_address():
        raise ApiError(409, "email_already_allowed", "That address is already on the allowlist")
    inserted = db.execute(
        insert(AllowedEmail)
        .values(email=normalized, added_by=by.id)
        .on_conflict_do_nothing(index_elements=[AllowedEmail.email])
        .returning(AllowedEmail.email)
    ).scalar_one_or_none()
    if inserted is None:
        db.rollback()
        raise ApiError(409, "email_already_allowed", "That address is already on the allowlist")

    user_id = db.execute(select(User.id).where(User.email == normalized)).scalar_one_or_none()
    addition = Addition(row=db.get(AllowedEmail, normalized), user_id=user_id)
    claimed: list[uuid.UUID] = []
    lease = datetime.now(timezone.utc) + DISPATCH_LEASE
    if user_id is not None:
        _lock_user_jobs(db, user_id)
        # Resumed: the jobs whose hold was still stopping something (not one cancelled or failed
        # since, or emptied by per-track cancels); every hold is cleared all the same.
        addition.resumed_job_ids = list(
            db.execute(
                select(Job.id).where(
                    Job.user_id == user_id,
                    Job.held_at.is_not(None),
                    Job.state.not_in(_UNHOLDABLE_JOB_STATES),
                    or_(Job.state == JobState.EXPANDING, _job_has_work()),
                )
            ).scalars()
        )
        db.execute(
            update(Job)
            .where(Job.user_id == user_id, Job.held_at.is_not(None))
            .values(held_at=None)
            .execution_options(synchronize_session=False)
        )
        if addition.resumed_job_ids:
            # One bulk query for every resumed job's pending tracks, in queue order.
            ordered = list(
                db.execute(
                    select(Track.id)
                    .join(Job, Job.id == Track.job_id)
                    .where(Track.job_id.in_(addition.resumed_job_ids), Track.state == TrackState.PENDING)
                    .order_by(Job.priority.desc(), Job.created_at.asc(), Track.created_at.asc(), Track.id)
                ).scalars()
            )
            if ordered:
                # The claim (expand_job's outbox lease, v56 E1): beat leaves them alone until
                # the lease runs out, so each is sent once, here. Only what the claim matched
                # is sent: a track beat dispatched since the read above has its own message.
                won = set(
                    db.execute(
                        update(Track)
                        .where(Track.id.in_(ordered), Track.state == TrackState.PENDING)
                        .values(scheduled_at=lease)
                        .returning(Track.id)
                        .execution_options(synchronize_session=False)
                    ).scalars()
                )
                claimed = [track_id for track_id in ordered if track_id in won]
    db.commit()
    db.refresh(addition.row)
    logger.info(
        "allowlist: an address was added (user %s: %d held job(s) resumed, %d track(s) to enqueue)",
        user_id,
        len(addition.resumed_job_ids),
        len(claimed),
    )
    if claimed:
        addition.enqueued = _send_resumed(db, claimed, lease)
    if user_id is not None:
        _announce_jobs(db, user_id, addition.resumed_job_ids)
    return addition


def _announce_jobs(db: Session, user_id: uuid.UUID, job_ids: list[uuid.UUID]) -> None:
    """After a hold or a resume: each job's `job.state` (one publish per job, no query), so a
    row an admin has open re-reads its status, then the status moves for the chips."""
    if not job_ids:
        return
    states = dict(db.execute(select(Job.id, Job.state).where(Job.id.in_(job_ids))).all())
    db.commit()
    for job_id in job_ids:
        if job_id in states:
            events.publish_job_event(user_id, job_id, states[job_id].value)
    job_status.publish_changes(db, job_ids)


def _due_case(track_ids: list[uuid.UUID], at: datetime):
    """A marker per track, a microsecond apart in `track_ids`' order (tasks/expand.py's)."""
    return case(
        {track_id: at + timedelta(microseconds=index) for index, track_id in enumerate(track_ids)},
        value=Track.id,
    )


def _send_resumed(db: Session, track_ids: list[uuid.UUID], lease: datetime) -> int:
    """One `.delay` per claimed track, in order. A broker error part-way puts the unsent ones'
    marker back to now, so beat's next tick sends them; the sent ones lose their marker. Only
    rows still carrying this claim's lease are touched (a sent track may have moved on)."""
    # Imported here: tasks.download imports the services this module's callers use.
    from app.tasks.download import download_track

    sent = 0
    try:
        for track_id in track_ids:
            download_track.delay(str(track_id))
            sent += 1
    except Exception as exc:
        logger.warning(
            "allowlist: the broker refused a resumed track (%s); %d of %d sent, the rest go on "
            "beat's next dispatch",
            exc,
            sent,
            len(track_ids),
        )
        unsent = track_ids[sent:]
        db.execute(
            update(Track)
            .where(Track.id.in_(unsent), Track.scheduled_at == lease, Track.state == TrackState.PENDING)
            .values(scheduled_at=_due_case(unsent, datetime.now(timezone.utc)))
            .execution_options(synchronize_session=False)
        )
    if sent:
        db.execute(
            update(Track)
            .where(Track.id.in_(track_ids[:sent]), Track.scheduled_at == lease)
            .values(scheduled_at=None)
            .execution_options(synchronize_session=False)
        )
    db.commit()
    return sent


def list_rows(db: Session) -> list[dict]:
    """Every allowlist row for `/users`, in one query: the address, when and by whom it was
    added, and the account behind it (none yet: never signed in). `ADMIN_EMAIL` is always
    listed, with or without a row. No held-jobs count (owner's decision, 2026-11-02): a listed
    address never has a held job, since a hold exists only while its address is off the list."""
    admin = admin_address()
    rows = union_all(
        select(AllowedEmail.email, AllowedEmail.added_at, AllowedEmail.added_by),
        select(
            literal(admin).label("email"),
            null().label("added_at"),
            null().label("added_by"),
        ).where(~exists().where(AllowedEmail.email == admin)),
    ).subquery("rows")
    adder = aliased(User)
    is_admin_email = rows.c.email == admin
    result = db.execute(
        select(
            rows.c.email,
            rows.c.added_at,
            adder.email.label("added_by_email"),
            User.username,
            User.last_login_at,
            is_admin_email.label("is_admin_email"),
        )
        .select_from(rows)
        .outerjoin(User, User.email == rows.c.email)
        .outerjoin(adder, adder.id == rows.c.added_by)
        .order_by(is_admin_email.desc(), rows.c.added_at.desc().nulls_last(), rows.c.email)
    ).all()
    return [row_to_dict(row) for row in result]


def row_to_dict(row) -> dict:
    return {
        "email": row.email,
        "added_at": row.added_at.isoformat() if row.added_at is not None else None,
        "added_by": row.added_by_email,
        "username": row.username,
        "last_login_at": row.last_login_at.isoformat() if row.last_login_at is not None else None,
        "is_admin_email": bool(row.is_admin_email),
    }


def get_row(db: Session, email: str) -> dict:
    """One address's row, in `list_rows`' shape (the add's answer)."""
    normalized = normalize_email(email)
    for row in list_rows(db):
        if row["email"] == normalized:
            return row
    raise ApiError(404, "allowed_email_not_found", "That address isn't on the allowlist")


def warn_if_env_ignored(db: Session) -> int:
    """At api startup: one warning when `ALLOWED_EMAILS` holds an address the table doesn't,
    since a later `.env` edit would otherwise silently do nothing. Prints the count only, never
    an address (they're personal data). Returns the count."""
    addresses = {normalize_email(email) for email in get_settings().allowed_emails} - {"", admin_address()}
    if not addresses:
        return 0
    present = set(
        db.execute(select(AllowedEmail.email).where(AllowedEmail.email.in_(addresses))).scalars()
    )
    missing = len(addresses - present)
    if missing:
        logger.warning(IGNORED_ENV_WARNING, missing)
    return missing
