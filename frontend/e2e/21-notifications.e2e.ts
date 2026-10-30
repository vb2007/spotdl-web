import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';
import type { Job } from '../src/lib/api';
import {
	ADMIN_STATE,
	LEDGER_TRACKS,
	USER_STATE,
	cancelUnlessSettled,
	spotifyTrackUrl
} from './support/stack';
import { openDashboard, submitUrl } from './support/ui';

// Spec 21 (v66): a browser notification when one of the user's own jobs settles. The browser's
// own Notification is replaced by a recorder in every page (`window.__notes`), so what the app
// asked to show is read back exactly; a real browser's notification is evidenced in the PR.
// Ledger tracks, so every job settles as a duplicate without a download.

function desktopOnly(): void {
	test.skip(
		test.info().project.name !== 'desktop',
		'one project is enough: the dashboards and identities are paired by hand here'
	);
}

interface Note {
	title: string;
	body: string;
	tag: string;
}

/** A context whose pages record notifications instead of showing them, with the permission
 * answered as `permission`. */
async function recordingContext(
	browser: Browser,
	storageState: string,
	permission: NotificationPermission
): Promise<BrowserContext> {
	const context = await browser.newContext({ storageState });
	await context.addInitScript((answer: NotificationPermission) => {
		const notes: { title: string; body: string; tag: string }[] = [];
		(window as unknown as { __notes: typeof notes }).__notes = notes;
		class Recorded {
			static permission: NotificationPermission = answer;
			static async requestPermission() {
				return answer;
			}
			onclick: (() => void) | null = null;
			constructor(title: string, options: NotificationOptions = {}) {
				notes.push({ title, body: options.body ?? '', tag: options.tag ?? '' });
			}
			close() {}
		}
		Object.defineProperty(window, 'Notification', { value: Recorded, configurable: true });
	}, permission);
	return context;
}

async function notes(pages: Page[]): Promise<Note[]> {
	const all: Note[] = [];
	for (const page of pages)
		all.push(...(await page.evaluate(() => (window as unknown as { __notes: Note[] }).__notes)));
	return all;
}

async function setNotifications(page: Page, on: boolean): Promise<void> {
	await page.goto('/account');
	const group = page.getByRole('group', { name: 'Notifications' });
	const saved = page.waitForResponse(
		(r) => r.request().method() === 'PATCH' && r.url().endsWith('/api/settings/notifications')
	);
	await group.getByRole('button', { name: on ? 'on' : 'off', exact: true }).click();
	expect((await saved).status()).toBe(200);
	await expect(group.getByRole('button', { name: on ? 'on' : 'off', exact: true })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
}

async function settled(page: Page, jobId: string): Promise<Job> {
	let job: Job | undefined;
	await expect
		.poll(
			async () => {
				job = (await (await page.request.get(`/api/jobs/${jobId}`)).json()) as Job;
				return job.status.lifecycle;
			},
			{ timeout: 180_000 }
		)
		.toBe('settled');
	return job!;
}

test('the /account switch: a refused permission keeps it off and says why', async ({ browser }) => {
	desktopOnly();
	const context = await recordingContext(browser, USER_STATE, 'denied');
	const page = await context.newPage();
	try {
		// Off to begin with, whatever an earlier run left.
		await setNotifications(page, false);
		const group = page.getByRole('group', { name: 'Notifications' });
		const patches: string[] = [];
		page.on('request', (r) => {
			if (r.method() === 'PATCH' && r.url().endsWith('/api/settings/notifications'))
				patches.push(r.postData() ?? '');
		});
		await group.getByRole('button', { name: 'on', exact: true }).click();
		await expect(group.getByText(/This browser blocks notifications from this site/)).toBeVisible();
		// Truthful: still off, and nothing was saved.
		await expect(group.getByRole('button', { name: 'off', exact: true })).toHaveAttribute(
			'aria-pressed',
			'true'
		);
		expect(patches).toEqual([]);
		await page.reload();
		await expect(
			page
				.getByRole('group', { name: 'Notifications' })
				.getByRole('button', { name: 'off', exact: true })
		).toHaveAttribute('aria-pressed', 'true');
	} finally {
		await context.close();
	}
});

test('one notification across two tabs for the user’s own job, none for someone else’s', async ({
	browser,
	baseURL
}) => {
	desktopOnly();
	test.setTimeout(480_000);
	const user = await recordingContext(browser, USER_STATE, 'granted');
	const admin = await recordingContext(browser, ADMIN_STATE, 'granted');
	const jobs: { id: string; state: string }[] = [];
	try {
		const settings = await user.newPage();
		await setNotifications(settings, true);
		await expect(
			settings.getByRole('group', { name: 'Notifications' }).getByText('This browser shows them.')
		).toBeVisible();
		await settings.close();

		const tabs = [await user.newPage(), await user.newPage()];
		for (const tab of tabs) await openDashboard(tab);

		// The user's own job: exactly one notification, from one of the two tabs.
		const own = await submitUrl(tabs[0], spotifyTrackUrl(LEDGER_TRACKS.submitMobile));
		jobs.push({ id: own.id, state: USER_STATE });
		const ownJob = await settled(tabs[0], own.id);
		await expect.poll(async () => (await notes(tabs)).length, { timeout: 15_000 }).toBe(1);
		// Long enough for a second tab's offer window to have passed, too.
		await tabs[0].waitForTimeout(3000);
		expect(await notes(tabs)).toEqual([
			{ title: ownJob.title, body: 'Done — 1 of 1', tag: `spotdl-web-job-${own.id}` }
		]);

		// The admin's job settling (in the admin's own dashboard, notifications off there) reaches
		// none of the user's tabs.
		await setNotifications(await admin.newPage(), false);
		const adminTab = await admin.newPage();
		await openDashboard(adminTab);
		const theirs = await submitUrl(adminTab, spotifyTrackUrl(LEDGER_TRACKS.submitDesktop));
		jobs.push({ id: theirs.id, state: ADMIN_STATE });
		await settled(adminTab, theirs.id);
		await tabs[0].waitForTimeout(3000);
		expect(await notes(tabs)).toHaveLength(1);
		expect(await notes([adminTab])).toEqual([]);
	} finally {
		for (const job of jobs) await cancelUnlessSettled(baseURL!, job.id, job.state);
		await setNotifications(await user.newPage(), false).catch(() => {});
		await user.close();
		await admin.close();
	}
});

for (const view of ['all', 'others'] as const) {
	test(`an admin in the ${view} view is notified only for their own jobs`, async ({
		browser,
		baseURL
	}) => {
		desktopOnly();
		test.setTimeout(480_000);
		const admin = await recordingContext(browser, ADMIN_STATE, 'granted');
		const user = await browser.newContext({ storageState: USER_STATE });
		const jobs: { id: string; state: string }[] = [];
		try {
			await setNotifications(await admin.newPage(), true);
			const tab = await admin.newPage();
			// The dashboard's stream carries the view's events (everyone's, or everyone else's); the
			// notifications open a `mine` stream of their own beside it.
			const streams: string[] = [];
			tab.on('request', (r) => {
				const url = new URL(r.url());
				if (url.pathname === '/api/stream') streams.push(url.search);
			});
			await tab.goto(`/?view=${view}`);
			await expect(tab.getByLabel('Spotify URL to submit')).toBeVisible();
			await expect.poll(() => streams.includes(`?view=${view}`)).toBe(true);
			await expect.poll(() => streams.includes('')).toBe(true);

			// Someone else's job settles in the admin's view: no notification.
			const userPage = await user.newPage();
			await openDashboard(userPage);
			const theirs = await submitUrl(userPage, spotifyTrackUrl(LEDGER_TRACKS.submitMobile));
			jobs.push({ id: theirs.id, state: USER_STATE });
			await settled(userPage, theirs.id);
			await tab.waitForTimeout(3000);
			expect(await notes([tab])).toEqual([]);

			// The admin's own (submitted in `others` too, where the dashboard's stream never shows
			// it): one.
			const own = await submitUrl(tab, spotifyTrackUrl(LEDGER_TRACKS.submitDesktop));
			jobs.push({ id: own.id, state: ADMIN_STATE });
			const ownJob = await settled(tab, own.id);
			await expect.poll(async () => (await notes([tab])).length, { timeout: 15_000 }).toBe(1);
			expect((await notes([tab]))[0].title).toBe(ownJob.title);
		} finally {
			for (const job of jobs) await cancelUnlessSettled(baseURL!, job.id, job.state);
			await setNotifications(await admin.newPage(), false).catch(() => {});
			await admin.close();
			await user.close();
		}
	});
}
