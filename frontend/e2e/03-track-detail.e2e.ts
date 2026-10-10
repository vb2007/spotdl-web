import { expect, test, type Page } from '@playwright/test';
import type { TrackAttempt } from '../src/lib/api';
import { ADMIN_STATE, expectedAttemptVia, readSeed, type SeedJob } from './support/stack';
import { jobToggle, trackToggle } from './support/ui';

test.use({ storageState: ADMIN_STATE });

/** Expands `seed`'s job and track, then checks every attempt row against the API's own
 * attempts: count, order (newest first) and the path label its `network_path` (v35 (b)) maps
 * to. Returns the API's attempts. */
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

	const rows = page.getByRole('list', { name: 'attempt history' }).getByRole('listitem');
	await expect(rows).toHaveCount(attempts.length);
	for (const [i, attempt] of attempts.entries()) {
		await expect(rows.nth(i)).toContainText(expectedAttemptVia(attempt));
	}
	return attempts;
}

// Spec 3.
test('expanding a job and a track loads attempt history with its network path', async ({
	page
}) => {
	const { admin, realPath } = readSeed();

	// The admin's seed job: one track, resolved from the ledger, so no network path.
	await page.goto('/');
	await checkAttemptHistory(page, admin);
	await expect(
		page.getByRole('list', { name: 'attempt history' }).getByRole('listitem').first()
	).toContainText('already logged');

	// A track whose attempts did reach the network (left by an earlier `@network` pass, its job
	// archived by setup), so a real path label renders.
	if (realPath === null) {
		test.info().annotations.push({
			type: 'warning',
			description:
				'no admin-owned track with a recorded network path yet, so real path labels went ' +
				'unchecked: run `npm run test:e2e:network` once'
		});
		return;
	}
	await page.goto('/');
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
