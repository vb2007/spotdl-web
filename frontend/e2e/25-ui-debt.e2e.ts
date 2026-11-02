import { expect, test, type Locator, type Page } from '@playwright/test';
import { ADMIN_STATE } from './support/stack';
import { m, t } from './support/i18n';

// v67: the UI debt slice's keyboard and pointer guards. U2: every setting on /settings stays a
// Tab stop and, below 1024px, the section bar stays at the top of the window. U10: the stats
// recorder is read by keyboard (a slider), its reading announced as the value. U5: a closed phone job row carries no
// actions. U11: a drag released outside the window leaves no glow stranded.

test.use({ storageState: ADMIN_STATE });

/** Presses Tab until `target` has focus, or fails after `limit` presses. */
async function tabTo(page: Page, target: Locator, limit = 80): Promise<void> {
	for (let i = 0; i < limit; i++) {
		if (await target.evaluate((el) => el === document.activeElement)) return;
		await page.keyboard.press('Tab');
	}
	await expect(target).toBeFocused();
}

test('U2: every setting on /settings is a Tab stop, and the section bar stays in reach', async ({
	page
}) => {
	await page.goto('/settings');
	await expect(page.getByRole('heading', { name: t(m.settings_heading), level: 1 })).toBeVisible();
	await page.waitForLoadState('networkidle');
	const sections = page.locator('.sections');
	await expect(sections.locator('select').first()).toBeVisible();

	// Every enabled control in the sections, marked so the walk can tell them apart.
	const controls = await sections
		.locator('input:not([type=hidden]), select, textarea, button, a[href]')
		.evaluateAll((els) =>
			els
				.filter(
					(el) =>
						!(el as HTMLButtonElement).disabled &&
						el.getAttribute('aria-hidden') !== 'true' &&
						el.getClientRects().length > 0
				)
				.map((el, i) => {
					el.setAttribute('data-v67-stop', String(i));
					return i;
				})
		);
	expect(controls.length).toBeGreaterThan(20);

	const reached = new Set<string>();
	await page.getByRole('heading', { name: t(m.settings_heading), level: 1 }).focus();
	for (let i = 0; i < controls.length * 3 && reached.size < controls.length; i++) {
		await page.keyboard.press('Tab');
		const stop = await page.evaluate(
			() => document.activeElement?.getAttribute('data-v67-stop') ?? null
		);
		if (stop !== null) reached.add(stop);
	}
	expect(controls.filter((i) => !reached.has(String(i)))).toEqual([]);

	// Below 1024px the index is a bar along the top: scrolled to the end it is still there, and a
	// link in it takes the page to its section, below the bar.
	const viewport = page.viewportSize();
	if (viewport && viewport.width < 1024) {
		const bar = page.getByRole('navigation', { name: t(m.settings_index_label) });
		await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
		await expect.poll(async () => (await bar.boundingBox())?.y).toBeLessThan(1);
		await bar.getByRole('link', { name: t(m.settings_section_alerts), exact: true }).click();
		const barBox = await bar.boundingBox();
		await expect
			.poll(async () => (await page.locator('#alerts').boundingBox())?.y ?? -1)
			.toBeGreaterThanOrEqual((barBox?.y ?? 0) + (barBox?.height ?? 0) - 1);
	}
});

test('U10: the failure recorder is read by keyboard, its reading announced', async ({ page }) => {
	await page.goto('/stats');
	// A slider over the buckets (role description "chart"), named by its summary.
	const recorder = page.getByRole('slider', { name: /^(Failures by type|No failures)/ });
	await expect(recorder).toBeVisible();
	await expect(recorder).toHaveAttribute('aria-roledescription', t(m.stats_chart_role));
	await tabTo(page, recorder);
	await expect(recorder).toHaveAccessibleDescription(/arrows/);

	// Nothing read yet: the value text says so.
	await expect(recorder).toHaveAttribute('aria-valuetext', t(m.stats_chart_unread_hour));
	await page.keyboard.press('End');
	await expect(recorder.locator('.readout')).toBeVisible();
	// The newest bucket's reading, announced as the value: its time, then every channel, the
	// breaker's last.
	const max = Number(await recorder.getAttribute('aria-valuemax'));
	await expect(recorder).toHaveAttribute('aria-valuenow', String(max));
	await expect(recorder).toHaveAttribute('aria-valuetext', /^.+: .*breaker (held|clear)$/);
	const newest = await recorder.getAttribute('aria-valuetext');
	await page.keyboard.press('ArrowLeft');
	await expect(recorder).toHaveAttribute('aria-valuenow', String(max - 1));
	await expect(recorder).not.toHaveAttribute('aria-valuetext', newest ?? '');
	await page.keyboard.press('Home');
	await expect(recorder).toHaveAttribute('aria-valuenow', '0');

	// Esc clears the crosshair (and stays the chart's while one is shown).
	await page.keyboard.press('Escape');
	await expect(recorder.locator('.readout')).toHaveCount(0);
	await expect(recorder).toHaveAttribute('aria-valuetext', t(m.stats_chart_unread_hour));
	await expect(recorder).toBeFocused();

	// The help overlay lists the chart's keys on /stats.
	await page.keyboard.press('h');
	const help = page.getByRole('dialog', { name: t(m.help_title), exact: true });
	await expect(help.getByText(t(m.kbd_chart_step), { exact: true })).toBeVisible();
	await expect(help.getByText(t(m.kbd_chart_ends), { exact: true })).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(help).toBeHidden();
});

test('U5: a closed phone job row carries no actions; opening it shows them', async ({
	page,
	isMobile
}) => {
	test.skip(!isMobile, 'a phone-band rule');
	await page.goto('/');
	const rows = page.locator('li.job');
	await expect(rows.first()).toBeVisible();
	await expect(page.locator('li.job .row:not(.open) .action:visible')).toHaveCount(0);
	const first = rows.first();
	await first.locator('.toggle').click();
	await expect(first.locator('.row.open')).toBeVisible();
	// An open row shows whatever actions it has (a settled job at least its archive).
	await expect(first.locator('.row.open .action:visible').first()).toBeVisible();
	await first.locator('.toggle').click();
});

test('U11: a drag released outside the window leaves no glow stranded', async ({
	page,
	isMobile
}) => {
	test.skip(isMobile, 'the glow follows a hovering fine pointer only');
	await page.goto('/');
	const glow = page.locator('.ambient-field .glow');
	await expect(glow).toHaveClass(/following/);
	const offset = () =>
		glow.evaluate((el) => {
			const matrix = new DOMMatrix(getComputedStyle(el).transform);
			return Math.round(Math.hypot(matrix.m41, matrix.m42));
		});
	for (let i = 0; i <= 10; i++) await page.mouse.move(700 + i * 40, 420 + i * 20);
	await expect.poll(offset).toBeGreaterThan(100);

	// A native drag leaving the window and dropped outside it: the browser cancels the pointer,
	// sends a pointerout with no related target, no more moves, then dragend at the drop point.
	await page.evaluate(() => {
		window.dispatchEvent(new PointerEvent('pointercancel', { pointerType: 'mouse' }));
		document.body.dispatchEvent(
			new PointerEvent('pointerout', { pointerType: 'mouse', bubbles: true, relatedTarget: null })
		);
		document.body.dispatchEvent(
			new DragEvent('dragend', { bubbles: true, clientX: -40, clientY: 300 })
		);
	});
	await expect.poll(offset, { timeout: 10_000 }).toBeLessThan(2);
});
