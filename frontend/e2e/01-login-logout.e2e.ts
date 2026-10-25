import { expect, request, test } from '@playwright/test';
import {
	ADMIN_STATE,
	adminIdentity,
	missingTrackUrl,
	readSeed,
	userIdentity
} from './support/stack';
import { m, t } from './support/i18n';
import { jobToggle, loginViaUi, logoutViaUi, submitUrl } from './support/ui';

declare global {
	interface Window {
		__e2eLeaks?: string[];
	}
}

// Spec 1. Fresh context: both identities go through the real login form, in the same tab.
test('login, logout, and no first-identity row flashes for the next identity', async ({
	page,
	baseURL
}) => {
	const seed = readSeed();
	const failedUrl = missingTrackUrl();
	let failedJobId: string | undefined;

	try {
		await loginViaUi(page, adminIdentity());
		await expect(jobToggle(page, seed.admin.title)).toBeVisible();

		// The incoming overlay renders without a loading gate (v22), which is exactly where a
		// store that survives logout shows the previous identity's rows. Give it one.
		failedJobId = (await submitUrl(page, failedUrl)).id;
		const incoming = page.getByRole('list', { name: 'Incoming submissions' });
		await expect(incoming.getByText(failedUrl)).toBeVisible();
		await expect(incoming.getByText(/no signal — could not read/)).toBeVisible({
			timeout: 60_000
		});

		await logoutViaUi(page);

		// Logout and the next login are client-side navigations, so this observer sees every
		// render the second identity's dashboard makes, however brief.
		await page.evaluate(
			(needles) => {
				window.__e2eLeaks = [];
				const check = () => {
					const text = document.body.textContent ?? '';
					for (const needle of needles) {
						if (text.includes(needle)) window.__e2eLeaks?.push(needle);
					}
				};
				check();
				new MutationObserver(check).observe(document.body, {
					childList: true,
					subtree: true,
					characterData: true
				});
			},
			[failedUrl, seed.admin.title]
		);

		await loginViaUi(page, userIdentity());
		await expect(jobToggle(page, seed.user.title)).toBeVisible();
		// Leave the stream's resync time to land, so a late render would be seen too.
		await page.waitForTimeout(2000);

		const leaks = await page.evaluate(() => window.__e2eLeaks);
		expect(leaks, 'the observer must survive: no hard navigation in between').toBeDefined();
		expect(leaks).toEqual([]);

		await logoutViaUi(page);
		await expect(page).toHaveURL(/\/login$/);

		// v54: the same from the admin's "other users" view. Its rows are someone else's (they
		// carry an owner tag) and its scope lives in the store and the URL; none of it may reach
		// the next identity's dashboard, however briefly.
		await loginViaUi(page, adminIdentity());
		const viewing = page.getByRole('group', { name: t(m.queuectl_viewing_label), exact: true });
		await viewing.getByRole('button', { name: t(m.queuectl_viewing_others), exact: true }).click();
		await expect(page).toHaveURL(/\?view=others$/);
		await expect(jobToggle(page, seed.user.title)).toBeVisible();
		await expect(jobToggle(page, seed.admin.title)).toHaveCount(0);
		await expect(page.locator('.owner').first()).toBeVisible();

		await logoutViaUi(page);
		await page.evaluate((othersLabel) => {
			window.__e2eLeaks = [];
			const check = () => {
				if (location.search.includes('view=')) window.__e2eLeaks?.push(`url ${location.search}`);
				if (document.querySelector('.owner')) window.__e2eLeaks?.push('an owner tag');
				const buttons = [...document.querySelectorAll('button')];
				if (buttons.some((b) => b.textContent?.trim() === othersLabel))
					window.__e2eLeaks?.push('the view control');
			};
			check();
			new MutationObserver(check).observe(document.body, {
				childList: true,
				subtree: true,
				characterData: true
			});
		}, t(m.queuectl_viewing_others));
		const scoped: string[] = [];
		const onRequest = (r: { url: () => string }) => {
			if (/[?&](view|all_users)=/.test(r.url())) scoped.push(r.url());
		};
		page.on('request', onRequest);

		await loginViaUi(page, userIdentity());
		await expect(jobToggle(page, seed.user.title)).toBeVisible();
		await page.waitForTimeout(2000);
		page.off('request', onRequest);
		const othersLeaks = await page.evaluate(() => window.__e2eLeaks);
		expect(othersLeaks, 'the observer must survive: no hard navigation in between').toBeDefined();
		expect(othersLeaks).toEqual([]);
		expect(scoped, "the next identity's page asks for no admin view").toEqual([]);

		await logoutViaUi(page);
		await expect(page).toHaveURL(/\/login$/);
	} finally {
		if (failedJobId) {
			const admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
			const cancelled = await admin.delete(`/api/jobs/${failedJobId}`);
			expect.soft(cancelled.status(), 'dismissing the failed job').toBe(200);
			await admin.dispose();
		}
	}
});
