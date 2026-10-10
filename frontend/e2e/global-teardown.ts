import { existsSync } from 'node:fs';
import {
	RUN_FILE,
	adminIdentity,
	e2eDownloadsInFlight,
	normalizeEmail,
	readRun,
	stackPython,
	userIdentity
} from './support/stack';

/** A default run must never reach YouTube: every job it creates is either a ledger duplicate
 * or a URL Spotify can't resolve. Any attempt with a recorded network path for one of the two
 * test identities since the run started means a seed or spec track wasn't in the ledger. A
 * beat reclaim records `failed` with no path and isn't counted. The `@network` spec is the one
 * deliberate exception. */
export default async function globalTeardown(): Promise<void> {
	if (process.env.E2E_NETWORK === '1' || !existsSync(RUN_FILE)) return;
	const { startedAt } = readRun();
	const count = stackPython(
		`
import sys
from sqlalchemy import text
from app.db import SessionLocal
print(SessionLocal().execute(text("""
    select count(*) from track_attempts a
    join tracks t on t.id = a.track_id
    join jobs j on j.id = t.job_id
    join users u on u.id = j.user_id
    where u.email in (:a, :b) and a.finished_at >= :since
      and a.network_path is not null
"""), {"a": sys.argv[1], "b": sys.argv[2], "since": sys.argv[3]}).scalar())
`,
		[normalizeEmail(adminIdentity().email), normalizeEmail(userIdentity().email), startedAt]
	);
	// An attempt row is written only when the attempt ends, and cancelling a job marks a track
	// `cancelled` without stopping worker-dl, so a download still in flight shows in neither the
	// count above nor any track state. Ask the worker what it is running right now instead.
	const inFlight = e2eDownloadsInFlight();
	if (inFlight !== '0') {
		throw new Error(
			`worker-dl is still downloading ${inFlight} e2e track(s); a default run must make none`
		);
	}
	if (count !== '0') {
		throw new Error(
			`the run made ${count} network download attempt(s); a default run must make none`
		);
	}
	console.log('teardown: zero network download attempts by the e2e identities during this run');
}
