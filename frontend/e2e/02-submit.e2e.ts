import { expect, test } from '@playwright/test';
import type { Job } from '../src/lib/api';
import { ADMIN_STATE, LEDGER_TRACKS, spotifyTrackUrl } from './support/stack';
import { jobRow, jobToggle, submitUrl } from './support/ui';

test.use({ storageState: ADMIN_STATE });

// Spec 2. A ledger track, so it settles as a duplicate without a download.
test('a submitted URL appears without a refetch, settles, and its counts match the API', async ({
	page
}, testInfo) => {
	// Up to a beat cycle for dispatch on top of expansion: the inner waits name what timed out.
	test.setTimeout(240_000);
	const spotifyId =
		testInfo.project.name === 'mobile' ? LEDGER_TRACKS.submitMobile : LEDGER_TRACKS.submitDesktop;

	await page.goto('/');
	await expect(page.getByLabel('Spotify URL to submit')).toBeVisible();
	// The page's own resync (the stream's onopen) has to land before counting refetches.
	await expect(page.getByText('Loading…')).toHaveCount(0);

	// v23.1: the new job reaches the Jobs list from its own SSE events, never by re-listing.
	// Only the window before the row appears matters. Every stream (re)open legitimately
	// re-lists, so those are recorded too, to tell a reconnect from the regression.
	const listings: string[] = [];
	let streamOpens = 0;
	page.on('request', (r) => {
		if (r.method() !== 'GET') return;
		const path = new URL(r.url()).pathname;
		if (path === '/api/jobs') listings.push(r.url());
		if (path === '/api/stream') streamOpens++;
	});

	const job = await submitUrl(page, spotifyTrackUrl(spotifyId));
	const apiJob = async (): Promise<Job> =>
		(await (await page.request.get(`/api/jobs/${job.id}`)).json()) as Job;

	try {
		// The row's title is the track's, known only once expansion has read it.
		await expect.poll(async () => (await apiJob()).state, { timeout: 60_000 }).toBe('expanded');
		const { title } = await apiJob();
		await expect(jobToggle(page, title)).toBeVisible();
		expect(
			listings,
			streamOpens
				? `the Jobs list was re-fetched, after ${streamOpens} stream reconnect(s): inconclusive, rerun`
				: 'the Jobs list was re-fetched to show the new job'
		).toEqual([]);

		// Settles once beat dispatches it and worker-dl resolves it from the ledger.
		const row = jobRow(page, title);
		await expect(row.getByRole('img', { name: /^Track progress:/ })).toHaveAccessibleName(
			'Track progress: 1 done',
			{ timeout: 150_000 }
		);
		await expect(row).toContainText('done');

		const settled = await apiJob();
		expect(settled.status).toEqual({ lifecycle: 'settled', outcome: 'complete' });
		expect(settled.track_counts).toEqual({ skipped_duplicate: 1 });
		const done =
			(settled.track_counts.completed ?? 0) + (settled.track_counts.skipped_duplicate ?? 0);
		await expect(row.getByText(`${done} done`, { exact: true })).toBeVisible();
	} finally {
		// Anything but a settled duplicate could be a download in progress: stop it.
		if ((await apiJob()).status.lifecycle !== 'settled') {
			const cancelled = await page.request.delete(`/api/jobs/${job.id}`);
			expect.soft(cancelled.status(), 'cancelling the unsettled job').toBe(200);
		}
	}
});
