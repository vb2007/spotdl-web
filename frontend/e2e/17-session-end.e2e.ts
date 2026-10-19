import { expect, test } from '@playwright/test';
import { USER_STATE } from './support/stack';
import { m, t } from './support/i18n';
import { openDashboard } from './support/ui';

// Spec 17 (v47). A session that ends under an open page, and an api that can't be reached,
// end in a page that says so, never "Not authenticated" with a retry that can only fail.
// Only this browser context's cookie is dropped: the identity's server session (the saved
// state the other specs use) stays valid.
test.use({ storageState: USER_STATE });

test('a session that ends mid-page lands on /login saying why', async ({ page, context }) => {
	await openDashboard(page);
	await context.clearCookies();
	// The 5s worker poll is the latest a request notices: one 401 is enough.
	await page.waitForURL('**/login', { timeout: 20_000 });
	const ended = page.getByRole('status').filter({ hasText: t(m.login_session_ended) });
	await expect(ended).toBeVisible();
	await expect(page.getByText(t(m.error_not_authenticated), { exact: true })).toHaveCount(0);
});

test('an unreachable api shows a retrying screen, not /login, and recovers', async ({ page }) => {
	await page.route('**/api/auth/me', (route) =>
		route.fulfill({ status: 502, contentType: 'text/html', body: '<h1>502 Bad Gateway</h1>' })
	);
	await page.goto('/');
	const heading = page.getByRole('heading', { name: t(m.layout_unreachable_title), level: 1 });
	await expect(heading).toBeVisible();
	expect(new URL(page.url()).pathname).toBe('/');
	await page.unroute('**/api/auth/me');
	// It asks again by itself (2s, then backing off); the dashboard comes back where it was.
	await expect(page.locator('#queue-heading')).toBeVisible({ timeout: 15_000 });
	expect(new URL(page.url()).pathname).toBe('/');
});
