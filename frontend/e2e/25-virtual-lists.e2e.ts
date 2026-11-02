import { expect, request, test, type Browser, type Page } from '@playwright/test';
import { expectFocusInList, focusedRow, tabStopsIn } from './support/keyboard';
import { m, t } from './support/i18n';
import { jobToggle, openDashboard } from './support/ui';
import {
	BIG_AT,
	BIG_TRACKS,
	FIXTURE_JOBS,
	LIVE_AT,
	fixtureTitle,
	parkVirtualFixture,
	seedVirtualFixture,
	signInFixture,
	type VirtualFixture
} from './support/virtual';

// Spec 25 (v68, U4): the virtualized lists. Above 200 rows a list renders only a window of
// them (`$lib/listWindow.svelte.ts`); everything built on the rows (v45's roving focus by id,
// load-more, focus restoration, v34's live patching, v41's open track detail, the screen
// reader's position) must work across the window's edge. The fixture is its own account with a
// 1600-job log (`support/virtual.ts`), so every other spec keeps its plain, short lists.

let fixture: VirtualFixture;

// Each test starts from the whole log (a previous one archived a row, cancelled the live job).
test.beforeEach(async ({ context, baseURL }) => {
	fixture = seedVirtualFixture();
	await signInFixture(context, baseURL!, fixture.token);
});
test.afterAll(() => parkVirtualFixture());

function desktopOnly(): void {
	test.skip(
		test.info().project.name === 'mobile',
		'keyboard journeys run on the desktop project (the mobile one emulates a touch phone)'
	);
}

const JOBS = 'jobs';

/** The page's own "load more" (not an open job's). */
const loadMoreButton = (page: Page) => page.locator('button.load-more:not([data-kb-load-more])');

/** How many rows `list` has loaded: a windowed list's `aria-setsize`, else its rows. */
function loadedRows(page: Page, list: string): Promise<number> {
	return page.evaluate((name) => {
		const el = document.querySelector(`[data-kb-list="${CSS.escape(name)}"]`);
		if (!el) return 0;
		const size = el.firstElementChild?.getAttribute('aria-setsize');
		return size ? Number(size) : el.children.length;
	}, list);
}

/** Loads pages with the pointer (the list's own button) until `list` has `rows` rows, or
 * (`Infinity`) every page. */
async function loadUntil(page: Page, list: string, rows: number): Promise<void> {
	for (let pages = 0; (await loadedRows(page, list)) < rows; pages++) {
		expect(pages, `${rows} rows loaded`).toBeLessThan(60);
		const button = loadMoreButton(page);
		if (rows === Infinity && (await button.count()) === 0) {
			// An empty last page hands focus to the queue's heading (scrolling to it) once it's
			// in: let that land before the test scrolls.
			await expect(page.locator('#queue-heading')).toBeFocused();
			return;
		}
		const before = await loadedRows(page, list);
		await button.click();
		// The last page can be empty (the cursor doesn't know it's the end): the button goes.
		await expect
			.poll(async () => (await loadedRows(page, list)) > before || (await button.count()) === 0)
			.toBe(true);
	}
}

/** The jobs list's rendered rows: how many, and the positions of those in the viewport
 * (`min`/`max`). A rendered row outside the window (the current one, kept) isn't in view. */
function windowOf(page: Page) {
	return page.evaluate(() => {
		const rows = [...document.querySelectorAll('[data-kb-list="jobs"] > li')];
		const pos = rows
			.filter((r) => {
				const box = r.getBoundingClientRect();
				return box.bottom > 0 && box.top < window.innerHeight;
			})
			.map((r) => Number(r.getAttribute('aria-posinset')));
		return { count: rows.length, min: Math.min(...pos), max: Math.max(...pos) };
	});
}

/** Whether the focused element is inside the viewport. */
function focusInView(page: Page) {
	return page.evaluate(() => {
		const el = document.activeElement;
		if (!el || el === document.body) return false;
		const box = el.getBoundingClientRect();
		return box.height > 0 && box.top >= 0 && box.bottom <= window.innerHeight;
	});
}

function posinsetOfFocus(page: Page): Promise<number> {
	return page.evaluate(() =>
		Number(
			document.activeElement?.closest('[data-kb-list] > li')?.getAttribute('aria-posinset') ?? 0
		)
	);
}

/** Every console error and uncaught exception of the page, from here on. */
function collectErrors(page: Page): string[] {
	const errors: string[] = [];
	page.on('console', (msg) => {
		if (msg.type() === 'error') errors.push(msg.text());
	});
	page.on('pageerror', (err) => errors.push(String(err)));
	return errors;
}

test('the list renders a window above the threshold; the screen reader gets the full count', async ({
	page
}) => {
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	// One page (50 rows): below the threshold, every row and no window markup.
	await expect(page.locator('[data-kb-list="jobs"] > li')).toHaveCount(50);
	expect(await page.locator('[data-kb-list="jobs"]').getAttribute('style')).toBeNull();
	expect(await page.locator('[data-kb-list="jobs"] > li[aria-setsize]').count()).toBe(0);
	const before = await page.evaluate(() => document.querySelectorAll('*').length);

	await loadUntil(page, JOBS, Infinity);
	const after = await page.evaluate(() => document.querySelectorAll('*').length);
	const win = await windowOf(page);
	test.info().annotations.push({
		type: 'dom',
		description: `${before} elements with 50 rows, ${after} with all ${FIXTURE_JOBS} loaded (${win.count} rendered)`
	});
	// A window of rows, never all 1600; the page grows by a few hundred nodes, not ~28k.
	expect(win.count).toBeLessThan(80);
	expect(after).toBeLessThan(before * 2);

	// Deep in the list: the row's place and the list's size in the accessibility tree.
	await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight / 2));
	await expect.poll(async () => (await windowOf(page)).min).toBeGreaterThan(500);
	const readDeep = () =>
		page.evaluate(() => {
			const rows = [...document.querySelectorAll<HTMLElement>('[data-kb-list="jobs"] > li')];
			const middle = window.innerHeight / 2;
			const box = (r: HTMLElement) => r.getBoundingClientRect();
			const mid = rows
				.filter((r) => box(r).bottom > 0 && box(r).top < window.innerHeight)
				.sort((a, b) => Math.abs(box(a).top - middle) - Math.abs(box(b).top - middle))[0];
			if (!mid) return null;
			return {
				id: mid.dataset.kbRow!,
				pos: Number(mid.getAttribute('aria-posinset')),
				size: Number(mid.getAttribute('aria-setsize'))
			};
		});
	await expect.poll(readDeep, { message: 'a row in view mid-list' }).not.toBeNull();
	const deep = (await readDeep())!;
	expect(deep.size).toBe(FIXTURE_JOBS);
	expect(deep.pos).toBeGreaterThan(500);
	// The row is a list item of the named list in the browser's accessibility tree, carrying
	// those attributes. (CDP's AX properties don't include the computed position; Chromium's
	// own tree shows it as "posinset=… setsize=…", recorded in the PR.)
	const cdp = await page.context().newCDPSession(page);
	const { root } = await cdp.send('DOM.getDocument', { depth: 0 });
	const { nodeId } = await cdp.send('DOM.querySelector', {
		nodeId: root.nodeId,
		selector: `[data-kb-row="${deep.id}"]`
	});
	const { nodes } = await cdp.send('Accessibility.getPartialAXTree', {
		nodeId,
		fetchRelatives: true
	});
	const row = nodes.find((n) => n.role?.value === 'listitem' && !n.ignored)!;
	expect(row, 'the row is a list item').toBeDefined();
	const parent = nodes.find((n) => n.nodeId === row.parentId);
	expect(parent?.role?.value).toBe('list');
	expect(parent?.name?.value).toBe(t(m.dashboard_list_jobs));
	test.info().annotations.push({
		type: 'a11y',
		description: `row ${deep.id}: ${row.role?.value} "${row.name?.value}" in list "${parent?.name?.value}", aria-posinset ${deep.pos}, aria-setsize ${deep.size}`
	});
	expect(errors).toEqual([]);
});

test('j/k cross the window with focus in view; End loads more onto its first row; one Tab stop', async ({
	page
}) => {
	desktopOnly();
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 350);
	await page.evaluate(() => window.scrollTo(0, 0));
	await page.keyboard.press('j');
	await expectFocusInList(page, JOBS);
	expect(await posinsetOfFocus(page)).toBe(1);
	// Row 1 to row 300, one row a press: the window moves along, focus never leaves the view.
	for (let row = 2; row <= 300; row++) {
		await page.keyboard.press('j');
		expect(await posinsetOfFocus(page), `j to row ${row}`).toBe(row);
		expect(await focusInView(page), `row ${row} in view`).toBe(true);
	}
	const win = await windowOf(page);
	expect(win.min, 'the window left row 1 behind').toBeGreaterThan(1);
	expect(win.count).toBeLessThan(80);
	// And back up past the window's top edge.
	for (let row = 299; row >= 240; row--) {
		await page.keyboard.press('k');
		expect(await posinsetOfFocus(page), `k to row ${row}`).toBe(row);
		expect(await focusInView(page)).toBe(true);
	}
	// Still one Tab stop: the roving list's single tabindex=0.
	expect(await tabStopsIn(page, JOBS)).toBe(1);

	// End: the last loaded row (350), then End again loads the next page and focuses its
	// first row (351), rendered and in view.
	await page.keyboard.press('End');
	await expect.poll(() => posinsetOfFocus(page)).toBe(350);
	expect(await focusInView(page)).toBe(true);
	await page.keyboard.press('End');
	await expect.poll(() => loadedRows(page, JOBS)).toBe(400);
	await expect
		.poll(() => posinsetOfFocus(page), { message: 'focus on the first new row' })
		.toBe(351);
	expect(await focusInView(page)).toBe(true);
	// Home goes back to row 1, far outside the window.
	await page.keyboard.press('Home');
	await expect.poll(() => posinsetOfFocus(page)).toBe(1);
	expect(await focusInView(page)).toBe(true);
	expect(await tabStopsIn(page, JOBS)).toBe(1);
	expect(errors).toEqual([]);
});

test('archiving the focused row at the window edge hands focus to its neighbour', async ({
	page,
	baseURL
}) => {
	desktopOnly();
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 300);
	// Focus row 250, then scroll the page away from it (the wheel, not the keys): the focused
	// row stays rendered outside the window's edge, its neighbours don't.
	await page.evaluate(() => window.scrollTo(0, 0));
	await page.keyboard.press('j');
	for (let row = 2; row <= 250; row++) await page.keyboard.press('j');
	expect(await posinsetOfFocus(page)).toBe(250);
	const focused = (await focusedRow(page))!;
	await page.evaluate(() => window.scrollTo(0, 0));
	await expect.poll(async () => (await windowOf(page)).min).toBe(1);
	const neighbour = await page.evaluate((id) => {
		const list = document.querySelector('[data-kb-list="jobs"]')!;
		const row = list.querySelector<HTMLElement>(`[data-kb-row="${id}"]`)!;
		const rendered = [...list.children].map((r) => Number(r.getAttribute('aria-posinset')));
		return { rendered, still: row.getAttribute('aria-posinset') };
	}, focused);
	expect(neighbour.still, 'the focused row is still rendered').toBe('250');
	expect(neighbour.rendered, 'its neighbour (251) is not').not.toContain(251);
	const api = await request.newContext({
		baseURL,
		extraHTTPHeaders: { cookie: `SPOTDL_SESSION=${fixture.token}` }
	});
	// Row 251's id, from the API's own order.
	const listed = await (await api.get('/api/jobs?limit=300')).json();
	const next: string = listed.items[250].id;
	expect(listed.items[249].id).toBe(focused);

	await page.keyboard.press('a');
	await expect(page.locator(`[data-kb-row="${focused}"]`)).toHaveCount(0);
	await expect.poll(() => focusedRow(page), { message: 'focus after archive' }).toBe(next);
	expect(await focusInView(page)).toBe(true);
	expect(
		((await (await api.get(`/api/jobs/${focused}`)).json()) as { archived_at: string | null })
			.archived_at
	).not.toBeNull();
	await api.dispose();
	expect(errors).toEqual([]);
});

test('a live update to a job off the window shows once it is scrolled into view', async ({
	page,
	baseURL
}) => {
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, Infinity);
	await page.evaluate(() => window.scrollTo(0, 0));
	await expect.poll(async () => (await windowOf(page)).min).toBe(1);
	const live = page.locator(`[data-kb-row="${fixture.liveJobId}"]`);
	await expect(live).toHaveCount(0);

	// The job is cancelled from outside the page; the stream's events patch a row that isn't
	// rendered.
	const api = await request.newContext({
		baseURL,
		extraHTTPHeaders: { cookie: `SPOTDL_SESSION=${fixture.token}` }
	});
	const reads: string[] = [];
	page.on('request', (r) => {
		const path = new URL(r.url()).pathname;
		if (r.method() === 'GET' && path.startsWith('/api/jobs')) reads.push(r.url());
	});
	expect((await api.delete(`/api/jobs/${fixture.liveJobId}`)).status()).toBe(200);
	await api.dispose();
	// Let the stream deliver it (the counts move as soon as it has).
	await page.waitForTimeout(3_000);

	// Scrolled to, a screen at a time.
	for (let step = 0; (await live.count()) === 0; step++) {
		expect(step, 'the live job comes into the window').toBeLessThan(600);
		await page.evaluate(() => window.scrollBy(0, window.innerHeight));
		await page.waitForTimeout(50);
	}
	await live.scrollIntoViewIfNeeded();
	await expect(live).toBeInViewport();
	await expect(live).toHaveAttribute('aria-posinset', String(LIVE_AT + 1));
	await expect(live.locator('.badge')).toHaveText(t(m.status_cancelled));
	test.info().annotations.push({
		type: 'reads',
		description: `job list reads after the cancel: ${reads.length ? reads.join(', ') : 'none'}`
	});
	expect(errors).toEqual([]);
});

test.describe('open rows deep in a windowed list', () => {
	/** A page of its own context, recorded (the bullet's evidence is a recording). */
	async function recordedPage(browser: Browser, baseURL: string) {
		const info = test.info();
		const context = await browser.newContext({
			viewport: info.project.use.viewport,
			deviceScaleFactor: info.project.use.deviceScaleFactor,
			isMobile: info.project.use.isMobile,
			hasTouch: info.project.use.hasTouch,
			locale: info.project.use.locale,
			baseURL,
			recordVideo: { dir: info.outputPath('video') }
		});
		await signInFixture(context, baseURL, fixture.token);
		const page = await context.newPage();
		return {
			page,
			done: async () => {
				const video = page.video();
				await context.close();
				if (video)
					await info.attach('recording', { path: await video.path(), contentType: 'video/webm' });
			}
		};
	}

	/** The top of the row and of the first row in view, and whether the open detail is whole. */
	function measure(page: Page, rowId: string) {
		return page.evaluate((id) => {
			const row = document.querySelector<HTMLElement>(`[data-kb-row="${id}"]`)!;
			const detail = row.querySelector<HTMLElement>('.detail');
			const next = row.nextElementSibling;
			const detailBox = detail?.getBoundingClientRect();
			return {
				top: row.getBoundingClientRect().top,
				scrollY: window.scrollY,
				detail: detailBox ? detailBox.height : 0,
				// The detail is inside its row and the next row starts below it (no overlap from a
				// stale height).
				whole:
					!!detailBox &&
					detailBox.bottom <= row.getBoundingClientRect().bottom + 0.5 &&
					(!next || next.getBoundingClientRect().top >= detailBox.bottom - 0.5)
			};
		}, rowId);
	}

	async function expandAndCheck(page: Page, rowId: string): Promise<void> {
		const row = page.locator(`[data-kb-row="${rowId}"]`);
		await row.evaluate((el) => el.scrollIntoView({ block: 'center' }));
		await page.waitForTimeout(500);
		const before = await measure(page, rowId);
		await row.locator('[data-kb-item]').click();
		await expect(row.locator('[data-kb-item]')).toHaveAttribute('aria-expanded', 'true');
		await expect(row.locator('.detail')).toBeVisible();
		await page.waitForTimeout(1_000);
		const after = await measure(page, rowId);
		test.info().annotations.push({
			type: 'expand',
			description: `row ${rowId}: top ${before.top.toFixed(1)} -> ${after.top.toFixed(1)}, detail ${after.detail.toFixed(0)}px`
		});
		expect(Math.abs(after.top - before.top), 'the row stays where it was').toBeLessThan(1);
		expect(after.detail).toBeGreaterThan(20);
		expect(after.whole, 'the detail renders whole').toBe(true);
		// Scroll away and back: the open row (its own state) is kept, still open.
		await page.evaluate(() => window.scrollBy(0, -8 * window.innerHeight));
		await page.waitForTimeout(300);
		await row.evaluate((el) => el.scrollIntoView({ block: 'center' }));
		await expect(row.locator('[data-kb-item]')).toHaveAttribute('aria-expanded', 'true');
	}

	test("an open job's tracks", async ({ browser, baseURL }) => {
		test.setTimeout(240_000);
		const { page, done } = await recordedPage(browser, baseURL!);
		const errors = collectErrors(page);
		await openDashboard(page);
		await jobToggle(page, fixtureTitle(BIG_AT)).click();
		const list = `job-tracks:${fixture.bigJobId}`;
		await expect(page.locator(`[data-kb-list="${list}"] > li`).first()).toBeVisible();
		const more = page.locator(`[data-kb-row="${fixture.bigJobId}"] [data-kb-load-more]`);
		while ((await loadedRows(page, list)) < BIG_TRACKS) {
			const before = await loadedRows(page, list);
			await more.click();
			await expect.poll(() => loadedRows(page, list)).toBeGreaterThan(before);
		}
		// Windowed now: a track around 300, scrolled to.
		expect(await page.locator(`[data-kb-list="${list}"] > li`).count()).toBeLessThan(120);
		for (let step = 0; ; step++) {
			expect(step).toBeLessThan(200);
			const max = await page.evaluate(
				(name) =>
					Math.max(
						...[...document.querySelectorAll(`[data-kb-list="${CSS.escape(name)}"] > li`)].map(
							(r) => Number(r.getAttribute('aria-posinset'))
						)
					),
				list
			);
			if (max >= 300) break;
			await page.evaluate(() => window.scrollBy(0, window.innerHeight));
			await page.waitForTimeout(50);
		}
		const deep = await page
			.locator(`[data-kb-list="${list}"] > li[aria-posinset="300"]`)
			.getAttribute('data-kb-row');
		await expandAndCheck(page, deep!);
		expect(errors).toEqual([]);
		await done();
	});

	test('the tracks scope', async ({ browser, baseURL }) => {
		test.setTimeout(240_000);
		const { page, done } = await recordedPage(browser, baseURL!);
		const errors = collectErrors(page);
		await openDashboard(page);
		await page.keyboard.press('2');
		const tracks = page.locator('[data-kb-list="tracks"]');
		await expect(tracks.locator('[data-kb-row]').first()).toBeVisible();
		// The tracks scope's threshold counts tracks; its window holds job groups. Fourteen
		// pages (700 tracks): past the playlist's 400, into single-track groups again.
		for (let pages = 1; pages < 14; pages++) {
			const answered = page.waitForResponse((r) => {
				const url = new URL(r.url());
				return url.pathname === '/api/tracks' && url.searchParams.has('cursor');
			});
			await loadMoreButton(page).click();
			await answered;
			await expect(loadMoreButton(page)).toHaveAttribute('aria-disabled', 'false');
		}
		expect(await tracks.locator('> li').first().getAttribute('aria-setsize')).not.toBeNull();
		// Near the end of what's loaded: single-track groups again, far past the playlist's.
		await page.evaluate(() =>
			window.scrollTo(0, document.documentElement.scrollHeight - 2 * window.innerHeight)
		);
		await page.waitForTimeout(500);
		const deep = await page.evaluate(() => {
			const groups = [...document.querySelectorAll<HTMLElement>('[data-kb-list="tracks"] > li')];
			const box = (g: HTMLElement) => g.getBoundingClientRect();
			const mid = groups
				.filter((g) => box(g).top > 0 && box(g).bottom < window.innerHeight)
				.sort(
					(a, b) =>
						Number(b.getAttribute('aria-posinset')) - Number(a.getAttribute('aria-posinset'))
				)[0];
			return {
				pos: Number(mid.getAttribute('aria-posinset')),
				row: mid.querySelector<HTMLElement>('[data-kb-row]')!.dataset.kbRow!
			};
		});
		expect(deep.pos, 'a group deep in the list').toBeGreaterThan(50);
		await expandAndCheck(page, deep.row);
		expect(errors).toEqual([]);
		await done();
	});
});
