import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { expect, request, test, type Page, type Response } from '@playwright/test';
import type { Job, JobTracksPage, OutputSettings, RetentionSettings } from '../src/lib/api';
import { HU_PHYSICAL, bindingsFor, chordLabel } from '../src/lib/keyboard/bindings';
import { requireQuietWorker, requireSafeSweep } from './support/guards';
import {
	HU,
	describeFocus,
	expectFocusInList,
	focusedList,
	focusedRow,
	huPress,
	rowIds,
	tabStopsIn,
	tabTo
} from './support/keyboard';
import {
	ADMIN_STATE,
	USER_STATE,
	cancelUnlessSettled,
	isSettled,
	ledgerMisses,
	markSweepRequested,
	readSeed,
	recordSpecSweep,
	restoreSettings,
	restoreSweepReport,
	restoreWorker,
	serverTrackFile,
	snapshotSweepReport,
	spotifyTrackUrl,
	stageSettings,
	stageWorker,
	userIdentity,
	waitForJob
} from './support/stack';
import { TITLE, anyTitle, m, prefix, projectLang, t } from './support/i18n';
import { baseLocale, overwriteGetLocale } from '../src/lib/paraglide/runtime.js';
import { jobRow, jobToggle, openDashboard } from './support/ui';

// Spec 14 (v45): every journey without the mouse. Each test drives the page through
// `page.keyboard` (or trusted CDP key events for the Hungarian layout) and never clicks;
// `goto` only stands in for typing an address. The journeys run on the desktop project: the
// mobile project emulates a touch phone, and only the layout-independent checks (one Tab stop,
// the skip link) run there too.

// v46: the bindings table's labels and key names are message functions; in Node they render
// in whatever the runtime's locale says, so it follows the project's (the `hu` project runs
// this spec in Hungarian).
test.beforeEach(() => overwriteGetLocale(() => projectLang()));
test.afterAll(() => overwriteGetLocale(() => baseLocale));

/** Ledger tracks (Daft Punk, Discovery) no other spec submits: submitted with the worker
 * paused, they are held, never downloaded. */
const HELD_TRACKS = {
	retry: '098ttCNmncrO4YvqWUNMvn', // High Life
	cancel: '186hvCTyrni4KT9nwIQ7zS' // Superheroes
} as const;

/** Another ledger track, for a second settled row next to the seed. */
const NEIGHBOUR_TRACK = '2LD2gT7gwAurzdQDQtILds'; // Veridis Quo

function desktopOnly(): void {
	test.skip(
		test.info().project.name === 'mobile',
		'keyboard journeys run on the desktop project (the mobile one emulates a touch phone)'
	);
}

/** The response to `method path` (for `waitForResponse`). */
function sent(method: string, path: string | RegExp): (r: Response) => boolean {
	return (r) => {
		if (r.request().method() !== method) return false;
		const actual = new URL(r.url()).pathname;
		return typeof path === 'string' ? actual === path : path.test(actual);
	};
}

/** Puts focus on the row `id` of `list` by keyboard alone: into the list with j, then j/k
 * towards it, re-reading the order after each press (live rows can land meanwhile). */
async function focusRowByKeys(page: Page, list: string, id: string): Promise<void> {
	if ((await focusedList(page)) !== list) await page.keyboard.press('j');
	await expectFocusInList(page, list);
	for (let presses = 0; presses < 200; presses++) {
		const ids = await rowIds(page, list);
		const target = ids.indexOf(id);
		expect(target, `row ${id} is in list ${list}`).toBeGreaterThanOrEqual(0);
		const at = ids.indexOf((await focusedRow(page)) ?? '');
		if (at === target) return;
		await page.keyboard.press(at < target ? 'j' : 'k');
	}
	throw new Error(`couldn't reach row ${id} in ${list}`);
}

/** Opens the focused job (if closed) and waits for its tracks, so → can move into them. */
async function openJob(page: Page, jobId: string): Promise<void> {
	const toggle = page.locator(`[data-kb-row="${jobId}"] > .row [data-kb-item]`);
	if ((await toggle.getAttribute('aria-expanded')) !== 'true') await page.keyboard.press('Enter');
	await expect(toggle).toHaveAttribute('aria-expanded', 'true');
	await expect(
		page.locator(`[data-kb-list="job-tracks:${jobId}"] [data-kb-row]`).first()
	).toBeVisible();
}

/** v52 (D5): types `text` into the focused job search and waits for that search's own answer.
 * The box re-lists only after a debounce, so a wait on the rows alone (or on "loading" being
 * gone) could pass on the list from before the search (the seed row, or an archived-toggle
 * reload's rows), which the search's answer then re-rendered under the next key press. The
 * store applies only its newest request's answer, so once this one has landed and the list
 * stopped loading, the rows are the search's. */
async function typeSearch(page: Page, text: string): Promise<void> {
	const answered = page.waitForResponse((r) => {
		const url = new URL(r.url());
		return url.pathname === '/api/jobs' && url.searchParams.get('q') === text;
	});
	await page.keyboard.type(text);
	await answered;
	await expect(page.getByText(t(m.dashboard_count_loading))).toHaveCount(0);
}

/** Leaves whatever text field has focus without the mouse (Tab onwards), so single keys act. */
async function leaveField(page: Page): Promise<void> {
	await page.keyboard.press('Tab');
}

const noOpenDialog = (page: Page) => expect(page.locator('dialog[open]')).toHaveCount(0);

/** No element is focusable inside an `aria-hidden` subtree (screen readers can't name it). */
async function expectNoHiddenFocusables(page: Page): Promise<void> {
	const hidden = await page.evaluate(() =>
		[...document.querySelectorAll<HTMLElement>('[aria-hidden="true"]')]
			.flatMap((h) => [h, ...h.querySelectorAll<HTMLElement>('*')])
			.filter(
				(e) =>
					e.matches('a[href], button, input, select, textarea, [tabindex]') &&
					e.tabIndex >= 0 &&
					!(e as HTMLButtonElement).disabled
			)
			.map((e) => e.outerHTML.slice(0, 80))
	);
	expect(hidden).toEqual([]);
}

test.describe('as the admin', () => {
	test.use({ storageState: ADMIN_STATE, acceptDownloads: true });

	test('the job list is one Tab stop; an open job adds its controls and one stop for its tracks', async ({
		page
	}) => {
		const { admin } = readSeed();
		await openDashboard(page);
		// Archived jobs shown, so the list has many rows (setup leaves one unarchived).
		await page.keyboard.press('Shift+A');
		await expect(
			page.getByRole('button', { name: t(m.queuectl_show_archived), exact: true })
		).toHaveAttribute('aria-pressed', 'true');
		await expect.poll(async () => (await rowIds(page, 'jobs')).length).toBeGreaterThan(10);
		await expect(page.locator(`[data-kb-row="${admin.jobId}"]`)).toHaveCount(1);
		expect(await tabStopsIn(page, 'jobs')).toBe(1);
		// Still one stop after j/k moved the current row.
		await page.keyboard.press('j');
		await page.keyboard.press('j');
		await page.keyboard.press('j');
		await page.keyboard.press('k');
		expect(await tabStopsIn(page, 'jobs')).toBe(1);

		// Counted by pressing Tab across it: from the control before the list, one press lands
		// in it and the next leaves it, however many rows it has.
		const reverse = page.getByRole('button', {
			name: prefix(t(m.queuectl_dir_label_asc).split(' (')[0])
		});
		await tabTo(page, reverse);
		await page.keyboard.press('Tab');
		await expectFocusInList(page, 'jobs');
		await page.keyboard.press('Tab');
		expect(await focusedList(page), `left the list (at ${await describeFocus(page)})`).not.toBe(
			'jobs'
		);

		// Open the seed job: its own controls and its track list (one stop) join the order.
		await page.keyboard.press('Shift+Tab');
		await focusRowByKeys(page, 'jobs', admin.jobId);
		await openJob(page, admin.jobId);
		expect(await tabStopsIn(page, `job-tracks:${admin.jobId}`)).toBe(1);
		await page.keyboard.press('Tab');
		await expect(
			jobRow(page, admin.title).getByRole('button', {
				name: t(m.job_archive_label, { title: admin.title }),
				exact: true
			})
		).toBeFocused();
		await page.keyboard.press('Tab');
		await expectFocusInList(page, `job-tracks:${admin.jobId}`);
		await page.keyboard.press('Tab');
		expect(String(await focusedList(page))).not.toMatch(/^job/);
		await page.keyboard.press('Escape');
	});

	test('skip link, find a job with /, open it and move into its tracks', async ({ page }) => {
		desktopOnly();
		const { admin } = readSeed();
		await openDashboard(page);

		// The skip link is the first stop and lands on the queue itself (v47: its heading, past
		// the submit form, the incoming submissions and the Waterfall).
		await page.keyboard.press('Tab');
		await expect(
			page.getByRole('link', { name: t(m.layout_skip_to_queue), exact: true })
		).toBeFocused();
		await page.keyboard.press('Enter');
		await expect(page.locator('#queue-heading')).toBeFocused();

		await page.keyboard.press('/');
		await expect(page.locator('#queue-search')).toBeFocused();
		await typeSearch(page, admin.title);
		await expect(
			page.getByRole('list', { name: t(m.dashboard_list_jobs), exact: true }).getByRole('listitem')
		).toHaveCount(1);
		await tabTo(page, jobToggle(page, admin.title));

		await openJob(page, admin.jobId);
		const toggle = jobToggle(page, admin.title);
		await expect(toggle).toBeFocused();
		await page.keyboard.press('ArrowRight');
		await expect.poll(() => focusedRow(page)).toBe(admin.trackId);
		expect(await focusedList(page)).toBe(`job-tracks:${admin.jobId}`);

		// Screen-reader sanity: the rows' names and expanded state, as the accessibility tree has
		// them (recorded with the run).
		await page.keyboard.press('o');
		const snapshot = await page
			.getByRole('list', { name: t(m.dashboard_list_jobs), exact: true })
			.ariaSnapshot();
		await test.info().attach('jobs-aria-snapshot.yml', { body: snapshot });
		const done = t(m.status_settled_complete);
		expect(snapshot).toContain(`button "${done} ${admin.title}`);
		expect(snapshot).toMatch(new RegExp(`button "${done} Get Lucky[^\\n]*\\[expanded\\]`));
		expect(snapshot).toMatch(
			new RegExp(`button "${t(m.state_skipped_duplicate)} ${admin.trackTitle.slice(0, 10)}`)
		);
		await expectNoHiddenFocusables(page);

		// ← closes the track, ← again goes back to its job, Esc closes the job.
		await page.keyboard.press('ArrowLeft');
		await expect.poll(() => focusedRow(page)).toBe(admin.trackId);
		await page.keyboard.press('ArrowLeft');
		await expect(toggle).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(toggle).toHaveAttribute('aria-expanded', 'false');
		await expect(toggle).toBeFocused();

		// Esc in the search clears it and leaves it.
		await page.keyboard.press('f');
		await expect(page.locator('#queue-search')).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(page.locator('#queue-search')).toHaveValue('');
		await expect(page.locator('#queue-search')).not.toBeFocused();
	});

	test('a reload keeps focus on the same track of an open job', async ({ page }) => {
		desktopOnly();
		const { items } = (await (
			await page.request.get('/api/jobs?include_archived=true&sort=track_count&dir=desc&limit=20')
		).json()) as { items: Job[] };
		const job = items.find(
			(j) => Object.values(j.track_counts).reduce((a, b) => a + (b ?? 0), 0) >= 3
		);
		expect(job, 'an admin job with three or more tracks on the dev stack').toBeDefined();
		await openDashboard(page);
		await page.keyboard.press('Shift+A');
		await page.keyboard.press('/');
		await typeSearch(page, job!.title);
		await expect.poll(() => rowIds(page, 'jobs')).toContain(job!.id);
		await leaveField(page);
		await focusRowByKeys(page, 'jobs', job!.id);
		await openJob(page, job!.id);
		await page.keyboard.press('ArrowRight');
		await page.keyboard.press('j');
		await page.keyboard.press('j');
		const nested = `job-tracks:${job!.id}`;
		expect(await focusedList(page)).toBe(nested);
		const tracks = await rowIds(page, nested);
		const track = await focusedRow(page);
		expect(track).toBe(tracks[2]);

		// `s` re-sorts: the list reloads (its skeleton replaces it, then it remounts with the
		// job still open). Focus comes back to the same track, and its list's roving state with it.
		await page.keyboard.press('s');
		await expect(page.getByText(t(m.dashboard_count_loading))).toHaveCount(0);
		await expect.poll(() => focusedRow(page), { message: 'focus after the reload' }).toBe(track);
		expect(await focusedList(page)).toBe(nested);
		expect(
			await page.evaluate(() => (document.activeElement as HTMLElement | null)?.tabIndex)
		).toBe(0);
		expect(await tabStopsIn(page, nested)).toBe(1);
		await page.keyboard.press('k');
		expect(await focusedRow(page)).toBe(tracks[1]);
	});

	test('load more tracks in an open job moves focus to its first new track', async ({ page }) => {
		desktopOnly();
		const { items } = (await (
			await page.request.get('/api/jobs?include_archived=true&sort=track_count&dir=desc&limit=20')
		).json()) as { items: Job[] };
		const job = items.find(
			(j) => Object.values(j.track_counts).reduce((a, b) => a + (b ?? 0), 0) >= 12
		);
		expect(job, 'an admin job with twelve or more tracks on the dev stack').toBeDefined();
		// The real API, paged in fives instead of fifties, so this job's tracks take several
		// pages (no job on the dev stack has more than one page of 50).
		await page.route(`**/api/jobs/${job!.id}/tracks*`, (route) => {
			const url = new URL(route.request().url());
			url.searchParams.set('limit', '5');
			return route.continue({ url: url.toString() });
		});
		await openDashboard(page);
		await page.keyboard.press('Shift+A');
		await page.keyboard.press('/');
		await typeSearch(page, job!.title);
		await expect.poll(() => rowIds(page, 'jobs')).toContain(job!.id);
		await leaveField(page);
		await focusRowByKeys(page, 'jobs', job!.id);
		await openJob(page, job!.id);
		const nested = `job-tracks:${job!.id}`;
		await expect.poll(async () => (await rowIds(page, nested)).length).toBe(5);

		// End on the last track loads the next page and lands on its first track.
		await page.keyboard.press('ArrowRight');
		await page.keyboard.press('End');
		await expect.poll(async () => (await rowIds(page, nested)).length).toBe(5);
		await page.keyboard.press('End');
		await expect.poll(async () => (await rowIds(page, nested)).length).toBe(10);
		await expect.poll(() => focusedRow(page)).toBe((await rowIds(page, nested))[5]);

		// Enter on the button itself, through to the last page (which removes the button):
		// focus still lands on the first new track, not on the job.
		const more = page.locator(`[data-kb-row="${job!.id}"] [data-kb-load-more]`);
		for (let i = 0; i < 10 && (await more.count()) > 0; i++) {
			const before = await rowIds(page, nested);
			await tabTo(page, more);
			await page.keyboard.press('Enter');
			await expect
				.poll(async () => (await rowIds(page, nested)).length)
				.toBeGreaterThan(before.length);
			await expect
				.poll(() => focusedRow(page), { message: 'focus after load more tracks' })
				.toBe((await rowIds(page, nested))[before.length]);
		}
		await expect(more).toHaveCount(0);
	});

	test('download a completed file by keyboard (checksum)', async ({ page }) => {
		desktopOnly();
		const { admin } = readSeed();
		const server = serverTrackFile(admin.trackId);
		await openDashboard(page);
		await focusRowByKeys(page, 'jobs', admin.jobId);
		await page.keyboard.press('ArrowRight');
		await openJob(page, admin.jobId);
		await page.keyboard.press('ArrowRight');
		await expect.poll(() => focusedRow(page)).toBe(admin.trackId);

		const downloadEvent = page.waitForEvent('download');
		await page.keyboard.press('d');
		const download = await downloadEvent;
		expect(await download.failure()).toBeNull();
		const sha256 = createHash('sha256')
			.update(await readFile(await download.path()))
			.digest('hex');
		expect(download.suggestedFilename()).toBe(server.name);
		expect(sha256).toBe(server.sha256);
		// Focus stays on the row.
		expect(await focusedRow(page)).toBe(admin.trackId);
	});

	test('archive and unarchive by keyboard; focus moves to the next row', async ({
		page,
		baseURL
	}) => {
		desktopOnly();
		test.setTimeout(240_000);
		const { admin } = readSeed();
		expect(ledgerMisses([NEIGHBOUR_TRACK]), 'the neighbour is a ledger hit').toEqual([]);
		const api = await request.newContext({ baseURL, storageState: ADMIN_STATE });
		// A second settled row above the seed (newer), resolved from the ledger: archiving it
		// must hand focus to the next row, the seed.
		const response = await api.post('/api/jobs', {
			data: { url: spotifyTrackUrl(NEIGHBOUR_TRACK) }
		});
		expect(response.status()).toBe(201);
		const extra = (await response.json()) as Job;
		const archivedAt = async (): Promise<string | null> =>
			((await (await api.get(`/api/jobs/${extra.id}`)).json()) as Job).archived_at;
		let lastArchived: string | null = null;
		try {
			await waitForJob(api, extra.id, isSettled, 150_000);
			await openDashboard(page);
			await expect(page.locator(`[data-kb-row="${extra.id}"]`)).toHaveCount(1);
			const before = await rowIds(page, 'jobs');
			const at = before.indexOf(extra.id);
			const neighbour = before[at + 1] ?? before[at - 1];
			expect(neighbour, 'a second row to land on').toBeDefined();
			await focusRowByKeys(page, 'jobs', extra.id);

			await page.keyboard.press('a');
			await expect.poll(archivedAt).not.toBeNull();
			await expect(page.locator(`[data-kb-row="${extra.id}"]`)).toHaveCount(0);
			// The row left: focus is on the next row (the previous one if it was last), never body.
			await expect.poll(() => focusedRow(page), { message: 'focus after archive' }).toBe(neighbour);

			await page.keyboard.press('Shift+A');
			await expect(
				page.getByRole('button', { name: t(m.queuectl_show_archived), exact: true })
			).toHaveAttribute('aria-pressed', 'true');
			await expect(page.locator(`[data-kb-row="${extra.id}"]`)).toHaveCount(1);
			await focusRowByKeys(page, 'jobs', extra.id);
			await expect(page.locator(`[data-kb-row="${extra.id}"]`)).toContainText(t(m.job_archived));
			await page.keyboard.press('a');
			await expect.poll(archivedAt).toBeNull();
			await expect(
				page
					.locator(`[data-kb-row="${extra.id}"]`)
					.getByRole('button', { name: anyTitle(t(m.job_archive_label, { title: TITLE })) })
			).toBeVisible();
			// Unarchiving in place keeps focus on the row.
			expect(await focusedRow(page)).toBe(extra.id);
			await page.keyboard.press('Shift+A');
			await expect(page.getByText(t(m.dashboard_count_loading))).toHaveCount(0);

			// The last row archived: focus goes to the one before it.
			const rows = await rowIds(page, 'jobs');
			const last = rows[rows.length - 1];
			const previous = rows[rows.length - 2];
			expect(previous, 'a row before the last').toBeDefined();
			lastArchived = last;
			await focusRowByKeys(page, 'jobs', last);
			await page.keyboard.press('a');
			await expect(page.locator(`[data-kb-row="${last}"]`)).toHaveCount(0);
			await expect
				.poll(() => focusedRow(page), { message: 'focus after the last row left' })
				.toBe(previous);
		} finally {
			// The last row (the seed, normally) comes back; the extra goes to the archive.
			if (lastArchived && lastArchived !== extra.id) {
				await api.post('/api/jobs/unarchive', { data: { job_ids: [lastArchived] } });
			}
			expect
				.soft(((await (await api.get(`/api/jobs/${admin.jobId}`)).json()) as Job).archived_at)
				.toBeNull();
			await cancelUnlessSettled(baseURL!, extra.id);
			await api.post('/api/jobs/archive', { data: { job_ids: [extra.id] } });
			await api.dispose();
		}
	});

	test('submit, retry a waiting track, cancel through the confirmation, priority keys', async ({
		page,
		baseURL
	}) => {
		desktopOnly();
		test.setTimeout(300_000);
		await requireQuietWorker(page.request);
		expect(ledgerMisses(Object.values(HELD_TRACKS)), 'held tracks are ledger hits').toEqual([]);
		const admin = await request.newContext({ baseURL, storageState: ADMIN_STATE });
		const created: Job[] = [];
		try {
			stageWorker({ paused: true });
			expect((await admin.post('/api/worker/pause')).ok()).toBe(true);
			await openDashboard(page);

			// Submit: `i`, the link, Enter; twice.
			for (const id of [HELD_TRACKS.retry, HELD_TRACKS.cancel]) {
				await page.keyboard.press('i');
				await expect(
					page.getByLabel(t(m.dashboard_submit_input_label), { exact: true })
				).toBeFocused();
				const response = page.waitForResponse(sent('POST', '/api/jobs'));
				await page.keyboard.type(spotifyTrackUrl(id));
				await page.keyboard.press('Enter');
				const r = await response;
				expect(r.status()).toBe(201);
				created.push((await r.json()) as Job);
				await leaveField(page);
			}
			// Held by the paused worker: `waiting` once download_track's pause gate has them.
			const [retryJob, cancelJob] = await Promise.all(
				created.map((job) =>
					waitForJob(admin, job.id, (j) => j.status.lifecycle === 'waiting', 150_000)
				)
			);
			const retryTrack = (
				(await (await admin.get(`/api/jobs/${retryJob.id}/tracks`)).json()) as JobTracksPage
			).items[0];
			await expect(page.locator(`[data-kb-row="${retryJob.id}"]`)).toHaveCount(1);

			// Shortcuts are inert in the priority input: j, x and ? change only the field.
			await focusRowByKeys(page, 'jobs', retryJob.id);
			await openJob(page, retryJob.id);
			const priority = page.getByLabel(t(m.job_priority_of, { title: retryJob.title }), {
				exact: true
			});
			await page.keyboard.press('Tab');
			await expect(priority).toBeFocused();
			const typedFrom = await priority.inputValue();
			await page.keyboard.type('jx?');
			await expect(priority).toBeFocused();
			await noOpenDialog(page);
			// A digit goes in (letters only leave a number field invalid).
			await page.keyboard.press('Control+a');
			await page.keyboard.type('9');
			await expect(priority).toHaveValue('9');
			// Esc from the field puts the typed value back, closes the row and returns to it;
			// nothing was saved.
			const changes: string[] = [];
			const onRequest = (r: { method(): string; url(): string }) => {
				if (r.method() === 'PATCH' && r.url().includes(`/api/jobs/${retryJob.id}`))
					changes.push(r.url());
			};
			page.on('request', onRequest);
			await page.keyboard.press('Escape');
			await expect(jobToggle(page, retryJob.title)).toHaveAttribute('aria-expanded', 'false');
			await expect(jobToggle(page, retryJob.title)).toBeFocused();
			await page.waitForTimeout(750);
			page.off('request', onRequest);
			expect(changes, 'Esc saved no priority').toEqual([]);
			await expect(priority).toHaveValue(typedFrom);

			// Priority: Shift+B raises, `-` lowers, `+` (Shift+3 on Hungarian) raises.
			const priorityOf = async () =>
				((await (await admin.get(`/api/jobs/${retryJob.id}`)).json()) as Job).priority;
			const start = await priorityOf();
			// The row takes one step at a time and drops a key pressed while the last step is
			// still settling in the page, which outlasts the moment the API has the new value.
			// So each step waits for its own response, and for the page to finish handling it.
			const step = async (press: () => Promise<void>, expected: number) => {
				const answered = page.waitForResponse(sent('PATCH', `/api/jobs/${retryJob.id}/priority`));
				await press();
				expect((await answered).ok()).toBe(true);
				await expect.poll(priorityOf).toBe(expected);
				await page.evaluate(() => new Promise((settled) => setTimeout(settled, 50)));
			};
			await step(() => page.keyboard.press('Shift+B'), start + 1);
			await step(() => huPress(page, HU.minus), start);
			await step(() => huPress(page, HU.plus), start + 1);
			await step(() => huPress(page, HU.minus), start);

			// Into its track, then retry it: held behind the pause, and focus stays on the same
			// row through the stream's patches of it.
			await page.keyboard.press('o');
			await openJob(page, retryJob.id);
			await page.keyboard.press('ArrowRight');
			await expect.poll(() => focusedRow(page)).toBe(retryTrack.id);
			const retried = page.waitForResponse(sent('POST', `/api/tracks/${retryTrack.id}/retry`));
			await page.keyboard.press('r');
			expect((await retried).ok()).toBe(true);
			const trackLi = page.locator(`[data-kb-row="${retryTrack.id}"]`);
			await expect(trackLi.getByRole('status').first()).toContainText(t(m.track_notice_retry_held));
			// The worker re-holds it (`waiting` again): an SSE patch of the focused row.
			await waitForJob(admin, retryJob.id, (j) => j.track_counts.waiting === 1, 90_000);
			await page.waitForTimeout(1500);
			expect(await focusedRow(page), 'focus after the stream patched the row').toBe(retryTrack.id);

			// Cancel the track: x asks, focus starts on the safe button; Esc keeps it and focus
			// comes back to the row.
			await page.keyboard.press('x');
			const dialog = page.getByRole('alertdialog', { name: t(m.track_cancel_title), exact: true });
			await expect(dialog).toBeVisible();
			await expect(
				dialog.getByRole('button', { name: t(m.track_cancel_keep), exact: true })
			).toBeFocused();
			await page.keyboard.press('Escape');
			await expect(dialog).toBeHidden();
			await expect.poll(() => focusedRow(page)).toBe(retryTrack.id);
			// Then for real: Tab to "cancel track", Enter.
			await page.keyboard.press('x');
			await expect(dialog).toBeVisible();
			await page.keyboard.press('Tab');
			await expect(
				dialog.getByRole('button', { name: t(m.track_cancel_confirm), exact: true })
			).toBeFocused();
			const cancelled = page.waitForResponse(sent('DELETE', `/api/tracks/${retryTrack.id}`));
			await page.keyboard.press('Enter');
			expect((await cancelled).ok()).toBe(true);
			await expect(dialog).toBeHidden();
			await expect.poll(() => focusedRow(page)).toBe(retryTrack.id);
			await page.keyboard.press('ArrowLeft');
			await page.keyboard.press('Escape');

			// Cancel a job: x asks; Tab to "cancel job", Enter. The store keeps a cancelled job's
			// row in the list (patched in place, as before v45), so focus stays on that row.
			await focusRowByKeys(page, 'jobs', cancelJob.id);
			await page.keyboard.press('x');
			const jobDialog = page.getByRole('alertdialog', { name: t(m.job_cancel_title), exact: true });
			await expect(jobDialog).toBeVisible();
			await expect(
				jobDialog.getByRole('button', { name: t(m.job_cancel_keep), exact: true })
			).toBeFocused();
			await page.keyboard.press('Tab');
			await expect(
				jobDialog.getByRole('button', { name: t(m.job_cancel_confirm), exact: true })
			).toBeFocused();
			const jobCancelled = page.waitForResponse(sent('DELETE', `/api/jobs/${cancelJob.id}`));
			await page.keyboard.press('Enter');
			expect((await jobCancelled).ok()).toBe(true);
			await expect(jobDialog).toBeHidden();
			await expect(page.locator(`[data-kb-row="${cancelJob.id}"]`)).toContainText(
				t(m.status_cancelled)
			);
			await expect
				.poll(() => focusedRow(page), { message: 'focus after cancel' })
				.toBe(cancelJob.id);
		} finally {
			try {
				for (const job of created) {
					const current = (await (await admin.get(`/api/jobs/${job.id}`)).json()) as Job;
					if (!['settled', 'failed', 'cancelled'].includes(current.status.lifecycle)) {
						await admin.delete(`/api/jobs/${job.id}`);
					}
				}
			} finally {
				restoreWorker();
			}
			if (created.length > 0) {
				await admin.post('/api/jobs/archive', { data: { job_ids: created.map((j) => j.id) } });
			}
			await admin.dispose();
		}
	});

	test('switch scope, toggle filters and sort', async ({ page }) => {
		desktopOnly();
		await openDashboard(page);
		const scope = page.getByRole('group', { name: t(m.queuectl_scope_label), exact: true });

		await page.keyboard.press('2');
		await expect(
			scope.getByRole('button', { name: t(m.queuectl_scope_tracks), exact: true })
		).toHaveAttribute('aria-pressed', 'true');
		await expect(
			page.getByRole('list', { name: t(m.dashboard_list_tracks), exact: true }).first()
		).toBeVisible();
		await page.keyboard.press('j');
		await expectFocusInList(page, 'tracks');
		await page.keyboard.press('1');
		await expect(
			scope.getByRole('button', { name: t(m.queuectl_scope_jobs), exact: true })
		).toHaveAttribute('aria-pressed', 'true');
		await expect(
			page.getByRole('group', { name: t(m.queuectl_filter_jobs_label), exact: true })
		).toBeVisible();

		// Filters: Shift+F into the chips, arrows roam, Space toggles. With archived jobs shown
		// (Shift+A) there are several statuses to roam.
		await page.keyboard.press('Shift+A');
		await expect(
			page.getByRole('button', { name: t(m.queuectl_show_archived), exact: true })
		).toHaveAttribute('aria-pressed', 'true');
		await expect
			.poll(() => page.locator('[data-kb-list="chips"] [data-kb-row]').count())
			.toBeGreaterThan(1);
		await page.keyboard.press('Shift+F');
		await expectFocusInList(page, 'chips');
		const first = await focusedRow(page);
		await page.keyboard.press('ArrowRight');
		const second = await focusedRow(page);
		expect(second).not.toBe(first);
		await page.keyboard.press('ArrowLeft');
		expect(await focusedRow(page)).toBe(first);
		const chip = page.locator(`[data-kb-list="chips"] [data-kb-row="${first}"]`);
		await page.keyboard.press('Space');
		await expect(chip).toHaveAttribute('aria-pressed', 'true');
		await page.keyboard.press('Space');
		await expect(chip).toHaveAttribute('aria-pressed', 'false');
		// The chips are one Tab stop.
		expect(await tabStopsIn(page, 'chips')).toBe(1);

		// Sort: s cycles the field.
		const sort = page.locator('#queue-sort');
		await expect(sort).toHaveValue('created_at');

		// The sort select isn't a typing target (owner's review): the single keys work on it,
		// while its own arrows still pick an option and keep focus there.
		await tabTo(page, sort);
		await page.keyboard.press('h');
		await expect(page.locator('dialog[data-kb-help]')).toHaveJSProperty('open', true);
		await page.keyboard.press('h');
		await noOpenDialog(page);
		await expect(sort).toBeFocused();
		await page.keyboard.press('2');
		await expect(
			scope.getByRole('button', { name: t(m.queuectl_scope_tracks), exact: true })
		).toHaveAttribute('aria-pressed', 'true');
		await page.keyboard.press('1');
		await expect(
			scope.getByRole('button', { name: t(m.queuectl_scope_jobs), exact: true })
		).toHaveAttribute('aria-pressed', 'true');
		await expect(page.getByText(t(m.dashboard_count_loading))).toHaveCount(0);
		await expect(sort).toBeFocused();
		await expect(sort).toHaveValue('created_at');
		await page.keyboard.press('ArrowDown');
		await expect(sort).not.toHaveValue('created_at');
		await expect(sort).toBeFocused();
		await page.keyboard.press('ArrowUp');
		await expect(sort).toHaveValue('created_at');
		await expect(sort).toBeFocused();
		await expect(page.getByText(t(m.dashboard_count_loading))).toHaveCount(0);
		await page.keyboard.press('s');
		await expect(sort).toHaveValue('title');
		await page.keyboard.press('s');
		await expect(sort).not.toHaveValue('title');
		for (let i = 0; i < 6 && (await sort.inputValue()) !== 'created_at'; i++) {
			await page.keyboard.press('s');
		}
		await expect(sort).toHaveValue('created_at');
		await expect(page.getByText(t(m.dashboard_count_loading))).toHaveCount(0);
	});

	test('load more by keyboard focuses the first new row', async ({ page }) => {
		desktopOnly();
		await openDashboard(page);
		await page.keyboard.press('Shift+A');
		await expect(
			page.getByRole('button', { name: t(m.queuectl_show_archived), exact: true })
		).toHaveAttribute('aria-pressed', 'true');
		await expect(page.getByText(t(m.dashboard_count_loading))).toHaveCount(0);
		// Load more: with archived jobs shown the admin has several pages. End goes to the last
		// loaded row; End there (and Shift+G) loads the next page and focuses its first row.
		await expect(
			page.getByRole('button', { name: t(m.dashboard_more_jobs), exact: true })
		).toBeVisible();
		await page.keyboard.press('j');
		await expectFocusInList(page, 'jobs');
		await page.keyboard.press('End');
		const loaded = await rowIds(page, 'jobs');
		await expect.poll(() => focusedRow(page)).toBe(loaded[loaded.length - 1]);
		await page.keyboard.press('End');
		await expect
			.poll(async () => (await rowIds(page, 'jobs')).length)
			.toBeGreaterThan(loaded.length);
		const more = await rowIds(page, 'jobs');
		await expect
			.poll(() => focusedRow(page), { message: 'focus after load more' })
			.toBe(more[loaded.length]);
		await page.keyboard.press('Shift+G');
		await expect.poll(async () => (await rowIds(page, 'jobs')).length).toBeGreaterThan(more.length);
		const third = await rowIds(page, 'jobs');
		await expect.poll(() => focusedRow(page)).toBe(third[more.length]);
		await page.keyboard.press('Shift+A');
	});

	test('every route through g chords; focus lands on each page’s h1', async ({ page }) => {
		desktopOnly();
		await openDashboard(page);
		const routes: [string, string, string][] = [
			['s', '/settings', t(m.settings_heading)],
			['l', '/library', t(m.library_heading)],
			['t', '/stats', t(m.stats_heading)],
			['a', '/account', t(m.account_heading)],
			['d', '/', 'spotdl-web']
		];
		for (const [key, path, heading] of routes) {
			await page.keyboard.press('g');
			await expect(page.getByRole('status').filter({ hasText: t(m.kbd_then) })).toBeVisible();
			await page.keyboard.press(key);
			await expect(page).toHaveURL(path);
			const h1 = page.locator('h1');
			await expect(h1).toContainText(heading);
			await expect(h1).toBeFocused();
			// The page is announced (SvelteKit's route announcer).
			await expect(page.locator('#svelte-announcer')).toHaveText(await page.title());
			await expectNoHiddenFocusables(page);
		}
		// Esc drops a chord, and so does waiting past its 1.5s: the next `a` goes nowhere.
		const chordReadout = page.getByRole('status').filter({ hasText: t(m.kbd_then) });
		await page.keyboard.press('g');
		await page.keyboard.press('Escape');
		await expect(chordReadout).toHaveCount(0);
		await page.keyboard.press('a');
		await page.keyboard.press('g');
		await expect(chordReadout).toBeVisible();
		await expect(chordReadout).toHaveCount(0, { timeout: 2500 });
		await page.keyboard.press('a');
		await page.waitForTimeout(500);
		await expect(page).toHaveURL('/');

		// The help overlay: h opens it with focus on "close", Esc closes it, focus returns.
		await page.keyboard.press('g');
		await page.keyboard.press('a');
		await expect(page).toHaveURL('/account');
		await expect(page.locator('h1')).toHaveText(t(m.account_heading));
		await expect(page.locator('h1')).toBeFocused();
		await page.keyboard.press('h');
		const help = page.getByRole('dialog', { name: t(m.help_title), exact: true });
		await expect(help).toBeVisible();
		await expect(help.getByRole('button', { name: t(m.help_close), exact: true })).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(help).toBeHidden();
		await expect(page.locator('h1')).toBeFocused();
	});

	test('change a setting on /settings and /account by keyboard', async ({ page, baseURL }) => {
		desktopOnly();
		const api = await request.newContext({ baseURL, storageState: ADMIN_STATE });
		const output = (await (await api.get('/api/settings/output')).json()) as OutputSettings;
		const retention = (await (
			await api.get('/api/settings/retention')
		).json()) as RetentionSettings;
		try {
			await page.goto('/settings');
			const section = page.getByRole('region', { name: t(m.settings_output_heading), exact: true });
			// Inert in a settings text field.
			const template = section.getByLabel(t(m.settings_output_template), { exact: true });
			await tabTo(page, template, { max: 200 });
			await page.keyboard.press('End');
			await page.keyboard.type('jx?');
			await expect(template).toHaveValue(`${output.output_template}jx?`);
			await noOpenDialog(page);
			for (let i = 0; i < 3; i++) await page.keyboard.press('Backspace');
			await expect(template).toHaveValue(output.output_template);

			// Not exact: a select inside its label is named with its selected option too.
			const bitrate = section.getByLabel(t(m.settings_output_bitrate));
			await tabTo(page, bitrate, { back: true });
			stageSettings({ default_bitrate: { original: output.default_bitrate, set: '?' } });
			await page.keyboard.press('ArrowDown');
			await expect(bitrate).not.toHaveValue(output.default_bitrate);
			const next = await bitrate.inputValue();
			stageSettings({ default_bitrate: { original: output.default_bitrate, set: next } });
			await tabTo(page, section.getByRole('button', { name: t(m.common_save), exact: true }));
			const saved = page.waitForResponse(sent('PATCH', '/api/settings/output'));
			await page.keyboard.press('Enter');
			expect((await saved).ok()).toBe(true);
			await expect(section.getByRole('status')).toHaveText(
				prefix(t(m.common_saved_at, { time: '' }).trim())
			);
			expect(
				((await (await api.get('/api/settings/output')).json()) as OutputSettings).default_bitrate
			).toBe(next);

			// /account: archive automatically after a number of days, Enter submits.
			await page.keyboard.press('g');
			await page.keyboard.press('a');
			await expect(page).toHaveURL('/account');
			const auto = page.getByRole('button', { name: t(m.account_retention_auto), exact: true });
			await tabTo(page, auto);
			await page.keyboard.press('Enter');
			await expect(auto).toHaveAttribute('aria-pressed', 'true');
			const days = page.getByLabel(t(m.account_retention_after), { exact: true });
			await tabTo(page, days);
			await page.keyboard.press('Control+a');
			await page.keyboard.type('jx?');
			await noOpenDialog(page);
			await page.keyboard.press('Control+a');
			await page.keyboard.type('412');
			const retained = page.waitForResponse(sent('PATCH', '/api/settings/retention'));
			await page.keyboard.press('Enter');
			expect((await retained).ok()).toBe(true);
			expect(
				((await (await api.get('/api/settings/retention')).json()) as RetentionSettings)
					.retention_days
			).toBe(412);
		} finally {
			await api.patch('/api/settings/output', {
				data: { default_bitrate: output.default_bitrate }
			});
			restoreSettings();
			await api.patch('/api/settings/retention', {
				data: { retention_days: retention.retention_days }
			});
			await api.dispose();
		}
	});

	test('run the library sweep through its confirmation', async ({ page }) => {
		desktopOnly();
		await requireSafeSweep(page.request);
		snapshotSweepReport();
		try {
			await openDashboard(page);
			await page.keyboard.press('g');
			await page.keyboard.press('l');
			await expect(page).toHaveURL('/library');
			const start = page.getByRole('button', { name: t(m.library_start), exact: true });
			await expect(start).toBeEnabled();
			await tabTo(page, start);
			await page.keyboard.press('Enter');
			const dialog = page.getByRole('alertdialog', {
				name: t(m.library_confirm_title),
				exact: true
			});
			await expect(
				dialog.getByRole('button', { name: t(m.library_confirm_cancel), exact: true })
			).toBeFocused();
			await page.keyboard.press('Tab');
			await expect(
				dialog.getByRole('button', { name: t(m.library_start), exact: true })
			).toBeFocused();
			markSweepRequested();
			const posted = page.waitForResponse(sent('POST', '/api/library/sort'));
			await page.keyboard.press('Enter');
			expect((await posted).ok()).toBe(true);
			recordSpecSweep();
			await expect(
				page.getByText(prefix(t(m.library_last_finished, { when: '' }).trim()))
			).toBeVisible({ timeout: 30_000 });
		} finally {
			restoreSweepReport();
		}
	});

	test('shortcuts are inert while typing in the search and URL fields', async ({ page }) => {
		desktopOnly();
		await openDashboard(page);
		const rowsBefore = await rowIds(page, 'jobs');
		for (const [key, field] of [
			['f', page.locator('#queue-search')],
			['i', page.getByLabel(t(m.dashboard_submit_input_label), { exact: true })]
		] as const) {
			await page.keyboard.press(key);
			await expect(field).toBeFocused();
			await page.keyboard.type('jx?');
			await expect(field).toHaveValue('jx?');
			await expect(field).toBeFocused();
			await noOpenDialog(page);
			for (let i = 0; i < 3; i++) await page.keyboard.press('Backspace');
			await expect(field).toHaveValue('');
			await leaveField(page);
		}
		await expect(page.getByText(t(m.dashboard_count_loading))).toHaveCount(0);
		expect(await rowIds(page, 'jobs')).toEqual(rowsBefore);
	});

	test('browser chords reach the browser', async ({ page }) => {
		desktopOnly();
		await openDashboard(page);
		await page.evaluate(() => {
			(window as unknown as { kbSeen: string[] }).kbSeen = [];
			// Registered after the app's own window listener, so it sees the event after it.
			window.addEventListener('keydown', (e) => {
				(window as unknown as { kbSeen: string[] }).kbSeen.push(
					`${e.ctrlKey ? 'C' : ''}${e.metaKey ? 'M' : ''}${e.key}:${e.defaultPrevented}`
				);
			});
		});
		for (const chord of ['Control+f', 'Control+l', 'Meta+k', 'Control+h', 'Control+g']) {
			await page.keyboard.press(chord);
		}
		const seen = await page.evaluate(() => (window as unknown as { kbSeen: string[] }).kbSeen);
		// Every chord arrived untouched (nothing prevented its default), and none acted.
		expect(seen.filter((s) => s.endsWith(':true'))).toEqual([]);
		expect(seen.filter((s) => /^(C|M)[fklhg]:false$/.test(s))).toHaveLength(5);
		await expect(page.locator('#queue-search')).not.toBeFocused();
		await noOpenDialog(page);
	});

	test('Hungarian QWERTZ, emulated: ? and / alias, AltGr and y/z fire nothing', async ({
		page
	}) => {
		desktopOnly();
		await openDashboard(page);
		const help = page.getByRole('dialog', { name: t(m.help_title), exact: true });

		// `?` is Shift + the comma key: opens and closes the help.
		await huPress(page, HU.question);
		await expect(help).toBeVisible();
		await huPress(page, HU.question);
		await expect(help).toBeHidden();

		// `/` is Shift + 6: the search.
		await huPress(page, HU.slash);
		const search = page.locator('#queue-search');
		await expect(search).toBeFocused();
		// AltGr characters fire nothing there (CDP's Ctrl+Alt types no text on Linux; the real
		// Hungarian pass in the PR covers typing them), and the accented letters type.
		await huPress(page, HU.at);
		await huPress(page, HU.brace);
		await huPress(page, HU.oDoubleAcute);
		await huPress(page, HU.uDoubleAcute);
		await expect(search).toBeFocused();
		await expect(search).toHaveValue('őű');
		await noOpenDialog(page);
		await page.keyboard.press('Escape');

		// On a row, y, z, a dead key and AltGr characters do nothing at all.
		await page.keyboard.press('j');
		const row = await expectFocusInList(page, 'jobs');
		const url = page.url();
		for (const key of [HU.z, HU.y, HU.dead, HU.at, HU.brace, HU.backslash]) {
			await huPress(page, key);
			expect(await focusedRow(page), `${key.code} moved focus`).toBe(row);
		}
		await noOpenDialog(page);
		await expect(page.getByRole('status').filter({ hasText: t(m.kbd_then) })).toHaveCount(0);
		expect(page.url()).toBe(url);
		// AltGr with a letter that is a binding (AltGr+V is `@`; V isn't bound, but AltGr+E is
		// the euro sign on Hungarian and `e` is): still nothing.
		await huPress(page, { key: '€', code: 'KeyE', altGr: true, text: '€' });
		await huPress(page, { key: 'x', code: 'KeyX', altGr: true });
		await noOpenDialog(page);
		expect(await focusedRow(page)).toBe(row);
	});
});

test.describe('the help overlay', () => {
	async function overlayEntries(page: Page) {
		const help = page.getByRole('dialog', { name: t(m.help_title), exact: true });
		await expect(help).toBeVisible();
		return help.locator('[data-binding]').evaluateAll((entries) =>
			entries.map((e) => ({
				id: (e as HTMLElement).dataset.binding ?? '',
				keys: [...e.querySelectorAll('kbd')].map((k) => k.textContent?.trim() ?? ''),
				hu: [...e.querySelectorAll('.hu')].map((k) => k.textContent?.trim() ?? ''),
				label: e.querySelector('dd')?.textContent?.trim() ?? ''
			}))
		);
	}

	function expected(routeId: string, isAdmin: boolean, signedIn = true) {
		return bindingsFor(routeId, isAdmin, signedIn).map((b) => ({
			id: b.id,
			keys: [...(b.prefix ? [b.prefix] : []), ...b.keys.map(chordLabel)],
			hu: b.keys.filter((k) => HU_PHYSICAL[k.key]).map((k) => `(${HU_PHYSICAL[k.key]})`),
			label: b.label()
		}));
	}

	// The overlay orders entries by group; the table may not. Compared as sets of rows.
	const byId = <T extends { id: string }>(rows: T[]) =>
		[...rows].sort((a, b) => a.id.localeCompare(b.id));

	for (const [who, state, isAdmin] of [
		['admin', ADMIN_STATE, true],
		['user', USER_STATE, false]
	] as const) {
		test(`lists exactly the registry's bindings for the ${who}, per route`, async ({ browser }) => {
			desktopOnly();
			const context = await browser.newContext({ storageState: state });
			const page = await context.newPage();
			try {
				for (const [path, routeId] of [
					['/', '/'],
					['/account', '/account'],
					...(isAdmin
						? ([
								['/settings', '/settings'],
								['/library', '/library'],
								['/stats', '/stats']
							] as const)
						: [])
				] as const) {
					await page.goto(path);
					await expect(page.locator('h1')).toBeVisible();
					await page.keyboard.press('h');
					const entries = await overlayEntries(page);
					expect(byId(entries), `${who} on ${path}`).toEqual(byId(expected(routeId, isAdmin)));
					// Every symbol shows its Hungarian keys.
					for (const entry of entries) {
						for (const key of entry.keys) {
							if (HU_PHYSICAL[key]) expect(entry.hu).toContain(`(${HU_PHYSICAL[key]})`);
						}
					}
					if (path === '/' && isAdmin) {
						await page
							.getByRole('dialog', { name: t(m.help_title), exact: true })
							.screenshot({ path: test.info().outputPath('help-overlay-admin.png') });
					}
					await page.keyboard.press('Escape');
					await noOpenDialog(page);
				}
			} finally {
				await context.close();
			}
		});
	}

	test('signed out, it offers only the help and Esc', async ({ browser }) => {
		desktopOnly();
		const context = await browser.newContext();
		const page = await context.newPage();
		try {
			await page.goto('/login');
			await expect(page.getByLabel(t(m.login_email), { exact: true })).toBeVisible();
			await page.keyboard.press('h');
			expect(byId(await overlayEntries(page))).toEqual(byId(expected('/login', false, false)));
			await page.keyboard.press('Escape');
			await expectNoHiddenFocusables(page);
		} finally {
			await context.close();
		}
	});
});

test.describe('signing in and out', () => {
	test('log in and log out without the mouse', async ({ browser }) => {
		desktopOnly();
		const identity = userIdentity();
		const context = await browser.newContext();
		const page = await context.newPage();
		try {
			await page.goto('/login');
			await expect(page.getByLabel(t(m.login_email), { exact: true })).toBeVisible();
			await page.keyboard.press('Tab');
			await expect(
				page.getByRole('link', { name: t(m.layout_skip_to_content), exact: true })
			).toBeFocused();
			await page.keyboard.press('Enter');
			await expect(page.locator('#main')).toBeFocused();
			const email = page.getByLabel(t(m.login_email), { exact: true });
			await tabTo(page, email);
			// Typing in the field is never a shortcut (`h` is in plenty of addresses).
			await page.keyboard.type(identity.email);
			await noOpenDialog(page);
			await page.keyboard.press('Tab');
			await expect(page.getByLabel(t(m.login_password), { exact: true })).toBeFocused();
			await page.keyboard.type(identity.password);
			await page.keyboard.press('Enter');
			await expect(
				page.getByLabel(t(m.dashboard_submit_input_label), { exact: true })
			).toBeVisible();
			await expect(page.locator('h1')).toBeFocused();

			const disconnect = page.getByRole('button', { name: t(m.dashboard_disconnect), exact: true });
			await tabTo(page, disconnect);
			await page.keyboard.press('Enter');
			await expect(
				page.getByRole('button', { name: t(m.login_connect), exact: true })
			).toBeVisible();
			await expect(page).toHaveURL('/login');
		} finally {
			await context.close();
		}
	});
});

test.describe('the shortcut switch', () => {
	test.use({ storageState: USER_STATE });

	test('off disables single keys, keeps Tab/arrows/Enter/Esc, persists, and is per user', async ({
		page,
		browser,
		baseURL
	}) => {
		desktopOnly();
		const userApi = await request.newContext({ baseURL, storageState: USER_STATE });
		const adminApi = await request.newContext({ baseURL, storageState: ADMIN_STATE });
		expect(
			(await userApi.patch('/api/settings/keyboard', { data: { keyboard_shortcuts: true } })).ok()
		).toBe(true);
		try {
			await page.goto('/account');
			const off = page.getByRole('button', { name: t(m.account_keyboard_off), exact: true });
			await tabTo(page, off);
			const saved = page.waitForResponse(sent('PATCH', '/api/settings/keyboard'));
			await page.keyboard.press('Enter');
			expect((await saved).ok()).toBe(true);
			await expect(off).toHaveAttribute('aria-pressed', 'true');
			await expect(off).toBeFocused();
			// Stored for this user only: the admin's is still on.
			expect(
				((await (await adminApi.get('/api/auth/me')).json()) as { keyboard_shortcuts: boolean })
					.keyboard_shortcuts
			).toBe(true);

			await openDashboard(page);
			const expectSingleKeysInert = async () => {
				const before = await describeFocus(page);
				for (const key of ['j', 'h', 'f', 'i', 'g', 's', '2', 'Shift+A', '/', '?']) {
					await page.keyboard.press(key);
				}
				await noOpenDialog(page);
				expect(await describeFocus(page)).toBe(before);
				await expect(page.locator('#queue-sort')).toHaveValue('created_at');
				await expect(page).toHaveURL('/');
			};
			await expectSingleKeysInert();

			// Tab, the arrows, Enter and Esc still work: show archived (a button), into the list,
			// down a row, open it, close it.
			const archived = page.getByRole('button', { name: t(m.queuectl_show_archived), exact: true });
			await tabTo(page, archived);
			await page.keyboard.press('Enter');
			await expect(archived).toHaveAttribute('aria-pressed', 'true');
			await expect.poll(async () => (await rowIds(page, 'jobs')).length).toBeGreaterThan(1);
			for (let i = 0; i < 20 && (await focusedList(page)) !== 'jobs'; i++) {
				await page.keyboard.press('Tab');
			}
			const first = await expectFocusInList(page, 'jobs');
			await page.keyboard.press('ArrowDown');
			const second = await focusedRow(page);
			expect(second).not.toBe(first);
			await page.keyboard.press('ArrowUp');
			expect(await focusedRow(page)).toBe(first);
			await page.keyboard.press('Enter');
			const toggle = page.locator(`[data-kb-row="${first}"] [data-kb-item]`).first();
			await expect(toggle).toHaveAttribute('aria-expanded', 'true');
			await page.keyboard.press('Escape');
			await expect(toggle).toHaveAttribute('aria-expanded', 'false');
			// Single keys on a row stay inert too.
			await page.keyboard.press('j');
			await page.keyboard.press('a');
			expect(await focusedRow(page)).toBe(first);

			// Persists across a reload…
			await page.reload();
			await expect(
				page.getByLabel(t(m.dashboard_submit_input_label), { exact: true })
			).toBeVisible();
			await expectSingleKeysInert();

			// …and to a second browser signed in as the same user.
			const identity = userIdentity();
			const second2 = await browser.newContext();
			try {
				const login = await second2.request.post(`${baseURL}/api/auth/login`, {
					data: { email: identity.email, password: identity.password }
				});
				expect(login.ok()).toBe(true);
				const other = await second2.newPage();
				await other.goto('/account');
				await expect(
					other.getByRole('button', { name: t(m.account_keyboard_off), exact: true })
				).toHaveAttribute('aria-pressed', 'true');
				await other.keyboard.press('h');
				await expect(other.locator('dialog[open]')).toHaveCount(0);
				// Back on from here: the first browser picks it up on its next reload.
				const on = other.getByRole('button', { name: t(m.account_keyboard_on), exact: true });
				await tabTo(other, on);
				await other.keyboard.press('Enter');
				await expect(on).toHaveAttribute('aria-pressed', 'true');
				await other.keyboard.press('h');
				await expect(
					other.getByRole('dialog', { name: t(m.help_title), exact: true })
				).toBeVisible();
			} finally {
				await second2.close();
			}
			await page.reload();
			await expect(
				page.getByLabel(t(m.dashboard_submit_input_label), { exact: true })
			).toBeVisible();
			await page.keyboard.press('h');
			await expect(page.getByRole('dialog', { name: t(m.help_title), exact: true })).toBeVisible();
		} finally {
			await userApi.patch('/api/settings/keyboard', { data: { keyboard_shortcuts: true } });
			await userApi.dispose();
			await adminApi.dispose();
		}
	});
});
