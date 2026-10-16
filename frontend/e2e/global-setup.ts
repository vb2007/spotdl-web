import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { request, type APIRequestContext, type FullConfig } from '@playwright/test';
import type { Job, JobTracksPage } from '../src/lib/api';
import { REPO_ROOT, loadE2eEnv } from './support/env';
import {
	ADMIN_STATE,
	AUTH_DIR,
	LEDGER_TRACKS,
	RUN_FILE,
	SEED_FILE,
	USER_STATE,
	adminIdentity,
	e2eDownloadsInFlight,
	isSettled,
	ledgerMisses,
	restoreWorker,
	spotifyTrackUrl,
	stackPython,
	tracksWithNetworkPath,
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
	await context.storageState({ path: statePath });
	return context;
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

/** An admin-owned track with a real network path whose job title is unique among the admin's
 * jobs (archived included), so spec 3 can find its row by title. */
async function findRealPathTrack(context: APIRequestContext): Promise<SeedJob | null> {
	for (const { trackId, jobId } of tracksWithNetworkPath(adminIdentity().email)) {
		const job = (await (await context.get(`/api/jobs/${jobId}`)).json()) as Job;
		const q = new URLSearchParams({ q: job.title, include_archived: 'true', limit: '100' });
		const sameTitle = (
			(await (await context.get(`/api/jobs?${q}`)).json()) as { items: Job[] }
		).items.filter((j) => j.title === job.title);
		if (sameTitle.length !== 1) continue;
		const tracks = (await (await context.get(`/api/jobs/${jobId}/tracks`)).json()) as JobTracksPage;
		if (tracks.items.length !== 1 || tracks.items[0].id !== trackId) continue;
		return { jobId, title: job.title, trackId, trackTitle: tracks.items[0].title ?? '' };
	}
	return null;
}

export default async function globalSetup(config: FullConfig): Promise<void> {
	loadE2eEnv();
	const baseURL = config.projects[0].use.baseURL;
	if (!baseURL) throw new Error('no baseURL configured');
	mkdirSync(AUTH_DIR, { recursive: true });
	// Teardown runs even when setup throws: neither file may still describe an earlier run.
	rmSync(RUN_FILE, { force: true });
	rmSync(SEED_FILE, { force: true });

	// Spec 12 stops worker-expand for one test; a run killed inside it would leave it stopped,
	// and every submission after that would sit at "tuning in". Starting a running service is a
	// no-op.
	execFileSync('docker', ['compose', 'start', 'worker-expand'], {
		cwd: REPO_ROOT,
		stdio: ['ignore', 'pipe', 'pipe']
	});

	// Likewise a run killed inside spec 12's worker tests: put back what it recorded.
	restoreWorker();

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
		const seed: Seed = {
			admin: adminSeed,
			user: userSeed,
			realPath: await findRealPathTrack(admin)
		};
		writeFileSync(SEED_FILE, JSON.stringify(seed, null, '\t'));
	} finally {
		await admin.dispose();
		await user.dispose();
	}
}
