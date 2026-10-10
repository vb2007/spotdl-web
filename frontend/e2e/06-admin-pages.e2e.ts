import { expect, test } from '@playwright/test';
import type { OutputSettings } from '../src/lib/api';
import { ADMIN_STATE, USER_STATE } from './support/stack';

/** The read-only admin endpoints behind `/settings` and `/library`. */
const ADMIN_GETS = [
	'/api/settings/output',
	'/api/settings/output/options',
	'/api/settings/library',
	'/api/settings/alerts',
	'/api/proxies',
	'/api/library/sort/status'
];

test.describe('admin', () => {
	test.use({ storageState: ADMIN_STATE });

	// Spec 6, admin half. The bitrate is changed, saved, re-read from a fresh page load and
	// from the API, then put back.
	test('/settings loads and a save round-trips; /library loads', async ({ page }) => {
		const original = (await (
			await page.request.get('/api/settings/output')
		).json()) as OutputSettings;

		try {
			await page.goto('/settings');
			const output = page.getByRole('region', { name: 'Output defaults' });
			const bitrate = output.getByLabel('Bitrate');
			await expect(bitrate).toHaveValue(original.default_bitrate);

			const options = await bitrate.locator('option').allTextContents();
			const next = options.find((o) => o !== original.default_bitrate);
			expect(next, 'needs a second bitrate option to switch to').toBeDefined();
			await bitrate.selectOption(next!);
			await output.getByRole('button', { name: 'SAVE' }).click();
			await expect(output.getByRole('status')).toHaveText('Saved.');

			await page.reload();
			await expect(
				page.getByRole('region', { name: 'Output defaults' }).getByLabel('Bitrate')
			).toHaveValue(next!);
			const saved = (await (
				await page.request.get('/api/settings/output')
			).json()) as OutputSettings;
			expect(saved.default_bitrate).toBe(next);
		} finally {
			await page.request.patch('/api/settings/output', {
				data: { default_bitrate: original.default_bitrate }
			});
		}

		await page.goto('/');
		await page.getByRole('link', { name: 'library' }).click();
		await expect(page).toHaveTitle('spotdl-web — library');
		await expect(page.getByRole('button', { name: /SWEEP/ })).toBeVisible();
		await expect(page.getByRole('alert')).toHaveText('');

		for (const path of ADMIN_GETS) {
			expect((await page.request.get(path)).status(), path).toBe(200);
		}
	});
});

test.describe('non-admin', () => {
	test.use({ storageState: USER_STATE });

	// Spec 6, non-admin half. No links to either page; a direct visit renders the page shell
	// with the backend's refusal in place of its data; every admin call is refused.
	test('/settings and /library refuse a non-admin', async ({ page }) => {
		await page.goto('/');
		await expect(page.getByLabel('Spotify URL to submit')).toBeVisible();
		await expect(page.getByRole('link', { name: 'settings' })).toHaveCount(0);
		await expect(page.getByRole('link', { name: 'library' })).toHaveCount(0);

		await page.goto('/settings');
		const output = page.getByRole('region', { name: 'Output defaults' });
		await expect(output.getByRole('alert')).toHaveText('Admin access required');
		await expect(output.getByLabel('Bitrate')).toHaveCount(0);

		await page.goto('/library');
		await expect(page.getByRole('alert')).toHaveText('Admin access required');

		// 403, not 404: admin gating is v22's pinned contract (404-not-403 is the rule for a
		// non-owner's direct-id access, not for admin endpoints). See the v37 Amendment.
		for (const path of ADMIN_GETS) {
			expect((await page.request.get(path)).status(), path).toBe(403);
		}
	});
});
