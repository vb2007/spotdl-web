import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { request, type APIRequestContext, type FullConfig } from '@playwright/test';
import type { Job, JobTracksPage } from '../src/lib/api';
import { loadE2eEnv } from './support/env';
import {
	ADMIN_STATE,
	AUTH_DIR,
	LEDGER_TRACKS,
	RUN_FILE,
	SEED_FILE,
	USER_STATE,
	adminIdentity,
	detachedWebVolumes,
	e2eDownloadsInFlight,
	isSettled,
	ledgerMisses,
	restartExpandWorker,
	restoreSettings,
	restoreSweepReport,
	resetPreferences,
	restoreWorker,
	spotifyTrackUrl,
	stackPython,
	userIdentity,
	waitForJob,
	type Identity,
	type Seed,
	type SeedJob
} from './support/stack';

/** Logs in through the real `/api/auth/login` (and so the real upstream), checks the identity
 * has the admin flag the suite expects of it, and saves the session for the specs to reuse. */
async function login(
	baseURL: string,
	identity: Identity,
	expectAdmin: boolean,
	statePath: string
): Promise<APIRequestContext> {
	const context = await request.newContext({ baseURL });
	const response = await context.post('/api/auth/login', {
		data: { email: identity.email, password: identity.password }
	});
	if (!response.ok()) {
		throw new Error(`login as ${identity.email} failed: ${response.status()}`);
	}
	const session = (await response.json()) as { is_admin: boolean };
	if (session.is_admin !== expectAdmin) {
		throw new Error(
			`${identity.email} has is_admin=${session.is_admin}; the suite needs it ${expectAdmin}. ` +
				"Check the dev .env's ADMIN_EMAIL."
		);
	}
	// v52 (D6): the suite runs on http://127.0.0.1, where Playwright's request contexts (unlike
	// Chromium) never send a `Secure` cookie: they count only `localhost` as a secure origin over
	// plain HTTP. The saved session drops the flag, so every context made from it (this one
	// included, from here on) sends it. The server still sets it, and a login the browser makes
	// itself (spec 1) keeps it.
	await context.storageState({ path: statePath });
	const state = JSON.parse(readFileSync(statePath, 'utf8')) as {
		cookies: { secure: boolean }[];
	};
	for (const cookie of state.cookies) cookie.secure = false;
	writeFileSync(statePath, JSON.stringify(state));
	await context.dispose();
	return request.newContext({ baseURL, storageState: statePath });
}

/** Leaves the identity with nothing in flight and nothing unarchived, so every run starts from
 * the same slate and a spec's own rows are the only ones with their titles. */
async function clearSlate(context: APIRequestContext): Promise<void> {
	const response = await context.get(
		'/api/jobs?status=expanding&status=active&status=waiting&limit=1000'
	);
	if (!response.ok()) throw new Error(`listing in-flight jobs failed: ${response.status()}`);
	const { items } = (await response.json()) as { items: Job[] };
	for (const job of items) {
		const cancelled = await context.delete(`/api/jobs/${job.id}`);
		if (!cancelled.ok()) throw new Error(`cancelling job ${job.id} failed: ${cancelled.status()}`);
	}
	const archived = await context.post('/api/jobs/archive', { data: { all_settled: true } });
	if (!archived.ok()) throw new Error(`clear log failed: ${archived.status()}`);
}

/** Submits a ledger track and waits for it to settle as a duplicate. Anything else means the
 * track wasn't a ledger hit after all; the job is cancelled so a download that did start can't
 * keep retrying on the ladder after the run. */
async function seedJob(context: APIRequestContext, spotifyId: string): Promise<SeedJob> {
	const created = await context.post('/api/jobs', { data: { url: spotifyTrackUrl(spotifyId) } });
	if (!created.ok()) throw new Error(`submitting ${spotifyId} failed: ${created.status()}`);
	const { id } = (await created.json()) as Job;
	let job: Job;
	try {
		job = await waitForJob(context, id, isSettled, 150_000);
		if (job.status.lifecycle !== 'settled' || job.track_counts.skipped_duplicate !== 1) {
			throw new Error(
				`seed ${spotifyId} settled as ${JSON.stringify(job.status)} with ` +
					`${JSON.stringify(job.track_counts)}; expected one skipped_duplicate`
			);
		}
	} catch (err) {
		await context.delete(`/api/jobs/${id}`);
		throw err;
	}
	const tracks = (await (await context.get(`/api/jobs/${id}/tracks`)).json()) as JobTracksPage;
	const [track] = tracks.items;
	return { jobId: id, title: job.title, trackId: track.id, trackTitle: track.title ?? '' };
}

export default async function globalSetup(config: FullConfig): Promise<void> {
	loadE2eEnv();
	const baseURL = config.projects[0].use.baseURL;
	if (!baseURL) throw new Error('no baseURL configured');
	mkdirSync(AUTH_DIR, { recursive: true });
	// Teardown runs even when setup throws: neither file may still describe an earlier run.
	rmSync(RUN_FILE, { force: true });
	rmSync(SEED_FILE, { force: true });

	// v52 (D7): fail now, and say why, rather than flake later on a reload.
	const detached = detachedWebVolumes();
	if (detached.length) {
		throw new Error(
			`the dev web container lost its own ${detached.join(', ')} (removing that directory on the ` +
				'host detaches the volume), so a host-side npm run check would reload the pages under ' +
				'test: docker compose restart web (in an agent slot: scripts/agent_stack.sh <slot> run ' +
				'docker compose restart web), then run again'
		);
	}

	// Spec 12 stops worker-expand for one test; a run killed inside it would leave it stopped,
	// and every submission after that would sit at "tuning in". Only a stop the suite recorded
	// is undone: one the developer made on purpose is left alone.
	await restartExpandWorker();

	// Likewise a run killed inside spec 12's worker tests: put back what it recorded.
	restoreWorker();
	restoreSweepReport();
	restoreSettings();

	// Every job a default run creates must resolve from the ledger. Refuse to start rather than
	// let one become a real download.
	const misses = ledgerMisses(Object.values(LEDGER_TRACKS));
	if (misses.length) {
		throw new Error(
			`LEDGER_TRACKS not resolvable as duplicates in worker-dl (no ledger row, its file is gone, or its root isn't mounted there): ${misses.join(', ')}`
		);
	}

	// A download still running for an e2e identity (an aborted `@network` pass, say) would finish
	// inside this run's window and be blamed on it. Refuse to start until worker-dl is done.
	const inFlight = e2eDownloadsInFlight();
	if (inFlight !== '0') {
		throw new Error(
			`worker-dl is still downloading ${inFlight} track(s) for the e2e identities; wait for it to finish`
		);
	}

	const startedAt = stackPython(
		'from sqlalchemy import text\nfrom app.db import SessionLocal\n' +
			'print(SessionLocal().execute(text("select now()")).scalar().isoformat())'
	);
	// Before the first job is submitted, so teardown checks this run's window however setup ends.
	writeFileSync(RUN_FILE, JSON.stringify({ startedAt }));

	const admin = await login(baseURL, adminIdentity(), true, ADMIN_STATE);
	const user = await login(baseURL, userIdentity(), false, USER_STATE);
	// v46: a saved language (or clock) wins over the browser's, and every project pins its
	// browser locale (en-US, or hu-HU for `hu`). Neither identity may carry one in from an
	// earlier run or from a developer's own switch on /account. After login, so both users rows
	// exist.
	resetPreferences();
	try {
		await Promise.all([clearSlate(admin), clearSlate(user)]);
		// allSettled: each seed cancels its own job on failure, which needs its context alive
		// until it's done, so the other's rejection mustn't reach `finally` first.
		const [adminResult, userResult] = await Promise.allSettled([
			seedJob(admin, LEDGER_TRACKS.adminSeed),
			seedJob(user, LEDGER_TRACKS.userSeed)
		]);
		if (adminResult.status === 'rejected') throw adminResult.reason;
		if (userResult.status === 'rejected') throw userResult.reason;
		const [adminSeed, userSeed] = [adminResult.value, userResult.value];
		const seed: Seed = { admin: adminSeed, user: userSeed };
		writeFileSync(SEED_FILE, JSON.stringify(seed, null, '\t'));
	} finally {
		await admin.dispose();
		await user.dispose();
	}
}
