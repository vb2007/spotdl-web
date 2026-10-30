import { expect, test, type Page } from '@playwright/test';
import { ADMIN_STATE, USER_STATE } from './support/stack';

/** v44: every GET of the stats endpoint the page makes, by its query. */
function recordStatsCalls(page: Page, path = '/api/admin/stats'): URLSearchParams[] {
	const calls: URLSearchParams[] = [];
	page.on('request', (r) => {
		const url = new URL(r.url());
		if (url.pathname === path) calls.push(url.searchParams);
	});
	return calls;
}

test.describe('admin', () => {
	test.use({ storageState: ADMIN_STATE });

	// Spec 13, admin half: reached from the masthead, one request per load and per window
	// change, and every chart readable without the drawing.
	test('/stats loads with one request and switches window with one more', async ({ page }) => {
		const calls = recordStatsCalls(page);
		const alertCalls = recordStatsCalls(page, '/api/admin/alerts');
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

		// v59: the alert history is its own plate, read once on load and not again on a
		// window switch (it isn't scoped by the window).
		const alerts = page.getByRole('region', { name: 'Alerts sent to Matrix' });
		await expect(alerts).toBeVisible();
		await expect(
			alerts.getByText(/^(Every alert raised|Matrix alerts are off|No alerts were raised)/).first()
		).toBeVisible();
		expect(alertCalls).toHaveLength(1);

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

test.describe('admin, own downloads', () => {
	test.use({ storageState: ADMIN_STATE });

	// v66: the admin lands on everyone's (owner's choice) and switches to their own in the title
	// row; the address keeps the choice across a reload. One request per switch.
	test('the scope switch reads the admin’s own with one request and survives a reload', async ({
		page
	}) => {
		const mine = recordStatsCalls(page, '/api/stats/me');
		const global = recordStatsCalls(page);
		await page.goto('/stats');
		await expect(page.getByRole('heading', { name: 'Download stats', level: 1 })).toBeVisible();
		const scope = page.getByRole('group', { name: 'Whose downloads' });
		await expect(scope.getByRole('button', { name: "everyone's" })).toHaveAttribute(
			'aria-pressed',
			'true'
		);
		await expect.poll(() => global.length).toBe(1);

		const read = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/stats/me');
		await scope.getByRole('button', { name: 'mine', exact: true }).click();
		expect((await read).status()).toBe(200);
		await expect(page).toHaveURL('/stats?scope=mine');
		await expect(page.getByRole('heading', { name: 'Your downloads', level: 1 })).toBeVisible();
		await expect(page.getByRole('region', { name: 'Your library' })).toBeVisible();
		await expect(page.getByRole('region', { name: 'Right now' })).toHaveCount(0);
		await expect(page.getByRole('region', { name: 'Alerts sent to Matrix' })).toHaveCount(0);
		expect(mine).toHaveLength(1);
		expect(global).toHaveLength(1);

		await page.reload();
		await expect(page.getByRole('heading', { name: 'Your downloads', level: 1 })).toBeVisible();
		await expect(
			page.getByRole('group', { name: 'Whose downloads' }).getByRole('button', { name: 'mine' })
		).toHaveAttribute('aria-pressed', 'true');

		await page.getByRole('button', { name: "everyone's" }).click();
		await expect(page).toHaveURL('/stats');
		await expect(page.getByRole('region', { name: 'Right now' })).toBeVisible();
	});
});

test.describe('non-admin', () => {
	test.use({ storageState: USER_STATE });

	// Spec 13, non-admin half (v66): /stats is the user's own. Linked like any page, one request
	// per load and per window change, never an admin request, and the admin endpoints still
	// answer exactly like a route that doesn't exist.
	test('/stats shows a non-admin their own downloads, and nothing of the admin’s', async ({
		page
	}) => {
		const calls = recordStatsCalls(page);
		const alertCalls = recordStatsCalls(page, '/api/admin/alerts');
		const mine = recordStatsCalls(page, '/api/stats/me');

		await page.goto('/account');
		await expect(page.getByRole('heading', { name: 'Account', level: 1 })).toBeVisible();
		await page.goto('/');
		await expect(page.getByLabel('Spotify URL to submit')).toBeVisible();
		const loaded = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/stats/me');
		await page.getByRole('link', { name: 'stats', exact: true }).click();
		expect((await loaded).status()).toBe(200);
		await expect(page.getByRole('heading', { name: 'Your downloads', level: 1 })).toBeVisible();
		await expect(page.getByRole('region', { name: 'Your library' })).toBeVisible();
		const panel = page.getByRole('region', { name: 'Last 24 hours' });
		await expect(panel.getByRole('region', { name: 'Tracks' })).toBeVisible();
		await expect(panel.getByRole('region', { name: 'Failures by type' })).toBeVisible();
		// Nothing of everyone's: no switch, no "Right now", no alerts, no breaker.
		await expect(page.getByRole('group', { name: 'Whose downloads' })).toHaveCount(0);
		await expect(page.getByRole('region', { name: 'Right now' })).toHaveCount(0);
		await expect(page.getByRole('region', { name: 'Alerts sent to Matrix' })).toHaveCount(0);
		await expect(page.getByText('breaker', { exact: true })).toHaveCount(0);

		const switched = page.waitForResponse((r) => new URL(r.url()).pathname === '/api/stats/me');
		await page.getByRole('button', { name: '30d', exact: true }).click();
		expect((await switched).status()).toBe(200);
		await expect(page.getByRole('heading', { name: 'Last 30 days' })).toBeVisible();
		expect(mine.map((q) => q.get('window'))).toEqual(['24h', '30d']);

		// A hard navigation is served too.
		await page.reload();
		await expect(page.getByRole('heading', { name: 'Your downloads', level: 1 })).toBeVisible();
		await expect(page.getByRole('link', { name: 'stats', exact: true })).toHaveAttribute(
			'aria-current',
			'page'
		);
		expect(calls).toEqual([]);
		expect(alertCalls).toEqual([]);

		// 404, not 403 (v44's plan): the same answer as a path that doesn't exist.
		const stats = await page.request.get('/api/admin/stats');
		expect(stats.status()).toBe(404);
		const missing = await page.request.get('/api/admin/no-such-endpoint');
		expect(await stats.json()).toEqual(await missing.json());
		// v59: the alert history's endpoint answers the same.
		const alerts = await page.request.get('/api/admin/alerts');
		expect(alerts.status()).toBe(404);
		expect(await alerts.json()).toEqual(await missing.json());
	});
});
