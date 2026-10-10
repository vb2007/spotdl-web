import { expect, test } from '@playwright/test';
import { ADMIN_STATE, missingTrackUrl } from './support/stack';
import { submitUrl } from './support/ui';

test.use({ storageState: ADMIN_STATE });

// Spec 5. A failed zero-track job stays in the incoming overlay until it's dismissed. Before
// v34 that overlay was fed by SSE only, so a hard reload emptied it for good.
test('a hard reload still shows an incoming item', async ({ page }) => {
	const url = missingTrackUrl();
	let jobId: string | undefined;

	try {
		await page.goto('/');
		jobId = (await submitUrl(page, url)).id;

		const incoming = page.getByRole('list', { name: 'Incoming submissions' });
		const item = incoming.getByRole('listitem').filter({ hasText: url });
		await expect(item).toContainText('no signal — could not read this track', {
			timeout: 60_000
		});

		await page.reload();
		await expect(page.getByText('Loading…')).toHaveCount(0);
		await expect(item).toContainText('no signal — could not read this track');

		await item.getByRole('button', { name: 'dismiss' }).click();
		await expect(item).toHaveCount(0);
		jobId = undefined;
	} finally {
		if (jobId) await page.request.delete(`/api/jobs/${jobId}`);
	}
});
