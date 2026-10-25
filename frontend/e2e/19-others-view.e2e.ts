import { expect, request as apiRequest, test, type Page } from '@playwright/test';
import type { Job } from '../src/lib/api';
import { m, t } from './support/i18n';
import { ADMIN_STATE, USER_STATE, missingTrackUrl, readSeed } from './support/stack';
import { jobToggle, openDashboard, submitUrl } from './support/ui';

// Spec 19 (v54). The admin's three-way view: mine, all users, other users. The seed gives the
// admin one job and the user one, so each view has a row it must show and one it mustn't.

function viewGroup(page: Page) {
	return page.getByRole('group', { name: t(m.queuectl_viewing_label), exact: true });
}

function viewButton(page: Page, label: () => string) {
	return viewGroup(page).getByRole('button', { name: t(label), exact: true });
}

/** Waits for the reconnect a view switch makes: the new stream's resync re-lists the jobs. */
async function switched(page: Page, act: () => Promise<void>): Promise<void> {
	const relisted = page.waitForResponse(
		(r) => r.request().method() === 'GET' && new URL(r.url()).pathname === '/api/jobs'
	);
	await act();
	await relisted;
	await expect(page.getByText(t(m.dashboard_count_loading))).toHaveCount(0);
}

async function expectView(page: Page, view: 'mine' | 'all' | 'others'): Promise<void> {
	const { admin, user } = readSeed();
	const labels = {
		mine: m.queuectl_viewing_mine,
		all: m.queuectl_viewing_all,
		others: m.queuectl_viewing_others
	};
	for (const [name, label] of Object.entries(labels)) {
		await expect(viewButton(page, label)).toHaveAttribute('aria-pressed', String(name === view));
	}
	await expect(page).toHaveURL(view === 'mine' ? /\/$/ : new RegExp(`\\?view=${view}$`));
	await expect(jobToggle(page, admin.title)).toHaveCount(view === 'others' ? 0 : 1);
	await expect(jobToggle(page, user.title)).toHaveCount(view === 'mine' ? 0 : 1);
}

test.describe('admin', () => {
	test.use({ storageState: ADMIN_STATE });

	test('three views by mouse and by Shift+V, kept in the URL across a reload', async ({ page }) => {
		await openDashboard(page);
		await expect(viewGroup(page).getByRole('button')).toHaveCount(3);
		await expectView(page, 'mine');

		await switched(page, () => viewButton(page, m.queuectl_viewing_others).click());
		await expectView(page, 'others');

		// A reload keeps the view, through the query string.
		await page.reload();
		await expect(page.getByText(t(m.dashboard_count_loading))).toHaveCount(0);
		await expectView(page, 'others');

		// Shift+V cycles mine -> all -> others -> mine, from wherever it is (focus off any field).
		await page.locator('body').click({ position: { x: 1, y: 1 } });
		await switched(page, () => page.keyboard.press('Shift+V'));
		await expectView(page, 'mine');
		await switched(page, () => page.keyboard.press('Shift+V'));
		await expectView(page, 'all');
		await switched(page, () => page.keyboard.press('Shift+V'));
		await expectView(page, 'others');

		// The help overlay lists it, from the registry.
		await page.keyboard.press('h');
		const help = page.getByRole('dialog');
		await expect(help.getByText(t(m.kbd_view_cycle), { exact: true })).toBeVisible();
		await page.keyboard.press('Escape');

		await switched(page, () => viewButton(page, m.queuectl_viewing_mine).click());
		await expectView(page, 'mine');

		// Back to the dashboard from another page brings back the view it was left in, not the
		// one the history entry was first loaded with (`?view=others`, from the reload above).
		await page.getByRole('link', { name: t(m.dashboard_nav_account), exact: true }).click();
		await expect(page).toHaveURL(/\/account$/);
		await page.goBack();
		await expect(page.getByText(t(m.dashboard_count_loading))).toHaveCount(0);
		await expectView(page, 'mine');
	});

	test('a link submitted in the others view is not shown there; a notice says where it went', async ({
		page,
		baseURL
	}) => {
		await page.goto('/?view=others');
		await expect(page.getByText(t(m.dashboard_count_loading))).toHaveCount(0);
		await expect(viewButton(page, m.queuectl_viewing_others)).toHaveAttribute(
			'aria-pressed',
			'true'
		);
		const url = missingTrackUrl();
		let job: Job | undefined;
		try {
			job = await submitUrl(page, url);
			await expect(
				page.getByText(t(m.dashboard_submit_added_elsewhere), { exact: true })
			).toBeVisible();
			const incoming = page.getByRole('list', { name: t(m.incoming_heading) });
			// Not optimistically, and not from its own events (others drops the admin's channel).
			await page.waitForTimeout(1500);
			await expect(page.getByText(url, { exact: true })).toHaveCount(0);
			await expect(incoming.getByText(url, { exact: true })).toHaveCount(0);

			// It's in the admin's own view.
			await switched(page, () => viewButton(page, m.queuectl_viewing_mine).click());
			await expect(page.getByText(url, { exact: true }).first()).toBeVisible();
			// The notice was about the view it was sent from.
			await expect(
				page.getByText(t(m.dashboard_submit_added_elsewhere), { exact: true })
			).toHaveCount(0);
		} finally {
			if (job) {
				const admin = await apiRequest.newContext({ baseURL, storageState: ADMIN_STATE });
				expect.soft((await admin.delete(`/api/jobs/${job.id}`)).status()).toBe(200);
				await admin.dispose();
			}
		}
	});
});

test.describe('non-admin', () => {
	test.use({ storageState: USER_STATE });

	test('?view= is ignored: no control, the own queue only, and the URL drops it', async ({
		page
	}) => {
		const { admin, user } = readSeed();
		const listings: string[] = [];
		page.on('request', (r) => {
			const path = new URL(r.url()).pathname;
			if (path === '/api/jobs' || path === '/api/tracks' || path === '/api/stream')
				listings.push(r.url());
		});
		for (const view of ['others', 'all']) {
			await page.goto(`/?view=${view}`);
			await expect(page.getByText(t(m.dashboard_count_loading))).toHaveCount(0);
			await expect(page).toHaveURL(/\/$/);
			await expect(viewGroup(page)).toHaveCount(0);
			await expect(jobToggle(page, user.title)).toBeVisible();
			await expect(jobToggle(page, admin.title)).toHaveCount(0);
			// Shift+V is admin-only: nothing happens.
			await page.keyboard.press('Shift+V');
			await expect(page).toHaveURL(/\/$/);
		}
		// The page never even asks for another view (the server would refuse it anyway).
		expect(listings.filter((u) => /[?&](view|all_users)=/.test(u))).toEqual([]);
	});
});
