import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import { ADMIN_STATE, readSeed, serverTrackFile } from './support/stack';
import { jobToggle, openDashboard, trackToggle } from './support/ui';

test.use({ storageState: ADMIN_STATE, acceptDownloads: true });

// Spec 4. The bytes the browser saves are the file the API resolves for the track.
test('a downloaded file matches the API-side file byte for byte', async ({ page }) => {
	const { admin } = readSeed();
	const server = serverTrackFile(admin.trackId);

	await openDashboard(page);
	await jobToggle(page, admin.title).click();
	await trackToggle(page, admin.title, admin.trackTitle).click();

	const downloadEvent = page.waitForEvent('download');
	await page.getByRole('button', { name: 'download' }).click();
	const download = await downloadEvent;
	expect(await download.failure()).toBeNull();

	const saved = await download.path();
	const sha256 = createHash('sha256')
		.update(await readFile(saved))
		.digest('hex');
	expect(download.suggestedFilename()).toBe(server.name);
	expect(sha256).toBe(server.sha256);
});
