import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import type { Job, JobTracksPage, TrackAttempt } from '../src/lib/api';
import {
	ADMIN_STATE,
	adminIdentity,
	expectedAttemptVia,
	expectedTimeline,
	networkPathFixture,
	readSeed,
	tracksWithNetworkPath,
	type SeedJob
} from './support/stack';
import { jobToggle, openDashboard, trackToggle } from './support/ui';

test.use({ storageState: ADMIN_STATE });

/** Of `candidates`, the first admin-owned track with a real network path whose job title is
 * unique among the admin's jobs (archived included) and whose job has only that track, so the
 * dashboard search finds its row by title. */
async function findRealPathTrack(
	context: APIRequestContext,
	candidates: { trackId: string; jobId: string }[]
): Promise<SeedJob | null> {
	for (const { trackId, jobId } of candidates) {
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

/** Expands `seed`'s job and track, then checks the timeline against the API's own attempts:
 * one entry per run of identical readings, newest first (v41), each single attempt carrying the
 * path label its `network_path` (v35 (b)) maps to and each run its `×n`. Returns the API's
 * attempts. */
async function checkAttemptHistory(page: Page, seed: SeedJob): Promise<TrackAttempt[]> {
	const attempts = (await (
		await page.request.get(`/api/tracks/${seed.trackId}/attempts`)
	).json()) as TrackAttempt[];
	expect(attempts.length).toBeGreaterThan(0);
	// The field itself must be there: with it missing, the UI and the expected label below
	// would both fall back to the same path-less branch and agree.
	for (const attempt of attempts) expect(attempt).toHaveProperty('network_path');

	const toggle = jobToggle(page, seed.title);
	await toggle.click();
	await expect(toggle).toHaveAttribute('aria-expanded', 'true');
	const track = trackToggle(page, seed.title, seed.trackTitle);
	await track.click();
	await expect(track).toHaveAttribute('aria-expanded', 'true');

	const entries = expectedTimeline(attempts);
	const rows = page.getByRole('list', { name: 'attempt history' }).getByRole('listitem');
	await expect(rows).toHaveCount(entries.length);
	for (const [i, entry] of entries.entries()) {
		if (entry.length === 1) await expect(rows.nth(i)).toContainText(expectedAttemptVia(entry[0]));
		else await expect(rows.nth(i)).toContainText(`×${entry.length}`);
	}
	return attempts;
}

// Spec 3.
test('expanding a job and a track loads attempt history with its network path', async ({
	page
}) => {
	const { admin } = readSeed();

	// The admin's seed job: one track, resolved from the ledger, so no network path.
	await openDashboard(page);
	await checkAttemptHistory(page, admin);
	await expect(
		page.getByRole('list', { name: 'attempt history' }).getByRole('listitem').first()
	).toContainText('duplicate');

	// A track whose attempts did reach the network (an earlier `@network` pass's, archived by
	// setup), so a real path label renders. Without one, only the path-less branch would ever
	// render and a broken real-path label would pass. v52 (D7): a database that has none (a fresh
	// one) gets this spec's own fixture, so it runs standalone, with no network pass first.
	const email = adminIdentity().email;
	const realPath =
		(await findRealPathTrack(page.request, tracksWithNetworkPath(email))) ??
		(await findRealPathTrack(page.request, [networkPathFixture(email)]));
	expect(realPath, 'an admin-owned track with a recorded network path').not.toBeNull();
	if (realPath === null) return;
	await openDashboard(page);
	await page.getByRole('button', { name: 'show archived' }).click();
	// The search re-lists after a debounce and re-renders the rows, so expanding before its
	// answer lands would be undone.
	const searched = page.waitForResponse(
		(r) => new URL(r.url()).pathname === '/api/jobs' && new URL(r.url()).searchParams.has('q')
	);
	await page.getByLabel('Search jobs').fill(realPath.title);
	await searched;
	await expect(page.getByText('Loading…')).toHaveCount(0);
	const attempts = await checkAttemptHistory(page, realPath);
	expect(attempts.some((a) => a.network_path !== null)).toBe(true);
});
