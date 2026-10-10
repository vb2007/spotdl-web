import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import type { Job, JobTracksPage, TrackAttempt } from '../src/lib/api';
import {
	ADMIN_STATE,
	cancelUnlessSettled,
	expectedAttemptVia,
	isSettled,
	serverTrackFile,
	stackPython,
	waitForJob
} from './support/stack';
import { requireEnv } from './support/env';
import { jobToggle, openDashboard, submitUrl, trackToggle } from './support/ui';

test.use({ storageState: ADMIN_STATE, acceptDownloads: true });

// Opt-in only (`npm run test:e2e:network`): one real YouTube download, end to end. Its track
// must not be in the dev ledger yet, and is in it after one pass, so there's no default:
// each pass names a fresh one in E2E_NETWORK_TRACK_URL.
test('a real download completes, records its network path, and serves its file @network', async ({
	page,
	baseURL
}) => {
	test.setTimeout(30 * 60_000);
	const TRACK_URL = requireEnv('E2E_NETWORK_TRACK_URL');
	const spotifyId = new URL(TRACK_URL).pathname.split('/').pop() ?? '';
	const inLedger = stackPython(
		'import sys\nfrom app.db import SessionLocal\nfrom app.models.downloaded_track import DownloadedTrack\n' +
			'print(SessionLocal().get(DownloadedTrack, sys.argv[1]) is not None)',
		[spotifyId]
	);
	expect(inLedger, `${TRACK_URL} is already in the dev ledger; set E2E_NETWORK_TRACK_URL`).toBe(
		'False'
	);

	// v35's trap: a file already in ./downloads makes spotdl skip and the app still record a
	// `completed` attempt with a network path. Only a file written during this test proves a
	// real download, so note the stack's clock first.
	const startedAt = Number(stackPython('import time; print(time.time())'));

	await openDashboard(page);
	const created = await submitUrl(page, TRACK_URL);
	try {
		// The retry ladder may legitimately hold it for a while; dev's LADDER_SECONDS keeps it short.
		const job: Job = await waitForJob(page.request, created.id, isSettled, 25 * 60_000);
		expect(job.status).toEqual({ lifecycle: 'settled', outcome: 'complete' });
		expect(job.track_counts.completed).toBe(1);

		const tracks = (await (
			await page.request.get(`/api/jobs/${job.id}/tracks`)
		).json()) as JobTracksPage;
		const [track] = tracks.items;
		const attempts = (await (
			await page.request.get(`/api/tracks/${track.id}/attempts`)
		).json()) as TrackAttempt[];
		const completed = attempts.find((a) => a.outcome === 'completed');
		expect(completed?.network_path, 'a real download records the path it took').toBeTruthy();

		await openDashboard(page);
		await jobToggle(page, job.title).click();
		await trackToggle(page, job.title, track.title ?? '').click();
		// Attempts render oldest first, so a retried download's completed row is its own index.
		const completedRow = page
			.getByRole('list', { name: 'attempt history' })
			.getByRole('listitem')
			.nth(attempts.indexOf(completed!));
		await expect(completedRow).toContainText('completed');
		await expect(completedRow).toContainText(expectedAttemptVia(completed!));

		const downloadEvent = page.waitForEvent('download');
		await page.getByRole('button', { name: 'download' }).click();
		const download = await downloadEvent;
		const sha256 = createHash('sha256')
			.update(await readFile(await download.path()))
			.digest('hex');
		const server = serverTrackFile(track.id);
		expect(server.mtime, 'the served file was written by this download').toBeGreaterThan(startedAt);
		expect(sha256).toBe(server.sha256);
	} finally {
		// A timed-out or failed pass must not leave a real download retrying on the ladder (or
		// finishing during the next default run, whose teardown would then fail).
		await cancelUnlessSettled(baseURL!, created.id);
	}
});
