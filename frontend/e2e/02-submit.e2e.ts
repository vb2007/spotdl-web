import { expect, test } from '@playwright/test';
import type { Job } from '../src/lib/api';
import { ADMIN_STATE, LEDGER_TRACKS, cancelUnlessSettled, spotifyTrackUrl } from './support/stack';
import { jobRow, jobToggle, openDashboard, submitUrl } from './support/ui';

test.use({ storageState: ADMIN_STATE });

// Spec 2. A ledger track, so it settles as a duplicate without a download.
test('a submitted URL appears without a refetch, settles, and its counts match the API', async ({
	page,
	baseURL
}, testInfo) => {
	// The inner waits add up to 240s (a beat cycle for dispatch on top of expansion) and name
	// what timed out; the margin lets the cleanup below run before the test-level timeout.
	test.setTimeout(300_000);
	const spotifyId =
		testInfo.project.name === 'mobile' ? LEDGER_TRACKS.submitMobile : LEDGER_TRACKS.submitDesktop;

	// v23.1: the new job reaches the Jobs list from its own SSE events, never by re-listing.
	// Every stream (re)open legitimately re-lists, so streams are counted from before the page
	// loads, and listings only once the first open's own resync has landed (`openDashboard`).
	let streamOpens = 0;
	let armed = false;
	const listings: string[] = [];
	page.on('request', (r) => {
		if (r.method() !== 'GET') return;
		const path = new URL(r.url()).pathname;
		if (path === '/api/stream') streamOpens++;
		if (armed && path === '/api/jobs') listings.push(r.url());
	});

	await openDashboard(page);
	const opensAtArm = streamOpens;
	armed = true;

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
			streamOpens > opensAtArm
				? `the Jobs list was re-fetched, after ${streamOpens - opensAtArm} stream reconnect(s): inconclusive, rerun`
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
		// v42 (F28): a one-track job shows no separate count line, so its count is read from
		// the bar's accessible name, against the API's own counts.
		const done =
			(settled.track_counts.completed ?? 0) + (settled.track_counts.skipped_duplicate ?? 0);
		await expect(
			row.getByRole('img', { name: `Track progress: ${done} done`, exact: true })
		).toBeVisible();
	} finally {
		await cancelUnlessSettled(baseURL!, job.id);
	}
});
