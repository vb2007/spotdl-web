import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { expect, test } from '@playwright/test';
import type { JobTracksPage, TrackAttempt } from '../src/lib/api';
import {
	USER_STATE,
	cancelUnlessSettled,
	isSettled,
	ledgerDownloads,
	ledgerFilePath,
	movedLedgerTracks,
	spotifyTrackUrl,
	waitForJob
} from './support/stack';
import { jobToggle, openDashboard, submitUrl, trackToggle } from './support/ui';

test.use({ storageState: USER_STATE, acceptDownloads: true });

// Spec 9 (v38). A track whose file the library sort moved, submitted by the non-admin identity
// (it was first downloaded by someone else): a duplicate of the library copy, never a download,
// and still downloadable to disk. Before v38, worker-dl couldn't see the library, so this
// downloaded the track again; teardown's zero-download check fails the run if it ever does.
test('a moved track resolves as a duplicate of its library file and downloads from it', async ({
	page,
	baseURL
}, testInfo) => {
	// A beat cycle for dispatch on top of expansion, plus the cleanup's margin (as spec 2).
	test.setTimeout(300_000);
	const moved = movedLedgerTracks();
	expect(
		moved.length,
		'needs two in-library ledger rows the admin never submitted: run the library sort on dev'
	).toBe(2);
	// One per project, so each run's row is unambiguous.
	const track = moved[testInfo.project.name === 'mobile' ? 1 : 0];
	// The pick was checked in worker-meta; worker-dl decides. If its library view differs (a
	// stale bind, a missing file), submitting would be a real download: refuse instead. A
	// library it can't see at all is held, not downloaded, so that case still runs (and fails).
	expect(ledgerDownloads([track.spotifyId]), 'worker-dl would download this track').toEqual([]);

	await openDashboard(page);
	const job = await submitUrl(page, spotifyTrackUrl(track.spotifyId));
	try {
		// A held track (worker-dl can't see the library) stays `waiting` and times out here.
		const settled = await waitForJob(page.request, job.id, isSettled, 150_000);
		expect(settled.status).toEqual({ lifecycle: 'settled', outcome: 'complete' });
		expect(settled.track_counts).toEqual({ skipped_duplicate: 1 });

		const tracks = (await (
			await page.request.get(`/api/jobs/${job.id}/tracks`)
		).json()) as JobTracksPage;
		const [apiTrack] = tracks.items;
		const attempts = (await (
			await page.request.get(`/api/tracks/${apiTrack.id}/attempts`)
		).json()) as TrackAttempt[];
		expect(attempts.map((a) => [a.outcome, a.network_path])).toEqual([['skipped_duplicate', null]]);
		// The ledger still points at the library copy: a re-download would have repointed it.
		expect(ledgerFilePath(track.spotifyId)).toBe(track.filePath);

		await jobToggle(page, settled.title).click();
		await trackToggle(page, settled.title, apiTrack.title ?? '').click();
		const downloadEvent = page.waitForEvent('download');
		await page.getByRole('button', { name: 'download', exact: true }).click();
		const download = await downloadEvent;
		expect(await download.failure()).toBeNull();

		const sha256 = createHash('sha256')
			.update(await readFile(await download.path()))
			.digest('hex');
		expect(download.suggestedFilename()).toBe(path.basename(track.filePath));
		expect(sha256).toBe(track.sha256);
	} finally {
		await cancelUnlessSettled(baseURL!, job.id, USER_STATE);
	}
});
