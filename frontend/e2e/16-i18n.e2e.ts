import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';
import { m, t, type Lang } from './support/i18n';
import {
	adminIdentity,
	languageOf,
	setLanguage,
	userIdentity,
	type Identity
} from './support/stack';

// Spec 16 (v46). Each test opens its own browser contexts, one per browser language, and runs
// once (desktop project). Both identities start with no saved language (global setup), and every
// test puts back what it saved.

async function freshContext(browser: Browser, locale: string): Promise<BrowserContext> {
	return browser.newContext({ locale, viewport: { width: 1280, height: 800 } });
}

async function htmlLang(page: Page): Promise<string> {
	return page.evaluate(() => document.documentElement.lang);
}

/** Signs in through the real form (real upstream), reading the form in `lang` and then the
 * dashboard in `landsIn` (a saved preference can make it another language than the form's). */
async function signIn(
	page: Page,
	identity: Identity,
	lang: Lang,
	landsIn: Lang = lang
): Promise<void> {
	if (new URL(page.url()).pathname !== '/login') await page.goto('/login');
	await page.getByLabel(t(m.login_email, {}, lang), { exact: true }).fill(identity.email);
	await page.getByLabel(t(m.login_password, {}, lang), { exact: true }).fill(identity.password);
	await page.getByRole('button', { name: t(m.login_connect, {}, lang), exact: true }).click();
	await expect(
		page.getByLabel(t(m.dashboard_submit_input_label, {}, landsIn), { exact: true })
	).toBeVisible();
}

/** Signs out from a dashboard in `lang`; /login then speaks `landsIn` (signed out, the
 * browser or a /login choice decides, never the profile). */
async function signOut(page: Page, lang: Lang, landsIn: Lang): Promise<void> {
	await page
		.getByRole('button', { name: t(m.dashboard_disconnect, {}, lang), exact: true })
		.click();
	await expect(
		page.getByRole('heading', { name: t(m.login_heading, {}, landsIn), exact: true })
	).toBeVisible();
}

/** The dashboard reads in `lang`: the document says so and its queue heading is in it. */
async function expectDashboardIn(page: Page, lang: Lang): Promise<void> {
	await expect(
		page.getByRole('heading', { name: t(m.queuectl_heading, {}, lang), exact: true })
	).toBeVisible();
	expect(await htmlLang(page)).toBe(lang);
}

test.afterEach(() => {
	setLanguage(userIdentity().email, null);
	setLanguage(adminIdentity().email, null);
});

test('auto-detect: hu-HU gets Hungarian, en-US English, de-DE falls back to English', async ({
	browser
}) => {
	for (const [locale, lang] of [
		['hu-HU', 'hu'],
		['en-US', 'en'],
		['de-DE', 'en']
	] as const) {
		const context = await freshContext(browser, locale);
		const page = await context.newPage();
		await page.goto('/login');
		await expect(
			page.getByRole('heading', { name: t(m.login_heading, {}, lang), exact: true })
		).toBeVisible();
		expect(await htmlLang(page), `/login in a ${locale} browser`).toBe(lang);
		await expect(page).toHaveTitle(t(m.login_title, {}, lang));

		// A profile with no saved language keeps following the browser once signed in.
		await signIn(page, userIdentity(), lang);
		await expectDashboardIn(page, lang);
		expect(languageOf(userIdentity().email), 'nothing saved by signing in').toBeNull();
		await context.close();
	}
});

test('preference wins: Hungarian chosen on /account follows the user, and only that user', async ({
	browser
}) => {
	const context = await freshContext(browser, 'en-US');
	const page = await context.newPage();
	await signIn(page, userIdentity(), 'en');
	await expectDashboardIn(page, 'en');

	await page.goto('/account');
	// A switch is not a reload: this marker survives only if the document does.
	await page.evaluate(
		() => ((window as Window & { __sameDocument?: boolean }).__sameDocument = true)
	);
	await page.getByRole('button', { name: 'Magyar', exact: true }).click();
	await expect(
		page.getByRole('heading', { name: t(m.account_heading, {}, 'hu'), exact: true })
	).toBeVisible();
	expect(await htmlLang(page), '<html lang> follows the switch').toBe('hu');
	await expect(page.getByRole('button', { name: 'Magyar', exact: true })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	await expect(page.getByRole('status').filter({ hasText: /Mentve/ })).toBeVisible();
	expect(
		await page.evaluate(() => (window as Window & { __sameDocument?: boolean }).__sameDocument),
		'no reload on switch'
	).toBe(true);
	await expect(page).toHaveTitle(t(m.account_title, {}, 'hu'));
	expect(languageOf(userIdentity().email), 'saved server-side').toBe('hu');

	// Reload.
	await page.reload();
	await expect(
		page.getByRole('heading', { name: t(m.account_heading, {}, 'hu'), exact: true })
	).toBeVisible();
	expect(await htmlLang(page)).toBe('hu');

	// Logout: signed out, the page follows this (English) browser again; signing back in
	// brings the profile's Hungarian back.
	await page.goto('/');
	await signOut(page, 'hu', 'en');
	expect(await htmlLang(page), 'signed out: the browser decides').toBe('en');
	await signIn(page, userIdentity(), 'en', 'hu');
	await expectDashboardIn(page, 'hu');

	// A second browser (no shared storage) for the same user.
	const second = await freshContext(browser, 'en-US');
	const secondPage = await second.newPage();
	await signIn(secondPage, userIdentity(), 'en', 'hu');
	await expectDashboardIn(secondPage, 'hu');
	await second.close();

	// Another user, same English browser: unaffected.
	const other = await freshContext(browser, 'en-US');
	const otherPage = await other.newPage();
	await signIn(otherPage, adminIdentity(), 'en');
	await expectDashboardIn(otherPage, 'en');
	expect(languageOf(adminIdentity().email)).toBeNull();
	await other.close();

	// And back: English chosen in Hungarian.
	await page.goto('/account');
	await page.getByRole('button', { name: 'English', exact: true }).click();
	await expect(
		page.getByRole('heading', { name: t(m.account_heading, {}, 'en'), exact: true })
	).toBeVisible();
	expect(await htmlLang(page)).toBe('en');
	expect(languageOf(userIdentity().email)).toBe('en');
	await context.close();
});

test('the /login choice is honored, and adopted only by a profile without one', async ({
	browser
}) => {
	// A profile with none adopts it.
	const context = await freshContext(browser, 'en-US');
	const page = await context.newPage();
	await page.goto('/login');
	expect(await htmlLang(page)).toBe('en');
	await page.evaluate(
		() => ((window as Window & { __sameDocument?: boolean }).__sameDocument = true)
	);
	await page.getByRole('button', { name: 'Magyar', exact: true }).click();
	await expect(
		page.getByRole('heading', { name: t(m.login_heading, {}, 'hu'), exact: true })
	).toBeVisible();
	expect(await htmlLang(page), '<html lang> follows the /login switch').toBe('hu');
	expect(
		await page.evaluate(() => (window as Window & { __sameDocument?: boolean }).__sameDocument)
	).toBe(true);
	await signIn(page, userIdentity(), 'hu');
	await expectDashboardIn(page, 'hu');
	expect(languageOf(userIdentity().email), 'adopted into the profile').toBe('hu');
	await context.close();

	// A choice made on an earlier visit, still in this browser's storage, counts the same: the
	// plan's "adopted into the profile on first login if the profile has none".
	setLanguage(userIdentity().email, null);
	const shared = await freshContext(browser, 'en-US');
	await shared.addInitScript(() => localStorage.setItem('spotdl.locale', 'hu'));
	const sharedPage = await shared.newPage();
	await sharedPage.goto('/login');
	await expect(
		sharedPage.getByRole('heading', { name: t(m.login_heading, {}, 'hu'), exact: true })
	).toBeVisible();
	await signIn(sharedPage, userIdentity(), 'hu');
	await expectDashboardIn(sharedPage, 'hu');
	expect(languageOf(userIdentity().email), 'a stored choice is adopted too').toBe('hu');
	await shared.close();

	// A profile that already chose keeps its choice over this browser's /login one.
	setLanguage(adminIdentity().email, 'en');
	const second = await freshContext(browser, 'hu-HU');
	const secondPage = await second.newPage();
	await secondPage.goto('/login');
	await secondPage.getByRole('button', { name: 'Magyar', exact: true }).click();
	await signIn(secondPage, adminIdentity(), 'hu', 'en');
	await expectDashboardIn(secondPage, 'en');
	expect(languageOf(adminIdentity().email)).toBe('en');
	await second.close();
});
