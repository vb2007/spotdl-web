import { readFileSync, writeFileSync } from 'node:fs';
import { expect, request, test, type APIRequestContext } from '@playwright/test';
import { m, t } from './support/i18n';
import { describeFocus, tabTo } from './support/keyboard';
import { ADMIN_STATE, USER_STATE, userIdentity } from './support/stack';
import { loginViaUi, openDashboard } from './support/ui';

// Spec 25 (v69): who may sign in, managed by the admin on /users. Keyboard-only add and remove;
// the page and its nav entry are absent for a non-admin; and a removed user's open tabs are
// sent to /login live, saying why. The removal test takes the suite's own user identity off
// the allowlist, so it puts the address back and saves a fresh session for the specs after it
// (removing an address ends every session of it, the saved one included).

/** An address no one can sign in with (a reserved domain), unique per run and project. */
function scratchAddress(): string {
	return `v69-e2e-${test.info().project.name}-${Date.now()}@example.invalid`;
}

async function adminApi(baseURL: string): Promise<APIRequestContext> {
	return request.newContext({ baseURL, storageState: ADMIN_STATE });
}

/** Puts the user identity back on the allowlist (if it isn't) and saves a new session for it,
 * as global setup does (a request context never sends a `Secure` cookie over plain HTTP). */
async function restoreUser(baseURL: string): Promise<void> {
	const admin = await adminApi(baseURL);
	try {
		const answer = await admin.post('/api/admin/allowlist', {
			data: { email: userIdentity().email }
		});
		expect([201, 409]).toContain(answer.status());
	} finally {
		await admin.dispose();
	}
	const context = await request.newContext({ baseURL });
	try {
		const login = await context.post('/api/auth/login', {
			data: { email: userIdentity().email, password: userIdentity().password }
		});
		expect(login.ok(), `the user identity signs in again: ${login.status()}`).toBe(true);
		await context.storageState({ path: USER_STATE });
	} finally {
		await context.dispose();
	}
	const state = JSON.parse(readFileSync(USER_STATE, 'utf8')) as { cookies: { secure: boolean }[] };
	for (const cookie of state.cookies) cookie.secure = false;
	writeFileSync(USER_STATE, JSON.stringify(state));
}

test.describe('as the admin', () => {
	test.use({ storageState: ADMIN_STATE });

	test('adds and removes an address with the keyboard only', async ({ page }) => {
		const address = scratchAddress();
		await openDashboard(page);
		// `g u`, the go-to binding (help overlay: "Users").
		await page.keyboard.press('g');
		await page.keyboard.press('u');
		await page.waitForURL('**/users');
		await expect(page.getByRole('heading', { name: t(m.users_heading), level: 1 })).toBeVisible();
		const list = page.getByRole('list', { name: t(m.users_list_heading) });
		await expect(list).toBeVisible();

		const field = page.getByLabel(t(m.users_add_label), { exact: true });
		await tabTo(page, field);
		// A malformed address: the backend's code, said under the field.
		await page.keyboard.type('not-an-address');
		await page.keyboard.press('Enter');
		await expect(page.getByText(t(m.error_invalid_email), { exact: true })).toBeVisible();
		await expect(field).toBeFocused();

		await page.keyboard.press('ControlOrMeta+a');
		await page.keyboard.type(address.toUpperCase());
		await page.keyboard.press('Enter');
		await expect(
			page.getByRole('status').filter({ hasText: t(m.users_added, { email: address }) })
		).toBeVisible();
		const row = list.getByRole('listitem').filter({ hasText: address });
		await expect(row).toContainText(t(m.users_never_signed_in));
		// Focus went back to the field, for the next address.
		await expect(field).toBeFocused();

		// The same address again: already allowed.
		await page.keyboard.type(address);
		await page.keyboard.press('Enter');
		await expect(page.getByText(t(m.error_email_already_allowed), { exact: true })).toBeVisible();
		await page.keyboard.press('ControlOrMeta+a');
		await page.keyboard.press('Delete');

		// The admin's own row has no remove control at all.
		const adminRow = list
			.getByRole('listitem')
			.filter({ has: page.getByText(t(m.users_admin_badge), { exact: true }) });
		await expect(adminRow).toHaveCount(1);
		await expect(adminRow.getByRole('button')).toHaveCount(0);

		const remove = page.getByRole('button', { name: t(m.users_remove_named, { email: address }) });
		await tabTo(page, remove);
		await page.keyboard.press('Enter');
		const dialog = page.getByRole('alertdialog');
		await expect(dialog).toBeVisible();
		await expect(dialog).toContainText(t(m.users_remove_body));
		// Focus starts on the safe button: Escape keeps the address.
		await expect(dialog.getByRole('button', { name: t(m.users_remove_cancel) })).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(dialog).toBeHidden();
		await expect(row).toHaveCount(1);

		await tabTo(page, remove);
		await page.keyboard.press('Enter');
		await expect(dialog).toBeVisible();
		await tabTo(page, dialog.getByRole('button', { name: t(m.users_remove_confirm) }));
		await page.keyboard.press('Enter');
		await expect(
			page.getByRole('status').filter({ hasText: t(m.users_removed, { email: address }) })
		).toBeVisible();
		await expect(row).toHaveCount(0);
		// The removed row's button is gone: focus is on the list's heading, not lost to the body.
		await expect.poll(() => describeFocus(page)).toContain('users-list-heading');
	});
});

test.describe('as a non-admin', () => {
	test.use({ storageState: USER_STATE });

	test('the nav entry is absent and /users asks nothing of the admin API', async ({ page }) => {
		const adminCalls: string[] = [];
		page.on('request', (r) => {
			if (new URL(r.url()).pathname.startsWith('/api/admin/allowlist')) adminCalls.push(r.url());
		});
		await openDashboard(page);
		await expect(page.locator('a[href="/users"]')).toHaveCount(0);
		await page.goto('/account');
		await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
		await expect(page.locator('a[href="/users"]')).toHaveCount(0);
		await page.goto('/users');
		await expect(page.getByRole('heading', { name: t(m.adminonly_heading) })).toBeVisible();
		await expect(page.locator('a[href="/users"]')).toHaveCount(0);
		await expect(page.getByRole('list', { name: t(m.users_list_heading) })).toHaveCount(0);
		expect(adminCalls).toEqual([]);
	});
});

test('a removed user is sent to /login live, saying why, and their other tab follows', async ({
	browser,
	baseURL
}) => {
	// A fresh sign-in of its own: the saved session is ended by the removal anyway.
	const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
	// And a second, unrelated browser on a page with no stream, reloaded after the removal: the
	// server says the session was a removed one (`access_removed`), so it says why too.
	const lone = await browser.newContext({ storageState: { cookies: [], origins: [] } });
	const admin = await adminApi(baseURL!);
	try {
		const dashboard = await context.newPage();
		await loginViaUi(dashboard, userIdentity());
		await openDashboard(dashboard);
		const other = await context.newPage();
		await other.goto('/account');
		await expect(other.getByRole('heading', { level: 1 })).toBeVisible();
		const stats = await lone.newPage();
		await loginViaUi(stats, userIdentity());
		await stats.goto('/stats');
		await expect(stats.getByRole('heading', { level: 1 })).toBeVisible();

		const removed = await admin.delete(
			`/api/admin/allowlist/${encodeURIComponent(userIdentity().email)}`
		);
		expect(removed.status()).toBe(204);

		// Live: the stream's `session.revoked`, not the next 5s poll (well inside its window).
		await dashboard.waitForURL('**/login', { timeout: 4_000 });
		await expect(
			dashboard.getByRole('status').filter({ hasText: t(m.login_access_removed) })
		).toBeVisible();
		// The other tab follows through the session channel, with the same reason.
		await other.waitForURL('**/login', { timeout: 4_000 });
		await expect(
			other.getByRole('status').filter({ hasText: t(m.login_access_removed) })
		).toBeVisible();
		await stats.reload();
		await stats.waitForURL('**/login');
		await expect(
			stats.getByRole('status').filter({ hasText: t(m.login_access_removed) })
		).toBeVisible();
	} finally {
		await admin.dispose();
		await lone.close();
		await context.close();
		await restoreUser(baseURL!);
	}
});
