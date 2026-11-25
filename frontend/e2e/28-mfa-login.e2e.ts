import { expect, test, type Page } from '@playwright/test';
import { m, t } from './support/i18n';
import { LEDGER_TRACKS } from './support/stack';
import { freshTotp, totp } from './support/totp';

// Spec 28 (v71): an account with MFA on signs in through /login's second step, against the real
// upstream: the authenticator code (keyboard only), the /share round trip through it, and, when
// asked for, a recovery code and a wrong code (each spends something the account has little of).
//
// The identity is the slot's dedicated MFA one (E2E_MFA_*, `.git/agent-stack/e2e.s<slot>.env`),
// allowlisted on the slot; never a shared slot identity. One account holds one challenge and takes
// each 30 s code once, so this runs in the desktop project only, one login at a time.

const MFA = {
	email: process.env.E2E_MFA_EMAIL ?? '',
	password: process.env.E2E_MFA_PASSWORD ?? '',
	secret: process.env.E2E_MFA_TOTP_SECRET ?? ''
};
// Opt-in: a recovery code is spent for good (10 per account), and a wrong code counts against the
// account's 20 a day.
const RECOVERY_CODE = process.env.E2E_MFA_RECOVERY_CODE ?? '';
const WRONG_CODE_RUN = process.env.E2E_MFA_WRONG_CODE === '1';

const SHARE =
	`/share?title=${encodeURIComponent('Contact')}` +
	`&text=${encodeURIComponent(`Contact · Daft Punk https://open.spotify.com/track/${LEDGER_TRACKS.userSeed}`)}`;

test.describe.configure({ mode: 'serial' });

test.beforeEach(() => {
	test.skip(
		test.info().project.name !== 'desktop',
		'one MFA account, single-use codes: desktop only'
	);
	test.skip(!MFA.email || !MFA.secret, 'no E2E_MFA_* identity for this slot');
});

function codeField(page: Page) {
	return page.getByLabel(t(m.login_mfa_code), { exact: true });
}

function method(page: Page, label: () => string) {
	return page.getByRole('button', { name: t(label), exact: true });
}

/** The password step, ending on the second step with the code field focused. */
async function toSecondStep(page: Page): Promise<void> {
	await page.getByLabel(t(m.login_email), { exact: true }).fill(MFA.email);
	await page.getByLabel(t(m.login_password), { exact: true }).fill(MFA.password);
	await page.keyboard.press('Enter');
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(t(m.login_mfa_heading));
	await expect(codeField(page)).toBeFocused();
}

async function chooseAuthenticator(page: Page): Promise<void> {
	const authenticator = method(page, m.login_mfa_method_totp);
	if ((await authenticator.count()) === 0) return; // the only method: no choice shown
	if ((await authenticator.getAttribute('aria-pressed')) !== 'true') await authenticator.click();
}

test('an authenticator code finishes the sign-in, keyboard only', async ({ page, context }) => {
	await page.goto('/login');
	await toSecondStep(page);
	// No upstream token ever reaches the browser: only spotdl's own challenge id, httponly.
	const during = await context.cookies();
	expect(during.map((c) => c.name)).not.toContain('__Host-VB-MFA');
	expect(during.find((c) => c.name === 'SPOTDL_MFA')?.httpOnly).toBe(true);

	// The methods come before the field, in upstream's order; reach the authenticator by keys.
	const authenticator = method(page, m.login_mfa_method_totp);
	if ((await authenticator.count()) > 0) {
		for (
			let i = 0;
			i < 5 && !(await authenticator.evaluate((el) => el === document.activeElement));
			i++
		)
			await page.keyboard.press('Shift+Tab');
		await expect(authenticator).toBeFocused();
		await page.keyboard.press('Enter');
		await expect(authenticator).toHaveAttribute('aria-pressed', 'true');
		while (!(await codeField(page).evaluate((el) => el === document.activeElement)))
			await page.keyboard.press('Tab');
	}
	await expect(codeField(page)).toHaveAttribute('inputmode', 'numeric');
	await expect(codeField(page)).toHaveAttribute('autocomplete', 'one-time-code');
	// A single-key shortcut stays inert in the code field (`h` would open the help overlay).
	await page.keyboard.type('h');
	await expect(page.getByRole('dialog')).toHaveCount(0);
	await codeField(page).fill('');

	await page.keyboard.type(await freshTotp(MFA.secret));
	await page.keyboard.press('Enter');
	await expect(page.getByLabel(t(m.dashboard_submit_input_label), { exact: true })).toBeVisible();
	const after = await context.cookies();
	expect(after.map((c) => c.name)).toContain('SPOTDL_SESSION');
	expect(after.map((c) => c.name)).not.toContain('SPOTDL_MFA');
	expect(after.filter((c) => c.name.startsWith('__Host-VB'))).toEqual([]);
});

test('Back returns to the password step with what was typed', async ({ page }) => {
	await page.goto('/login');
	await toSecondStep(page);
	await page.getByRole('button', { name: t(m.login_mfa_back), exact: true }).click();
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(t(m.login_heading));
	await expect(page.getByLabel(t(m.login_email), { exact: true })).toHaveValue(MFA.email);
	await expect(page.getByRole('button', { name: t(m.login_connect), exact: true })).toBeFocused();
});

test('a share survives the round trip through the second step', async ({ page, baseURL }) => {
	await page.goto(SHARE);
	await expect(page).toHaveURL(/\/login\?next=/);
	await expect(page.getByText(t(m.login_share_waiting), { exact: true })).toBeVisible();
	await toSecondStep(page);
	await expect(page.getByText(t(m.login_share_waiting), { exact: true })).toBeVisible();
	await chooseAuthenticator(page);
	await codeField(page).fill(await freshTotp(MFA.secret));
	await page.keyboard.press('Enter');

	await expect(page).toHaveURL(`${baseURL}${SHARE}`);
	await expect(page.getByRole('heading', { level: 1 })).toHaveText(t(m.share_heading));
	await expect(page.getByRole('button', { name: t(m.share_queue), exact: true })).toBeFocused();
	// The login replaced its own entry: Back leaves the share for the page before it.
	await page.goBack();
	await expect(page).not.toHaveURL(/\/login/);
});

test('a wrong code says how many tries are left (opt-in)', async ({ page }) => {
	test.skip(
		!WRONG_CODE_RUN,
		'E2E_MFA_WRONG_CODE=1 spends one of the account’s 20 wrong codes a day'
	);
	await page.goto('/login');
	await toSecondStep(page);
	await chooseAuthenticator(page);
	// A code from long ago: never the current one.
	await codeField(page).fill(totp(MFA.secret, 1));
	await page.keyboard.press('Enter');
	await expect(page.locator('#login-error')).toHaveText(
		t(m.login_mfa_wrong_left, { count: 4, n: '4' })
	);
	await expect(codeField(page)).toBeFocused();
	await expect(codeField(page)).toHaveAttribute('aria-invalid', 'true');
});

test('a recovery code finishes the sign-in (opt-in)', async ({ page }) => {
	test.skip(!RECOVERY_CODE, 'E2E_MFA_RECOVERY_CODE=<an unused code> spends it for good');
	await page.goto('/login');
	await toSecondStep(page);
	await method(page, m.login_mfa_method_recovery).click();
	await expect(codeField(page)).toHaveAttribute('inputmode', 'text');
	await codeField(page).fill(RECOVERY_CODE);
	await page.keyboard.press('Enter');
	await expect(page.getByLabel(t(m.dashboard_submit_input_label), { exact: true })).toBeVisible();
});
