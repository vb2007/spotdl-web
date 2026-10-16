import { expect, request, test } from '@playwright/test';
import type { AlertSettings, LibrarySettings, OutputSettings, Proxy } from '../src/lib/api';
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
	test('/settings loads and a save round-trips; /library loads', async ({ page, baseURL }) => {
		const original = (await (
			await page.request.get('/api/settings/output')
		).json()) as OutputSettings;

		try {
			await page.goto('/settings');
			const output = page.getByRole('region', { name: 'Output defaults' });
			const bitrate = output.getByLabel('Bitrate');
			await expect(bitrate).toHaveValue(original.default_bitrate);

			const options = await bitrate.getByRole('option').allTextContents();
			const next = options.find((o) => o !== original.default_bitrate);
			expect(next, 'needs a second bitrate option to switch to').toBeDefined();
			await bitrate.selectOption(next!);
			await expect(output.getByRole('status')).toHaveText('Unsaved changes');
			await output.getByRole('button', { name: 'save', exact: true }).click();
			// v43: the save state says when, and clears on the next edit (F31).
			await expect(output.getByRole('status')).toHaveText(/^Saved at /);

			await page.reload();
			await expect(
				page.getByRole('region', { name: 'Output defaults' }).getByLabel('Bitrate')
			).toHaveValue(next!);
			const saved = (await (
				await page.request.get('/api/settings/output')
			).json()) as OutputSettings;
			expect(saved.default_bitrate).toBe(next);
		} finally {
			// The shared dev stack keeps this value for real downloads and the next run's baseline.
			// Own context: a test-level timeout may already have closed the page's.
			const admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
			const restored = await admin.patch('/api/settings/output', {
				data: { default_bitrate: original.default_bitrate }
			});
			expect.soft(restored.status(), 'restoring the original bitrate').toBe(200);
			await admin.dispose();
		}

		await page.goto('/');
		// The page fills its error line from this fetch, so only its answer makes "no error" mean
		// anything.
		const status = page.waitForResponse(
			(r) => new URL(r.url()).pathname === '/api/library/sort/status'
		);
		await page.getByRole('link', { name: 'library' }).click();
		expect((await status).status()).toBe(200);
		await expect(page).toHaveTitle('spotdl-web — library');
		await expect(page.getByRole('button', { name: 'start sweep', exact: true })).toBeVisible();
		await expect(page.getByRole('alert')).toHaveText('');

		for (const path of ADMIN_GETS) {
			expect((await page.request.get(path)).status(), path).toBe(200);
		}
	});

	// v43: every /settings section still saves and re-reads (library, alerts, proxies), and a
	// client-side validation error stops the request.
	test('/settings library, alerts and proxies round-trip', async ({ page, baseURL }) => {
		const admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
		const library = (await (await admin.get('/api/settings/library')).json()) as LibrarySettings;
		const alerts = (await (await admin.get('/api/settings/alerts')).json()) as AlertSettings;
		let addedId: string | null = null;
		try {
			await page.goto('/settings');

			const lib = page.getByRole('region', { name: 'Library sort & move' });
			const template = `${library.library_folder_template} e2e`;
			await lib.getByLabel('Folder template').fill(template);
			await lib.getByRole('button', { name: 'save', exact: true }).click();
			await expect(lib.getByRole('status')).toHaveText(/^Saved at /);

			const al = page.getByRole('region', { name: 'Alerts' });
			const cooldown = al.getByLabel('Repeat an alert at most every');
			await cooldown.fill('0');
			const sentPatch: string[] = [];
			const onRequest = (r: import('@playwright/test').Request) => {
				if (r.method() === 'PATCH' && new URL(r.url()).pathname === '/api/settings/alerts')
					sentPatch.push(r.url());
			};
			page.on('request', onRequest);
			await al.getByRole('button', { name: 'save', exact: true }).click();
			await expect(cooldown).toHaveAttribute('aria-invalid', 'true');
			// Nothing was sent, so focus moves to the field and its error is read from there.
			await expect(cooldown).toBeFocused();
			await expect(al.getByText('Use a whole number from 1 to 10,080.')).toBeVisible();
			page.off('request', onRequest);
			expect(sentPatch, 'an invalid number never reaches the API').toEqual([]);
			const nextCooldown = alerts.alert_cooldown_minutes === 61 ? 62 : 61;
			await cooldown.fill(String(nextCooldown));
			await al.getByRole('button', { name: 'save', exact: true }).click();
			await expect(al.getByRole('status').first()).toHaveText(/^Saved at /);

			const px = page.getByRole('region', { name: 'Proxy pool' });
			const proxyField = px.getByLabel('Add a proxy');
			await proxyField.fill('http://proxy.example.com:8080');
			await px.getByRole('button', { name: 'add proxy', exact: true }).click();
			await expect(proxyField).toHaveAttribute('aria-invalid', 'true');
			await expect(px.getByText(/needs a literal IPv4 address/)).toBeVisible();
			const added = page.waitForResponse(
				(r) => r.request().method() === 'POST' && new URL(r.url()).pathname === '/api/proxies'
			);
			const url = `http://203.0.113.${test.info().project.name === 'mobile' ? 46 : 45}:8080`;
			await proxyField.fill(url);
			await px.getByRole('button', { name: 'add proxy', exact: true }).click();
			const proxy = (await (await added).json()) as Proxy;
			addedId = proxy.id;
			// Off at once: a TEST-NET address must never be offered to a download.
			await px.getByRole('button', { name: `switch off ${proxy.url}`, exact: true }).click();
			await expect(
				px.getByRole('button', { name: `switch on ${proxy.url}`, exact: true })
			).toBeVisible();

			await page.reload();
			await expect(
				page.getByRole('region', { name: 'Library sort & move' }).getByLabel('Folder template')
			).toHaveValue(template);
			await expect(
				page.getByRole('region', { name: 'Alerts' }).getByLabel('Repeat an alert at most every')
			).toHaveValue(String(nextCooldown));
			const proxies = (await (await admin.get('/api/proxies')).json()) as Proxy[];
			expect(proxies.find((p) => p.id === addedId)?.enabled).toBe(false);
		} finally {
			const restoredLibrary = await admin.patch('/api/settings/library', {
				data: { library_folder_template: library.library_folder_template }
			});
			expect.soft(restoredLibrary.status(), 'restoring the folder template').toBe(200);
			const restoredAlerts = await admin.patch('/api/settings/alerts', {
				data: { alert_cooldown_minutes: alerts.alert_cooldown_minutes }
			});
			expect.soft(restoredAlerts.status(), 'restoring the alert cooldown').toBe(200);
			if (addedId) await admin.delete(`/api/proxies/${addedId}`);
			await admin.dispose();
		}
	});
});

test.describe('non-admin', () => {
	test.use({ storageState: USER_STATE });

	// Spec 6, non-admin half. No links to either page anywhere; a direct visit renders a
	// notice (v43, F17) and makes no admin request; every admin call is refused.
	test('/settings and /library refuse a non-admin', async ({ page }) => {
		const adminCalls: string[] = [];
		page.on('request', (r) => {
			const path = new URL(r.url()).pathname;
			if (ADMIN_GETS.includes(path) || path.startsWith('/api/worker/')) adminCalls.push(path);
		});

		await page.goto('/');
		await expect(page.getByLabel('Spotify URL to submit')).toBeVisible();
		await expect(page.getByRole('link', { name: 'settings' })).toHaveCount(0);
		await expect(page.getByRole('link', { name: 'library' })).toHaveCount(0);

		await page.goto('/account');
		await expect(page.getByRole('heading', { name: 'Account', level: 1 })).toBeVisible();
		await expect(page.getByRole('link', { name: 'settings' })).toHaveCount(0);
		await expect(page.getByRole('link', { name: 'library' })).toHaveCount(0);

		const notice = { name: 'Only the admin can use this page' };
		await page.goto('/settings');
		await expect(page.getByRole('heading', notice)).toBeVisible();
		await expect(page.getByLabel('Bitrate')).toHaveCount(0);
		await expect(page.getByRole('region', { name: 'Output defaults' })).toHaveCount(0);

		await page.goto('/library');
		await expect(page.getByRole('heading', notice)).toBeVisible();
		await expect(page.getByRole('button', { name: 'start sweep' })).toHaveCount(0);
		// `/` polls the worker status for everyone (TrackRow's countdown); only the pages'
		// own admin reads count here.
		expect(adminCalls.filter((p) => p !== '/api/worker/status')).toEqual([]);

		// 403, not 404: admin gating is v22's pinned contract (404-not-403 is the rule for a
		// non-owner's direct-id access, not for admin endpoints). See the v37 Amendment.
		for (const path of ADMIN_GETS) {
			expect((await page.request.get(path)).status(), path).toBe(403);
		}
	});
});
