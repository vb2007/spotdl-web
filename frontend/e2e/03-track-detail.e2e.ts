import { expect, test } from '@playwright/test';
import type { TrackAttempt } from '../src/lib/api';
import { ADMIN_STATE, expectedAttemptVia, readSeed } from './support/stack';
import { jobToggle, trackToggle } from './support/ui';

test.use({ storageState: ADMIN_STATE });

// Spec 3. The admin's seed job: one track, resolved from the ledger.
test('expanding a job and a track loads attempt history with its network path', async ({
	page
}) => {
	const { admin } = readSeed();
	const attempts = (await (
		await page.request.get(`/api/tracks/${admin.trackId}/attempts`)
	).json()) as TrackAttempt[];
	expect(attempts.length).toBeGreaterThan(0);

	await page.goto('/');
	const toggle = jobToggle(page, admin.title);
	await toggle.click();
	await expect(toggle).toHaveAttribute('aria-expanded', 'true');

	const track = trackToggle(page, admin.title, admin.trackTitle);
	await track.click();
	await expect(track).toHaveAttribute('aria-expanded', 'true');

	const history = page.getByRole('list', { name: 'attempt history' });
	const rows = history.getByRole('listitem');
	await expect(rows).toHaveCount(attempts.length);
	// The API lists newest first, and the UI keeps that order. Each row renders the path the
	// API's `network_path` (v35 (b)) says the attempt took.
	for (const [i, attempt] of attempts.entries()) {
		await expect(rows.nth(i)).toContainText(expectedAttemptVia(attempt));
	}
	await expect(rows.first()).toContainText('already logged');
});
