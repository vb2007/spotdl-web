import { expect, request, test } from '@playwright/test';
import {
	ADMIN_STATE,
	adminIdentity,
	missingTrackUrl,
	readSeed,
	userIdentity
} from './support/stack';
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
	} finally {
		if (failedJobId) {
			const admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
			const cancelled = await admin.delete(`/api/jobs/${failedJobId}`);
			expect.soft(cancelled.status(), 'dismissing the failed job').toBe(200);
			await admin.dispose();
		}
	}
});
