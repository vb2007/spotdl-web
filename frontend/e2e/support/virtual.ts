import type { BrowserContext } from '@playwright/test';
import { LEDGER_TRACKS, normalizeEmail, stackPython } from './stack';

// v68: the virtualized lists' fixture. A separate account with a 1600-job log, so the lists
// cross their windowing threshold (`VIRTUAL_THRESHOLD`, 200 rows) once enough pages are loaded,
// while the suite's two identities keep the plain, below-threshold lists every other spec reads.
// It's never a login identity: it signs in with a session minted straight in the stack's database
// (the suite's admin and user still log in through the real upstream in global setup).

export const FIXTURE_EMAIL = 'v68fixture@example.com';
/** The log: every job a single track, except one playlist of `BIG_TRACKS`. */
export const FIXTURE_JOBS = 1600;
export const BIG_TRACKS = 400;
/** Newest first, the list's default order: the playlist sits on the first page. */
export const BIG_AT = 5;
/** The job the live spec changes from outside the page: deep in the list, far off the window
 * until it's scrolled to. Its one track waits (on a ledger id, a day away from any dispatch). */
export const LIVE_AT = 1500;

export function fixtureTitle(n: number): string {
	return n === BIG_AT
		? 'Virtual fixture playlist'
		: `Virtual fixture ${String(n).padStart(4, '0')}`;
}

export interface VirtualFixture {
	token: string;
	liveJobId: string;
	bigJobId: string;
}

/** Seeds (once) or resets the fixture account, and mints a session for it. Idempotent: the log
 * is created once, and every run puts back what a spec changed (archived rows come back, the
 * live job is waiting again). Refuses anything but a dev stack. */
export function seedVirtualFixture(): VirtualFixture {
	const out = stackPython(
		`
import json, sys
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from app.config import get_settings
from app.db import SessionLocal
from app.models.job import Job, JobSourceType, JobState
from app.models.track import Track, TrackState
from app.services.sessions import create_session
from app.services.users import get_or_create_user

if get_settings().spotdl_env != "dev":
    sys.exit("v68 fixture: refusing a stack that isn't SPOTDL_ENV=dev")
email, jobs, big_tracks, big_at, live_at, ledger_id = sys.argv[1:7]
jobs, big_tracks, big_at, live_at = int(jobs), int(big_tracks), int(big_at), int(live_at)
db = SessionLocal()
user = get_or_create_user(db, email)
url = "https://open.spotify.com/{kind}/v68fixture{n:04d}"
have = db.execute(text("select count(*) from jobs where user_id = :u"), {"u": user.id}).scalar()
if have not in (0, jobs):
    sys.exit(f"v68 fixture: {email} has {have} jobs, not {jobs}: delete them to reseed")
if have == 0:
    # Two years back: older than anything the other specs create or page through, so in the
    # admin's all-users view (archived, between runs) it sorts after all of it.
    newest = datetime.now(timezone.utc) - timedelta(days=730)
    for n in range(jobs):
        created = newest - timedelta(minutes=n)
        big = n == big_at
        job = Job(
            user_id=user.id,
            source_url=url.format(kind="playlist" if big else "track", n=n),
            source_type=JobSourceType.PLAYLIST if big else JobSourceType.TRACK,
            state=JobState.EXPANDED,
            created_at=created,
        )
        db.add(job)
        db.flush()
        for i in range(big_tracks if big else 1):
            name = f"Virtual fixture playlist track {i + 1:03d}" if big else f"Virtual fixture {n:04d}"
            song = {"name": name, "artists": ["v68 fixture"], "album_name": "v68 fixture"}
            if big:
                song["list_name"] = "Virtual fixture playlist"
            db.add(Track(
                job_id=job.id,
                # The live job's one track is a ledger hit: a dispatch would resolve it as a
                # duplicate, never a download (and it's no backlog for agent_stack's e2e).
                spotify_track_id=ledger_id if n == live_at else f"v68fixture{n:04d}t{i:03d}",
                song_json=song,
                state=TrackState.SKIPPED_DUPLICATE,
                # Within its own minute (the playlist's 400 too), so the tracks scope keeps the
                # jobs' order.
                created_at=created + timedelta(milliseconds=i),
            ))
    db.flush()
ids = {
    n: str(db.execute(text("select id from jobs where user_id = :u and source_url = :s"),
                      {"u": user.id, "s": url.format(kind=kind, n=n)}).scalar())
    for n, kind in ((live_at, "track"), (big_at, "playlist"))
}
# What a spec changed: every row back in the log, the live job waiting again.
db.execute(text("update jobs set archived_at = null, state = 'expanded' where user_id = :u"),
           {"u": user.id})
db.execute(text("""
    update tracks set state = 'waiting', scheduled_at = now() + interval '1 day',
                      last_error = null, last_error_type = null
    where job_id = :j
"""), {"j": ids[live_at]})
# v69: a session works only for an address on the allowlist (every cookie request checks it).
db.execute(text("insert into allowed_emails (email) values (:e) on conflict do nothing"), {"e": user.email})
token = create_session(db, user.id).token
db.commit()
# v70: the reset moved the live job's rollup (cancelled back to waiting), so it's announced as
# app code must (CLAUDE.md, job_status.publish_change after the commit): its Redis record then
# says "waiting", and the spec's cancel carries a real prev_status, as every job since v62 does.
# Without it a fresh stack's first run cancelled a job with no record (the store re-read its
# counts) and every later run one already recorded "cancelled" (no job.status event at all).
from app.services import job_status
job_status.publish_change(db, ids[live_at])
print(json.dumps({"token": token, "liveJobId": ids[live_at], "bigJobId": ids[big_at]}))
`,
		[
			normalizeEmail(FIXTURE_EMAIL),
			String(FIXTURE_JOBS),
			String(BIG_TRACKS),
			String(BIG_AT),
			String(LIVE_AT),
			LEDGER_TRACKS.adminSeed
		]
	);
	return JSON.parse(out.split('\n').at(-1) ?? '') as VirtualFixture;
}

/** Signs `context` in as the fixture account. */
export async function signInFixture(
	context: BrowserContext,
	baseURL: string,
	token: string
): Promise<void> {
	await context.addCookies([{ name: 'SPOTDL_SESSION', value: token, url: baseURL }]);
}

/** Puts the log away after the spec: every fixture job archived, the live one settled, its
 * minted sessions deleted, so the
 * admin's all-users view of the specs that run after it (the next project's) doesn't page
 * through 1600 rows. */
export function parkVirtualFixture(): void {
	stackPython(
		`
import sys
from sqlalchemy import text
from app.config import get_settings
from app.db import SessionLocal
if get_settings().spotdl_env != "dev":
    sys.exit("v68 fixture: refusing a stack that isn't SPOTDL_ENV=dev")
db = SessionLocal()
user = "(select id from users where email = :e)"
db.execute(text(f"""
    update tracks set state = 'skipped_duplicate', scheduled_at = null
    where state = 'waiting' and job_id in (select id from jobs where user_id = {user})
"""), {"e": sys.argv[1]})
db.execute(text(f"update jobs set archived_at = now() where user_id = {user} and archived_at is null"),
           {"e": sys.argv[1]})
# The sessions the spec minted, one per test.
db.execute(text(f"delete from sessions where user_id = {user}"), {"e": sys.argv[1]})
db.commit()
`,
		[normalizeEmail(FIXTURE_EMAIL)]
	);
}
