import { expect, test, type Page } from '@playwright/test';
import { ADMIN_STATE, USER_STATE } from './support/stack';

/** v44: every GET of the stats endpoint the page makes, by its query. */
function recordStatsCalls(page: Page): URLSearchParams[] {
	const calls: URLSearchParams[] = [];
	page.on('request', (r) => {
		const url = new URL(r.url());
		if (url.pathname === '/api/admin/stats') calls.push(url.searchParams);
	});
	return calls;
}

test.describe('admin', () => {
	test.use({ storageState: ADMIN_STATE });

	// Spec 13, admin half: reached from the masthead, one request per load and per window
	// change, and every chart readable without the drawing.
	test('/stats loads with one request and switches window with one more', async ({ page }) => {
		const calls = recordStatsCalls(page);
		await page.goto('/');
		const loaded = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/admin/stats');
		await page.getByRole('link', { name: 'stats', exact: true }).click();
		expect((await loaded).status()).toBe(200);
		await expect(page).toHaveTitle('spotdl-web — stats');
		await expect(page.getByRole('heading', { name: 'Download stats', level: 1 })).toBeVisible();

		const now = page.getByRole('region', { name: 'Right now' });
		await expect(now.getByText('waiting', { exact: true })).toBeVisible();
		const panel = page.getByRole('region', { name: 'Last 24 hours' });
		const routes = panel.getByRole('region', { name: 'Routes' });
		for (const route of ['direct · IPv4', 'direct · IPv6', 'proxy']) {
			await expect(routes.getByRole('rowheader', { name: route, exact: true })).toBeVisible();
		}
		// The recorder is an image whose alternative is its label and its table.
		const recorder = panel.getByRole('img', { name: /^(Failures by type|No failures)/ });
		await expect(recorder).toHaveAttribute('aria-label', /breaker/i);
		await panel.getByText('show as a table').click();
		await expect(panel.getByRole('columnheader', { name: 'Hour' })).toBeVisible();
		await expect(panel.getByRole('columnheader', { name: 'Breaker' })).toBeVisible();

		expect(calls.map((q) => q.get('window'))).toEqual(['24h']);
		// The viewer's own clock rides along (owner's choice: a day bucket is their day).
		expect(calls[0].get('utc_offset_minutes')).toBe(
			String(await page.evaluate(() => -new Date().getTimezoneOffset()))
		);

		const switched = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/admin/stats');
		await page.getByRole('button', { name: '7d', exact: true }).click();
		expect((await switched).status()).toBe(200);
		await expect(page.getByRole('heading', { name: 'Last 7 days' })).toBeVisible();
		await expect(page.getByRole('button', { name: '7d', exact: true })).toHaveAttribute(
			'aria-pressed',
			'true'
		);
		// The table view stays open across the switch and re-reads per day.
		await expect(page.getByRole('columnheader', { name: 'Day' })).toBeVisible();
		await expect(page.getByRole('columnheader', { name: 'Hour' })).toHaveCount(0);
		expect(calls.map((q) => q.get('window'))).toEqual(['24h', '7d']);

		// A hard navigation is served too (dev here; the nginx image's own block is checked
		// against the built image in the PR).
		await page.reload();
		await expect(page.getByRole('heading', { name: 'Download stats', level: 1 })).toBeVisible();
		await expect(page.getByRole('link', { name: 'stats', exact: true })).toHaveAttribute(
			'aria-current',
			'page'
		);
	});
});

test.describe('non-admin', () => {
	test.use({ storageState: USER_STATE });

	// Spec 13, non-admin half: no link anywhere, the notice on a typed path with no stats
	// request, and the endpoint answers exactly like a route that doesn't exist.
	test('/stats is hidden from a non-admin', async ({ page }) => {
		const calls = recordStatsCalls(page);

		await page.goto('/');
		await expect(page.getByLabel('Spotify URL to submit')).toBeVisible();
		await expect(page.getByRole('link', { name: 'stats' })).toHaveCount(0);

		await page.goto('/account');
		await expect(page.getByRole('heading', { name: 'Account', level: 1 })).toBeVisible();
		await expect(page.getByRole('link', { name: 'stats' })).toHaveCount(0);

		await page.goto('/stats');
		await expect(
			page.getByRole('heading', { name: 'Only the admin can use this page' })
		).toBeVisible();
		await expect(page.getByRole('region', { name: 'Right now' })).toHaveCount(0);
		await expect(page.getByRole('button', { name: 'refresh' })).toHaveCount(0);
		expect(calls).toEqual([]);

		// 404, not 403 (v44's plan): the same answer as a path that doesn't exist.
		const stats = await page.request.get('/api/admin/stats');
		expect(stats.status()).toBe(404);
		const missing = await page.request.get('/api/admin/no-such-endpoint');
		expect(await stats.json()).toEqual(await missing.json());
	});
});
