import { expect, request, test, type Browser, type Page } from '@playwright/test';
import { expectFocusInList, focusedList, focusedRow, tabStopsIn } from './support/keyboard';
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

/** How many rows `list` has loaded (a windowed list's `aria-setsize` is the whole total, so
 * not that): the jobs from the queue's count line ("350 of 1,600 jobs"), an open job's tracks
 * from its "load more" ("250 of 400 shown"), or every row once that button is gone. */
function loadedRows(page: Page, list: string): Promise<number> {
	return page.evaluate((name) => {
		const el = document.querySelector(`[data-kb-list="${CSS.escape(name)}"]`);
		if (!el) return 0;
		const number = (text: string | undefined | null) =>
			Number((text ?? '').match(/^\s*([\d,]+) of /)?.[1]?.replace(/,/g, '') ?? NaN);
		if (name === 'jobs') {
			const line = [...document.querySelectorAll('.queue *')].find(
				(node) =>
					node.children.length === 0 &&
					/^\s*[\d,]+ of [\d,]+\+? jobs\s*$/.test(node.textContent ?? '')
			);
			const shown = number(line?.textContent);
			if (!Number.isNaN(shown)) return shown;
		}
		const shown = el.closest('li')?.querySelector('[data-kb-load-more] .shown');
		if (shown) return number(shown.textContent);
		return Number(el.firstElementChild?.getAttribute('aria-setsize') ?? el.children.length);
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

	// To the end, then a jump back to the middle: the view lands there and stays (a kept row,
	// the list's current one, once pulled the page back to the top).
	await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
	await expect.poll(async () => (await windowOf(page)).max).toBe(FIXTURE_JOBS);
	await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight / 2));
	await expect.poll(async () => (await windowOf(page)).min).toBeGreaterThan(500);
	await page.waitForTimeout(1_000);
	expect((await windowOf(page)).min, 'still mid-list').toBeGreaterThan(500);
	// Deep in the list: the row's place and the list's size in the accessibility tree.
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
	// 350 of 1600 loaded: the screen reader's size is still the whole log's.
	expect(
		await page.locator('[data-kb-list="jobs"] > li').first().getAttribute('aria-setsize')
	).toBe(String(FIXTURE_JOBS));
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
	// The stream's patch did it: the job list wasn't read again (a resync would also show it).
	expect(reads.filter((url) => new URL(url).pathname === '/api/jobs')).toEqual([]);
	expect(errors).toEqual([]);
});

test('a kept row, focused again, is shown at its real place', async ({ page }) => {
	desktopOnly();
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 600);
	await page.evaluate(() => window.scrollTo(0, 0));
	// Row 5 becomes the list's current row; focus then goes to the search, and the page is
	// scrolled far down: row 5 stays rendered as a stand-in at the window's edge.
	await page.keyboard.press('j');
	for (let row = 2; row <= 5; row++) await page.keyboard.press('j');
	expect(await posinsetOfFocus(page)).toBe(5);
	const current = (await focusedRow(page))!;
	const backTo = async (how: () => Promise<void>, label: string) => {
		await page.keyboard.press('/');
		await expect(page.locator('#queue-search')).toBeFocused();
		await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight * 0.6));
		await expect.poll(async () => (await windowOf(page)).min).toBeGreaterThan(300);
		await how();
		await expect.poll(() => focusedRow(page), { message: label }).toBe(current);
		await expect.poll(() => focusInView(page), { message: `${label}: in view` }).toBe(true);
		// Its real place: rows 4 and 6 are rendered around it.
		const around = (await windowOf(page)).min;
		expect(around, `${label}: the window is at row 5`).toBeLessThanOrEqual(5);
	};
	// j from outside the list (Esc leaves the search), and Tab into the list's one stop.
	await backTo(async () => {
		await page.keyboard.press('Escape');
		await page.keyboard.press('j');
	}, 'j');
	await backTo(async () => {
		await page.keyboard.press('Tab');
		// Past the filter chips (a roving list too) to the jobs list's one stop.
		for (let n = 0; n < 40 && (await focusedList(page)) !== JOBS; n++) {
			await page.keyboard.press('Tab');
		}
	}, 'Tab');
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
		// Windowed now: from the playlist's top, a screen at a time, to its track 300.
		expect(await page.locator(`[data-kb-list="${list}"] > li`).count()).toBeLessThan(120);
		await page
			.locator(`[data-kb-row="${fixture.bigJobId}"]`)
			.evaluate((el) => el.scrollIntoView({ block: 'start' }));
		const track300 = page.locator(`[data-kb-list="${list}"] > li[aria-posinset="300"]`);
		for (let step = 0; (await track300.count()) === 0; step++) {
			expect(step, 'track 300 comes into the window').toBeLessThan(100);
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
			// The last track row in view, and its group's place.
			const rows = [
				...document.querySelectorAll<HTMLElement>('[data-kb-list="tracks"] [data-kb-row]')
			].filter((r) => {
				const box = r.getBoundingClientRect();
				return box.top > 0 && box.bottom < window.innerHeight;
			});
			const row = rows[rows.length - 1];
			if (!row) return { pos: 0, row: '' };
			return {
				pos: Number(row.closest('[data-kb-list] > li')!.getAttribute('aria-posinset')),
				row: row.dataset.kbRow!
			};
		});
		expect(deep.pos, 'a group deep in the list').toBeGreaterThan(50);
		await expandAndCheck(page, deep.row);
		expect(errors).toEqual([]);
		await done();
	});
});

test('an open job of 400 tracks in a windowed job list scrolls without jumps', async ({ page }) => {
	desktopOnly();
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 250);
	await page.evaluate(() => window.scrollTo(0, 0));
	await jobToggle(page, fixtureTitle(BIG_AT)).click();
	const list = `job-tracks:${fixture.bigJobId}`;
	await expect(page.locator(`[data-kb-list="${list}"] > li`).first()).toBeVisible();
	const more = page.locator(`[data-kb-row="${fixture.bigJobId}"] [data-kb-load-more]`);
	while ((await more.count()) > 0) {
		const before = await loadedRows(page, list);
		await more.click();
		await expect
			.poll(async () => (await more.count()) === 0 || (await loadedRows(page, list)) > before)
			.toBe(true);
	}
	// Both lists windowed: to the playlist's last tracks, then up through them a step at a time.
	await page.locator(`[data-kb-list="${list}"] > li`).last().scrollIntoViewIfNeeded();
	await page.waitForTimeout(500);
	const firstInView = () =>
		page.evaluate((name) => {
			const rows = [...document.querySelectorAll<HTMLElement>(`[data-kb-list="${name}"] > li`)];
			const row = rows.find((r) => {
				const box = r.getBoundingClientRect();
				return box.top >= 0 && box.bottom <= window.innerHeight;
			});
			return row ? { id: row.dataset.kbRow!, top: row.getBoundingClientRect().top } : null;
		}, list);
	const topOf = (id: string) =>
		page.evaluate(
			(rowId) =>
				document.querySelector(`[data-kb-row="${rowId}"]`)?.getBoundingClientRect().top ?? null,
			id
		);
	for (let step = 0; step < 25; step++) {
		const anchor = (await firstInView())!;
		expect(anchor, 'a track in view').not.toBeNull();
		await page.evaluate(() => window.scrollBy(0, -300));
		await page.waitForTimeout(150);
		const top = await topOf(anchor.id);
		expect(top, `step ${step}: the track is still rendered`).not.toBeNull();
		expect(
			Math.abs(top! - (anchor.top + 300)),
			`step ${step}: moved by the scroll only`
		).toBeLessThan(2);
	}
	expect(errors).toEqual([]);
});

test('a focused row archived off-screen in the overscan hands focus to a neighbour in view', async ({
	page
}) => {
	desktopOnly();
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 300);
	await page.evaluate(() => window.scrollTo(0, 0));
	await page.keyboard.press('j');
	for (let row = 2; row <= 120; row++) await page.keyboard.press('j');
	const focused = (await focusedRow(page))!;
	// Below the view, but still rendered (inside the window's overscan, not a kept row).
	await page.evaluate((id) => {
		const top = document.querySelector(`[data-kb-row="${id}"]`)!.getBoundingClientRect().top;
		window.scrollBy(0, top - 1200);
	}, focused);
	await page.waitForTimeout(300);
	const neighbour = await page.evaluate((id) => {
		const row = document.querySelector<HTMLElement>(`[data-kb-row="${id}"]`)!;
		return (row.nextElementSibling as HTMLElement).dataset.kbRow!;
	}, focused);
	await page.keyboard.press('a');
	await expect(page.locator(`[data-kb-row="${focused}"]`)).toHaveCount(0);
	await expect.poll(() => focusedRow(page)).toBe(neighbour);
	await page.waitForTimeout(500);
	expect(await focusInView(page), 'the neighbour is scrolled into view').toBe(true);
	expect(errors).toEqual([]);
});

test('the current row archived in the background: Tab finds its neighbour, in view', async ({
	page,
	baseURL
}) => {
	desktopOnly();
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 600);
	await page.evaluate(() => window.scrollTo(0, 0));
	await page.keyboard.press('j');
	for (let row = 2; row <= 5; row++) await page.keyboard.press('j');
	const current = (await focusedRow(page))!;
	const ids = await page.evaluate(() =>
		[...document.querySelectorAll<HTMLElement>('[data-kb-list="jobs"] > li')].map(
			(r) => r.dataset.kbRow!
		)
	);
	const next = ids[ids.indexOf(current) + 1];
	await page.keyboard.press('/');
	await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight * 0.6));
	await expect.poll(async () => (await windowOf(page)).min).toBeGreaterThan(300);
	const api = await request.newContext({
		baseURL,
		extraHTTPHeaders: { cookie: `SPOTDL_SESSION=${fixture.token}` }
	});
	expect(
		(await api.post('/api/jobs/archive', { data: { job_ids: [current] } })).status()
	).toBeLessThan(300);
	await api.dispose();
	await expect(page.locator(`[data-kb-row="${current}"]`)).toHaveCount(0);
	// Its neighbour is the list's current row now, kept rendered for the Tab stop.
	await expect(page.locator(`[data-kb-row="${next}"]`)).toHaveCount(1);
	await page.keyboard.press('Escape');
	for (let n = 0; n < 40 && (await focusedList(page)) !== JOBS; n++) {
		await page.keyboard.press('Tab');
	}
	await expect.poll(() => focusedRow(page)).toBe(next);
	await expect.poll(() => focusInView(page)).toBe(true);
	expect(errors).toEqual([]);
});

test('an open job kept off the window, focused again, shows its own button', async ({ page }) => {
	desktopOnly();
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 600);
	await page.evaluate(() => window.scrollTo(0, 0));
	// The playlist, open: its row (50 tracks) is taller than the view.
	await page.keyboard.press('j');
	for (let row = 2; row <= BIG_AT + 1; row++) await page.keyboard.press('j');
	expect(await focusedRow(page)).toBe(fixture.bigJobId);
	await page.keyboard.press('Enter');
	await expect(page.locator(`[data-kb-list="job-tracks:${fixture.bigJobId}"] > li`)).toHaveCount(
		50
	);
	const tall = await page
		.locator(`[data-kb-row="${fixture.bigJobId}"]`)
		.evaluate((el) => el.getBoundingClientRect().height);
	expect(tall).toBeGreaterThan(800);
	await page.keyboard.press('/');
	await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight * 0.6));
	await page.waitForTimeout(500);
	await page.keyboard.press('Escape');
	for (let n = 0; n < 40 && (await focusedList(page)) !== JOBS; n++) {
		await page.keyboard.press('Tab');
	}
	await expect.poll(() => focusedRow(page)).toBe(fixture.bigJobId);
	await expect
		.poll(() => focusInView(page), { message: "the job's own button in view" })
		.toBe(true);
	expect(errors).toEqual([]);
});

test('crossing the threshold keeps the view where it was', async ({ page }) => {
	desktopOnly();
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 200);
	expect(await page.locator('[data-kb-list="jobs"]').getAttribute('style')).toBeNull();
	// Row 190 at the top of the view, and the next page arriving while the user reads there,
	// focus elsewhere: a pointer-type click (detail 1) dispatched on "load more", which moves no
	// focus. (A real click focuses the button, and the browser then holds the button in place,
	// as main does; a synthetic click() counts as the keyboard's and focuses the first new row.)
	const row = page.locator('[data-kb-list="jobs"] > li').nth(189);
	const id = (await row.getAttribute('data-kb-row'))!;
	await row.evaluate((el) => el.scrollIntoView({ block: 'start' }));
	await page.waitForTimeout(300);
	const top = () =>
		page.evaluate(
			(rowId) =>
				document.querySelector(`[data-kb-row="${rowId}"]`)?.getBoundingClientRect().top ?? null,
			id
		);
	const before = (await top())!;
	await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
	await loadMoreButton(page).dispatchEvent('click', { detail: 1 });
	await expect.poll(() => loadedRows(page, JOBS)).toBe(250);
	await expect(page.locator('[data-kb-list="jobs"]')).toHaveAttribute('style', /padding-top/);
	await page.waitForTimeout(500);
	const after = await top();
	test
		.info()
		.annotations.push({ type: 'threshold', description: `row 190: ${before} -> ${after}` });
	expect(after, 'row 190 still rendered').not.toBeNull();
	expect(Math.abs(after! - before), 'row 190 stays put').toBeLessThan(2);
	expect(errors).toEqual([]);
});

test('crossing the threshold keeps the focused row, focused, and the view still', async ({
	page
}) => {
	desktopOnly();
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 200);
	await page.evaluate(() => window.scrollTo(0, 0));
	for (let row = 1; row <= 3; row++) await page.keyboard.press('j');
	const focused = (await focusedRow(page))!;
	// Far below it, focus still on row 3, the next page arrives (a pointer-type click that
	// moves no focus): the first window must keep row 3.
	await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
	await page.waitForTimeout(300);
	// The row the user reads: the last loaded one, in view at the bottom.
	const lastId = await page
		.locator('[data-kb-list="jobs"] > li')
		.last()
		.getAttribute('data-kb-row');
	const reading = page.locator(`[data-kb-row="${lastId}"]`);
	const readingTop = () => reading.evaluate((el) => el.getBoundingClientRect().top);
	const y = await readingTop();
	await loadMoreButton(page).dispatchEvent('click', { detail: 1 });
	await expect.poll(() => loadedRows(page, JOBS)).toBe(250);
	await expect(page.locator('[data-kb-list="jobs"]')).toHaveAttribute('style', /padding-top/);
	await page.waitForTimeout(500);
	expect(await focusedRow(page), 'focus stays on row 3').toBe(focused);
	expect(Math.abs((await readingTop()) - y), 'the view stays').toBeLessThan(2);
	expect(errors).toEqual([]);
});

test('the tracks scope crosses the threshold without moving the view', async ({ page }) => {
	desktopOnly();
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await page.keyboard.press('2');
	const tracks = page.locator('[data-kb-list="tracks"]');
	await expect(tracks.locator('[data-kb-row]').first()).toBeVisible();
	// Four pages (200 tracks in a handful of groups, the playlist's among them): plain.
	for (let pages = 1; pages < 4; pages++) {
		const answered = page.waitForResponse((r) => {
			const url = new URL(r.url());
			return url.pathname === '/api/tracks' && url.searchParams.has('cursor');
		});
		await loadMoreButton(page).click();
		await answered;
		await expect(loadMoreButton(page)).toHaveAttribute('aria-disabled', 'false');
	}
	expect(await tracks.getAttribute('style')).toBeNull();
	// A track deep in the playlist's group at the top of the view, then the fifth page.
	const row = tracks.locator('[data-kb-row]').nth(150);
	const id = (await row.getAttribute('data-kb-row'))!;
	await row.evaluate((el) => el.scrollIntoView({ block: 'start' }));
	await page.waitForTimeout(300);
	const top = () =>
		page.evaluate(
			(rowId) =>
				document.querySelector(`[data-kb-row="${rowId}"]`)?.getBoundingClientRect().top ?? null,
			id
		);
	const before = (await top())!;
	await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
	await loadMoreButton(page).dispatchEvent('click', { detail: 1 });
	await expect(tracks).toHaveAttribute('style', /padding-top/);
	await page.waitForTimeout(500);
	const after = await top();
	expect(after, 'the track is still rendered').not.toBeNull();
	expect(Math.abs(after! - before), 'the track stays put').toBeLessThan(2);
	expect(errors).toEqual([]);
});

test("an open job's tracks hold their place when a job above them is archived", async ({
	page,
	baseURL
}) => {
	desktopOnly();
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 300);
	await page.evaluate(() => window.scrollTo(0, 0));
	await jobToggle(page, fixtureTitle(BIG_AT)).click();
	const list = `job-tracks:${fixture.bigJobId}`;
	const more = page.locator(`[data-kb-row="${fixture.bigJobId}"] [data-kb-load-more]`);
	await expect(page.locator(`[data-kb-list="${list}"] > li`).first()).toBeVisible();
	while ((await more.count()) > 0) {
		const before = await loadedRows(page, list);
		await more.click();
		await expect
			.poll(async () => (await more.count()) === 0 || (await loadedRows(page, list)) > before)
			.toBe(true);
	}
	// Track 200 at the middle of the view; then the newest job (above the playlist) archived
	// from outside the page.
	await page
		.locator(`[data-kb-row="${fixture.bigJobId}"]`)
		.evaluate((el) => el.scrollIntoView({ block: 'start' }));
	const track200 = page.locator(`[data-kb-list="${list}"] > li[aria-posinset="200"]`);
	for (let step = 0; (await track200.count()) === 0; step++) {
		expect(step).toBeLessThan(100);
		await page.evaluate(() => window.scrollBy(0, window.innerHeight));
		await page.waitForTimeout(50);
	}
	await track200.evaluate((el) => el.scrollIntoView({ block: 'center' }));
	await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
	await page.waitForTimeout(500);
	const id = (await track200.getAttribute('data-kb-row'))!;
	const top = () =>
		page.evaluate(
			(rowId) =>
				document.querySelector(`[data-kb-row="${rowId}"]`)?.getBoundingClientRect().top ?? null,
			id
		);
	const before = (await top())!;
	const api = await request.newContext({
		baseURL,
		extraHTTPHeaders: { cookie: `SPOTDL_SESSION=${fixture.token}` }
	});
	// The newest job, from the API's own order (the list's first child is the open playlist,
	// kept outside the window).
	const listed = (await (await api.get('/api/jobs?limit=1')).json()) as { items: { id: string }[] };
	const first = listed.items[0].id;
	expect(first).not.toBe(fixture.bigJobId);
	expect(
		(await api.post('/api/jobs/archive', { data: { job_ids: [first] } })).status()
	).toBeLessThan(300);
	await api.dispose();
	await expect(page.locator(`[data-kb-row="${first}"]`)).toHaveCount(0);
	await page.waitForTimeout(500);
	const after = await top();
	test.info().annotations.push({ type: 'nested', description: `track 200: ${before} -> ${after}` });
	expect(Math.abs(after! - before), 'track 200 stays put').toBeLessThan(2);
	expect(errors).toEqual([]);
});

test('rows archived above the view leave the reading position where it was', async ({
	page,
	baseURL
}) => {
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 400);
	// Row 330 at 300px, then 40 rows far above it archived from outside the page: one live
	// removal each, every one corrected (the browser rounds each scroll to whole pixels; the
	// fraction used to add up, 10px over 40 rows on desktop).
	const api = await request.newContext({
		baseURL,
		extraHTTPHeaders: { cookie: `SPOTDL_SESSION=${fixture.token}` }
	});
	const listed = (await (await api.get('/api/jobs?limit=200')).json()) as {
		items: { id: string }[];
	};
	// Down a screen at a time until row 331 is rendered, then (in the same step, before the
	// window can move on) brought to 300px.
	const bring331 = () =>
		page.evaluate(() => {
			const el = document.querySelector<HTMLElement>(
				'[data-kb-list="jobs"] > li[aria-posinset="331"]'
			);
			if (!el) {
				window.scrollBy(0, window.innerHeight);
				return null;
			}
			window.scrollBy(0, el.getBoundingClientRect().top - 300);
			return el.dataset.kbRow!;
		});
	await page.evaluate(() => window.scrollTo(0, 0));
	let id: string | null;
	for (let step = 0; (id = await bring331()) === null; step++) {
		expect(step).toBeLessThan(300);
		await page.waitForTimeout(50);
	}
	const row = page.locator(`[data-kb-row="${id}"]`);
	await page.waitForTimeout(500);
	const top = () => row.evaluate((el) => el.getBoundingClientRect().top);
	const before = await top();
	const ids = listed.items.slice(50, 90).map((job) => job.id);
	expect((await api.post('/api/jobs/archive', { data: { job_ids: ids } })).status()).toBeLessThan(
		300
	);
	await api.dispose();
	await expect(page.locator(`[data-kb-row="${ids[ids.length - 1]}"]`)).toHaveCount(0);
	await expect
		.poll(
			async () =>
				await page.locator('[data-kb-list="jobs"] > li').first().getAttribute('aria-setsize')
		)
		.toBe(String(FIXTURE_JOBS - ids.length));
	await page.waitForTimeout(1_000);
	const after = await top();
	test
		.info()
		.annotations.push({ type: 'archive-above', description: `row 330: ${before} -> ${after}` });
	expect(Math.abs(after - before), 'the reading row stays').toBeLessThan(2);
	expect(errors).toEqual([]);
});

test('focus coming back with the browser window leaves the view where it is', async ({ page }) => {
	desktopOnly();
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 600);
	await page.evaluate(() => window.scrollTo(0, 0));
	for (let row = 1; row <= 5; row++) await page.keyboard.press('j');
	expect(await posinsetOfFocus(page)).toBe(5);
	// Read far below it with the wheel; row 5 keeps focus as a stand-in at the window's edge.
	await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight * 0.6));
	await expect.poll(async () => (await windowOf(page)).min).toBeGreaterThan(300);
	const y = await page.evaluate(() => window.scrollY);
	// The browser window loses focus and gets it back (alt-tab): Chromium fires blur on the
	// window, then focus/focusin on the element that had it. Dispatched here as it fires them.
	await page.evaluate(() => {
		window.dispatchEvent(new Event('blur'));
		const el = document.activeElement!;
		window.dispatchEvent(new Event('focus'));
		el.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
	});
	await page.waitForTimeout(500);
	expect(await page.evaluate(() => window.scrollY), 'the view stays').toBe(y);
	// A focusin that isn't the window's return (Tab, a dialog giving focus back) still shows the
	// row at its real place.
	await page.evaluate(() =>
		document.activeElement!.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))
	);
	await expect.poll(() => focusInView(page)).toBe(true);
	expect(errors).toEqual([]);
});

test('a tall open job collapsed leaves no blank stretch in the window', async ({ page }) => {
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 400);
	await page.evaluate(() => window.scrollTo(0, 0));
	const toggle = jobToggle(page, fixtureTitle(BIG_AT));
	await toggle.click();
	const list = `job-tracks:${fixture.bigJobId}`;
	const more = page.locator(`[data-kb-row="${fixture.bigJobId}"] [data-kb-load-more]`);
	await expect(page.locator(`[data-kb-list="${list}"] > li`).first()).toBeVisible();
	while ((await more.count()) > 0) {
		const before = await loadedRows(page, list);
		await more.click();
		await expect
			.poll(async () => (await more.count()) === 0 || (await loadedRows(page, list)) > before)
			.toBe(true);
	}
	// Open, the playlist's row is far taller than the view; collapsed, it's one row again.
	await page.evaluate(() => window.scrollTo(0, 0));
	await toggle.click();
	await expect(toggle).toHaveAttribute('aria-expanded', 'false');
	for (const y of [1500, 4000, 9000, 15000]) {
		await page.evaluate((to) => window.scrollTo(0, to), y);
		await page.waitForTimeout(500);
		const shown = await page.evaluate(() => {
			const probe = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2);
			return probe?.closest('[data-kb-list="jobs"] > li')?.getAttribute('aria-posinset') ?? null;
		});
		expect(shown, `a row in the middle of the view at y=${y}`).not.toBeNull();
	}
	expect(errors).toEqual([]);
});

test('a batch archiving the first rows in view leaves the next row where it was', async ({
	page,
	baseURL
}) => {
	desktopOnly();
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 400);
	await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight * 0.75));
	await page.waitForTimeout(500);
	// The first ten rows in view archived in one call (the live removals arrive a few ms apart,
	// not in the list's order); the eleventh is the one read.
	const inView = await page.evaluate(() =>
		[...document.querySelectorAll<HTMLElement>('[data-kb-list="jobs"] > li')]
			.filter((r) => {
				const box = r.getBoundingClientRect();
				return box.bottom > 0 && box.top < window.innerHeight;
			})
			.map((r) => r.dataset.kbRow!)
	);
	expect(inView.length).toBeGreaterThan(12);
	const gone = inView.slice(0, 10);
	const reading = page.locator(`[data-kb-row="${inView[10]}"]`);
	const before = await reading.evaluate((el) => el.getBoundingClientRect().top);
	const api = await request.newContext({
		baseURL,
		extraHTTPHeaders: { cookie: `SPOTDL_SESSION=${fixture.token}` }
	});
	expect((await api.post('/api/jobs/archive', { data: { job_ids: gone } })).status()).toBeLessThan(
		300
	);
	await api.dispose();
	for (const id of gone) await expect(page.locator(`[data-kb-row="${id}"]`)).toHaveCount(0);
	await page.waitForTimeout(800);
	const after = await reading.evaluate((el) => el.getBoundingClientRect().top);
	test.info().annotations.push({ type: 'batch', description: `next row: ${before} -> ${after}` });
	expect(Math.abs(after - before), 'the next row stays').toBeLessThan(2);
	expect(errors).toEqual([]);
});

test('a job opened and closed below the threshold leaves the crossing where it was', async ({
	page
}) => {
	desktopOnly();
	test.setTimeout(240_000);
	const errors = collectErrors(page);
	await openDashboard(page);
	await loadUntil(page, JOBS, 150);
	// Opened (50 tracks, ~2000px) and closed again while the list is plain: its height must be
	// the closed one when the list crosses 200.
	await page.evaluate(() => window.scrollTo(0, 0));
	const toggle = jobToggle(page, fixtureTitle(BIG_AT));
	await toggle.click();
	await expect(page.locator(`[data-kb-list="job-tracks:${fixture.bigJobId}"] > li`)).toHaveCount(
		50
	);
	await page.waitForTimeout(300);
	await toggle.click();
	await expect(toggle).toHaveAttribute('aria-expanded', 'false');
	await loadUntil(page, JOBS, 200);
	expect(await page.locator('[data-kb-list="jobs"]').getAttribute('style')).toBeNull();
	const row = page.locator('[data-kb-list="jobs"] > li').nth(189);
	const id = (await row.getAttribute('data-kb-row'))!;
	await row.evaluate((el) => el.scrollIntoView({ block: 'start' }));
	await page.waitForTimeout(300);
	const top = () =>
		page.evaluate(
			(rowId) =>
				document.querySelector(`[data-kb-row="${rowId}"]`)?.getBoundingClientRect().top ?? null,
			id
		);
	const before = (await top())!;
	await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
	await loadMoreButton(page).dispatchEvent('click', { detail: 1 });
	await expect(page.locator('[data-kb-list="jobs"]')).toHaveAttribute('style', /padding-top/);
	await page.waitForTimeout(500);
	const after = await top();
	expect(after, 'row 190 still rendered').not.toBeNull();
	expect(Math.abs(after! - before), 'row 190 stays put').toBeLessThan(2);
	expect(errors).toEqual([]);
});
