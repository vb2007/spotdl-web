import { expect, test } from '@playwright/test';
import { m, t } from './support/i18n';
import { readSeed, setLanguage, userIdentity } from './support/stack';
import { jobToggle, loginViaUi, trackToggle } from './support/ui';

// Spec 15 (v46): the `hu` project's smoke, in a Hungarian browser (`hu-HU`) with no saved
// language, so the page auto-detects Hungarian. Names come from the same message files the app
// renders (`t()` reads them in the project's language). Fresh context: the real login form.

test.afterEach(() => setLanguage(userIdentity().email, null));

test('Hungarian: sign in, the dashboard, a track’s detail, and the /account switch', async ({
	page
}) => {
	const seed = readSeed().user;

	await page.goto('/login');
	await expect(page.getByRole('heading', { name: t(m.login_heading) })).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.lang)).toBe('hu');
	await loginViaUi(page, userIdentity());

	// The dashboard, in Hungarian.
	await expect(page).toHaveTitle(t(m.dashboard_title));
	await expect(page.getByRole('heading', { name: t(m.queuectl_heading) })).toBeVisible();
	await expect(page.getByRole('heading', { name: t(m.waterfall_heading) })).toBeVisible();

	// A job opens to its tracks, and a track to its detail. The track's own metadata stays as
	// Spotify has it; only the interface around it is translated.
	const toggle = jobToggle(page, seed.title);
	await expect(toggle).toContainText(t(m.status_settled_complete));
	await toggle.click();
	await expect(toggle).toHaveAttribute('aria-expanded', 'true');
	const track = trackToggle(page, seed.title, seed.trackTitle);
	await expect(track).toContainText(t(m.state_skipped_duplicate));
	await expect(track).toContainText(seed.trackTitle);
	await track.click();
	await expect(track).toHaveAttribute('aria-expanded', 'true');
	await expect(page.getByText(t(m.track_status_skipped_duplicate))).toBeVisible();

	// /account: switch to English and back, in place.
	await page.goto('/account');
	await expect(page.getByRole('heading', { name: t(m.account_heading), level: 1 })).toBeVisible();
	await page.getByRole('button', { name: 'English', exact: true }).click();
	await expect(
		page.getByRole('heading', { name: t(m.account_heading, {}, 'en'), level: 1 })
	).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.lang)).toBe('en');
	await page.getByRole('button', { name: 'Magyar', exact: true }).click();
	await expect(page.getByRole('heading', { name: t(m.account_heading), level: 1 })).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.lang)).toBe('hu');
	await expect(page.getByRole('button', { name: 'Magyar', exact: true })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
});
