import { expect, type Locator, type Page } from '@playwright/test';

// v45: helpers for the keyboard-only specs. Everything here acts through `page.keyboard` or
// trusted CDP key events, never a click.

/** Presses Tab (or Shift+Tab) until `target` has focus, failing after `max` presses. Returns
 * how many presses it took. */
export async function tabTo(
	page: Page,
	target: Locator,
	{ max = 80, back = false }: { max?: number; back?: boolean } = {}
): Promise<number> {
	for (let presses = 0; presses <= max; presses++) {
		if (await isFocused(target)) return presses;
		await page.keyboard.press(back ? 'Shift+Tab' : 'Tab');
	}
	throw new Error(`Tab didn't reach ${target} in ${max} presses (at ${await describeFocus(page)})`);
}

export async function isFocused(target: Locator): Promise<boolean> {
	if ((await target.count()) !== 1) return false;
	return target.evaluate((el) => el === document.activeElement);
}

/** The keyboard row (`data-kb-row`) holding focus, or null. */
export function focusedRow(page: Page): Promise<string | null> {
	return page.evaluate(
		() => document.activeElement?.closest<HTMLElement>('[data-kb-row]')?.dataset.kbRow ?? null
	);
}

/** The keyboard list (`data-kb-list`) holding focus, or null. */
export function focusedList(page: Page): Promise<string | null> {
	return page.evaluate(
		() => document.activeElement?.closest<HTMLElement>('[data-kb-list]')?.dataset.kbList ?? null
	);
}

/** A readable name for whatever has focus, for failure messages and assertions. */
export function describeFocus(page: Page): Promise<string> {
	return page.evaluate(() => {
		const el = document.activeElement;
		if (!el || el === document.body) return 'body';
		const name = el.getAttribute('aria-label') ?? el.textContent?.trim().slice(0, 40) ?? '';
		return `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''} "${name}"`;
	});
}

/** Waits until focus sits on a row of `list` (and not on <body>). */
export async function expectFocusInList(page: Page, list: string): Promise<string> {
	await expect.poll(() => focusedList(page), { message: `focus in list ${list}` }).toBe(list);
	return (await focusedRow(page))!;
}

/** The ids of `list`'s rows in order, as the page has them. */
export function rowIds(page: Page, list: string): Promise<string[]> {
	return page.evaluate((name) => {
		const el = document.querySelector(`[data-kb-list="${CSS.escape(name)}"]`);
		if (!el) return [];
		return [...el.querySelectorAll<HTMLElement>('[data-kb-row]')]
			.filter((r) => r.parentElement?.closest('[data-kb-list]') === el)
			.map((r) => r.dataset.kbRow ?? '');
	}, list);
}

/** How many elements of `list` are in the Tab order right now (tabIndex >= 0 and shown). */
export function tabStopsIn(page: Page, list: string): Promise<number> {
	return page.evaluate((name) => {
		const el = document.querySelector(`[data-kb-list="${CSS.escape(name)}"]`);
		if (!el) return -1;
		return [
			...el.querySelectorAll<HTMLElement>('a[href], button, input, select, textarea, [tabindex]')
		].filter((e) => e.tabIndex >= 0 && e.getClientRects().length > 0).length;
	}, list);
}

/** One physical key on a **Hungarian QWERTZ** keyboard, as Chromium reports it: the produced
 * character (`key`), the physical key (`code`) and the modifiers. Playwright's own keyboard
 * always maps through a US layout and can't switch OS layouts, so these go straight to
 * `Input.dispatchKeyEvent` (trusted events). */
export interface HuKey {
	key: string;
	code: string;
	shift?: boolean;
	/** AltGr on Windows: reported as Ctrl+Alt. */
	altGr?: boolean;
	/** The text the key types (absent for a key that types nothing). */
	text?: string;
}

export const HU = {
	/** `?` is Shift + the comma key. */
	question: { key: '?', code: 'Comma', shift: true, text: '?' },
	/** `/` is Shift + 6. */
	slash: { key: '/', code: 'Digit6', shift: true, text: '/' },
	/** `+` is Shift + 3. */
	plus: { key: '+', code: 'Digit3', shift: true, text: '+' },
	/** `-` is unshifted, right of `.`. */
	minus: { key: '-', code: 'Slash', text: '-' },
	/** Y and Z are swapped against US: the key labelled Z sits where US has Y. */
	z: { key: 'z', code: 'KeyY', text: 'z' },
	y: { key: 'y', code: 'KeyZ', text: 'y' },
	/** AltGr+V types `@`; AltGr+B types `{`; AltGr+Q types `\`. */
	at: { key: '@', code: 'KeyV', altGr: true, text: '@' },
	brace: { key: '{', code: 'KeyB', altGr: true, text: '{' },
	backslash: { key: '\\', code: 'KeyQ', altGr: true, text: '\\' },
	/** The accented letters are unshifted keys of their own. */
	oDoubleAcute: { key: 'ő', code: 'BracketLeft', text: 'ő' },
	uDoubleAcute: { key: 'ű', code: 'Backslash', text: 'ű' },
	/** A dead key (used by some Hungarian layouts for accents): it must never fire anything. */
	dead: { key: 'Dead', code: 'Equal' }
} satisfies Record<string, HuKey>;

export async function huPress(page: Page, k: HuKey): Promise<void> {
	const cdp = await page.context().newCDPSession(page);
	try {
		// Alt = 1, Ctrl = 2, Meta = 4, Shift = 8.
		const modifiers = (k.altGr ? 3 : 0) | (k.shift ? 8 : 0);
		await cdp.send('Input.dispatchKeyEvent', {
			type: k.text ? 'keyDown' : 'rawKeyDown',
			key: k.key,
			code: k.code,
			modifiers,
			text: k.text,
			unmodifiedText: k.text
		});
		await cdp.send('Input.dispatchKeyEvent', {
			type: 'keyUp',
			key: k.key,
			code: k.code,
			modifiers
		});
	} finally {
		await cdp.detach();
	}
}
