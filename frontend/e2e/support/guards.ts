import { test, type APIRequestContext } from '@playwright/test';
import type { WorkerStatus } from '../../src/lib/api';
import { expandWorkerRunning, stackPython } from './stack';

// Guards shared by the specs that pause the worker or run a sweep (12, and v45's 14).

/** These tests step aside (skip) rather than disturb a busy dev stack. With E2E_STRICT=1 they
 * fail instead, so a recorded run proves every guarded action really ran. */
export function skipUnlessStrict(condition: boolean, reason: string): void {
	if (condition && process.env.E2E_STRICT === '1') {
		throw new Error(`E2E_STRICT: would skip (${reason})`);
	}
	test.skip(condition, reason);
}

/** The suite shares the developer's stack: a worker they paused, or a real hold, is theirs.
 * A test that has to pause or hold the worker skips rather than override or release it. */
export async function requireQuietWorker(admin: APIRequestContext): Promise<void> {
	const status = (await (await admin.get('/api/worker/status')).json()) as WorkerStatus;
	const holding =
		status.breaker_tripped_until !== null &&
		new Date(status.breaker_tripped_until).getTime() > Date.now();
	skipUnlessStrict(
		status.paused || holding,
		'the dev worker is paused or holding; not overriding it'
	);
	// A pause or a staged hold reschedules any track that comes up meanwhile (held to +15m or
	// +1h): never with someone's real work about to run.
	const due = Number(
		stackPython(`
from sqlalchemy import text
from app.db import SessionLocal
print(SessionLocal().execute(text(
    "select count(*) from tracks where state in ('pending', 'queued', 'downloading') "
    "or (state = 'waiting' and scheduled_at < now() + interval '2 hours')"
)).scalar())
`)
	);
	skipUnlessStrict(due > 0, `${due} track(s) would run during this test; not holding them back`);
}

/** v43's conditions for a real library sweep on the shared dev stack: it must move no file and
 * archive no one's jobs, and never post to a configured Matrix room. */
export async function requireSafeSweep(admin: APIRequestContext): Promise<void> {
	const alerts = (await (await admin.get('/api/settings/alerts')).json()) as {
		configured: boolean;
	};
	skipUnlessStrict(
		alerts.configured,
		'Matrix alerts are configured; a sweep would post to the room'
	);
	// The sweep runs on worker-expand: stopped, it would sit queued and run later, unasked.
	skipUnlessStrict(!expandWorkerRunning(), 'worker-expand is stopped; a sweep would sit queued');
	// A track that finishes downloading between the check below and the sweep would be moved.
	await requireQuietWorker(admin);
	const unfiled = Number(
		stackPython(`
from sqlalchemy import text
from app.db import SessionLocal
db = SessionLocal()
print(
    db.execute(text("select count(*) from downloaded_tracks where not in_library")).scalar()
    + db.execute(text("select count(*) from tracks where state = 'downloading'")).scalar()
)
`)
	);
	skipUnlessStrict(
		unfiled > 0,
		`${unfiled} download(s) wait to be filed or are finishing; a sweep would move them`
	);
}
