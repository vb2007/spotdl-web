import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import type { Job, JobTracksPage, TrackAttempt } from '../src/lib/api';
import {
	ADMIN_STATE,
	expectedAttemptVia,
	isSettled,
	serverTrackFile,
	stackPython,
	waitForJob
} from './support/stack';
import { jobToggle, submitUrl, trackToggle } from './support/ui';

test.use({ storageState: ADMIN_STATE, acceptDownloads: true });

// Opt-in only (`npm run test:e2e:network`): one real YouTube download, end to end. Its track
// must not be in the dev ledger yet, so each pass needs a fresh one (E2E_NETWORK_TRACK_URL).
const TRACK_URL =
	process.env.E2E_NETWORK_TRACK_URL || 'https://open.spotify.com/track/0DiWol3AO6WpXZgp0goxAV';

test('a real download completes, records its network path, and serves its file @network', async ({
	page
}) => {
	test.setTimeout(30 * 60_000);
	const spotifyId = new URL(TRACK_URL).pathname.split('/').pop() ?? '';
	const inLedger = stackPython(
		'import sys\nfrom app.db import SessionLocal\nfrom app.models.downloaded_track import DownloadedTrack\n' +
			'print(SessionLocal().get(DownloadedTrack, sys.argv[1]) is not None)',
		[spotifyId]
	);
	expect(inLedger, `${TRACK_URL} is already in the dev ledger; set E2E_NETWORK_TRACK_URL`).toBe(
		'False'
	);

	await page.goto('/');
	const created = await submitUrl(page, TRACK_URL);
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

	await page.reload();
	await jobToggle(page, job.title).click();
	await trackToggle(page, job.title, track.title ?? '').click();
	const history = page.getByRole('list', { name: 'attempt history' });
	await expect(history.getByRole('listitem').first()).toContainText(expectedAttemptVia(completed!));
	await expect(history.getByRole('listitem').first()).toContainText('completed');

	const downloadEvent = page.waitForEvent('download');
	await page.getByRole('button', { name: 'download' }).click();
	const download = await downloadEvent;
	const sha256 = createHash('sha256')
		.update(await readFile(await download.path()))
		.digest('hex');
	expect(sha256).toBe(serverTrackFile(track.id).sha256);
});
