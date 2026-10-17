/**
 * v45: roving-tabindex lists (the jobs, the tracks, an open job's tracks, the filter chips).
 *
 * A list (`[data-kb-list]`) is one Tab stop: its rows (`[data-kb-row]`, each with one
 * `[data-kb-item]`, the row's own button) are reached with the arrows and j/k. A row's other
 * controls are in the Tab order only while it is the list's current row *and* open (owner's
 * decision: Enter opens a job, then Tab walks its controls and its track list), so a closed
 * list is exactly one stop and a list nested in a row is reachable only through that row.
 *
 * Focus is tracked by row **id**, never by index or element: an SSE re-order moves the DOM
 * node (which drops focus in the browser) and a reload remounts the whole list, and both put
 * focus back on the same row. A row that goes away hands focus to the next row, or the
 * previous one if it was last; never to `<body>`.
 */

/** What a row can do from the keyboard. Each key is optional: a job has no retry, a track no
 * archive, and a handler returning `false` means "not for this row now" (the key then does
 * nothing, and the browser keeps it). */
export interface RowActions {
	retry?: () => unknown;
	download?: () => unknown;
	cancel?: () => unknown;
	archive?: () => unknown;
	bump?: () => unknown;
	priorityUp?: () => unknown;
	priorityDown?: () => unknown;
	repeats?: () => unknown;
}

const rowActions = new WeakMap<Element, RowActions>();

/** Attachment for a row's `<li>`: its keyboard actions. */
export function kbRow(actions: RowActions) {
	return (node: Element) => {
		rowActions.set(node, actions);
		return () => rowActions.delete(node);
	};
}

export function actionsOf(row: Element | null): RowActions | undefined {
	return row ? rowActions.get(row) : undefined;
}

interface ListMemory {
	/** The current row's id. */
	active: string | null;
	/** Row ids in order at the last look, to find a removed row's neighbour. */
	order: string[];
	/** Focus was inside the list (and hasn't been taken elsewhere since). */
	focusWithin: boolean;
	/** The list was unmounted with focus inside: its remount takes focus back. */
	restoreUntil: number;
}

/** Outlives the list element, so a reload (which swaps the list for its skeleton) or a
 * scope switch back keeps the place. Keyed by the list's `data-kb-list` name. */
const memory = new Map<string, ListMemory>();
const RESTORE_WINDOW_MS = 10_000;

function mem(key: string): ListMemory {
	let m = memory.get(key);
	if (!m) {
		m = { active: null, order: [], focusWithin: false, restoreUntil: 0 };
		memory.set(key, m);
	}
	return m;
}

/** Forgets every list's place (a logout or identity change). */
export function resetLists(): void {
	memory.clear();
}

export function listOf(row: Element): HTMLElement | null {
	return row.parentElement?.closest<HTMLElement>('[data-kb-list]') ?? null;
}

export function rowsOf(list: Element): HTMLElement[] {
	return [...list.querySelectorAll<HTMLElement>('[data-kb-row]')].filter((r) => listOf(r) === list);
}

export function itemOf(row: Element): HTMLElement | null {
	if (row.matches('[data-kb-item]')) return row as HTMLElement;
	return (
		[...row.querySelectorAll<HTMLElement>('[data-kb-item]')].find(
			(item) => item.closest('[data-kb-row]') === row
		) ?? null
	);
}

export function rowId(row: Element): string {
	return (row as HTMLElement).dataset.kbRow ?? '';
}

/** The row (innermost) holding `el`. */
export function rowAt(el: Element | null): HTMLElement | null {
	return el?.closest<HTMLElement>('[data-kb-row]') ?? null;
}

export function isOpen(row: Element): boolean {
	return itemOf(row)?.getAttribute('aria-expanded') === 'true';
}

function isActive(row: Element): boolean {
	const list = listOf(row);
	if (!list) return false;
	return mem(list.dataset.kbList ?? '').active === rowId(row);
}

/** Whether `list` is reachable by Tab: every row it is nested in is its list's current row
 * and open. */
function gateOpen(list: Element): boolean {
	for (let row = rowAt(list); row; row = rowAt(row.parentElement)) {
		if (!isActive(row) || !isOpen(row)) return false;
	}
	return true;
}

const FOCUSABLE = 'a[href], button, input, select, textarea, [tabindex]';

/** Sets the tabindexes of `list`'s own rows and controls (nested lists do their own). */
function applyTabOrder(list: HTMLElement): void {
	const key = list.dataset.kbList ?? '';
	const m = mem(key);
	const rows = rowsOf(list);
	const ids = rows.map(rowId);
	if (m.active === null || !ids.includes(m.active)) m.active = ids[0] ?? null;
	const reachable = gateOpen(list);
	for (const row of rows) {
		const active = rowId(row) === m.active;
		const item = itemOf(row);
		if (item) item.tabIndex = reachable && active ? 0 : -1;
		// The row's other controls: only on the current, open row. Marked so a control that
		// takes tabindex -1 on its own (the queue heading) is never touched.
		const inner = reachable && active && isOpen(row);
		for (const el of row.querySelectorAll<HTMLElement>(FOCUSABLE)) {
			if (el === item || rowAt(el) !== row || el.closest('[data-kb-list]') !== list) continue;
			if (el.dataset.kbManaged === undefined && el.hasAttribute('tabindex')) continue;
			el.dataset.kbManaged = '';
			if (inner) el.removeAttribute('tabindex');
			else el.tabIndex = -1;
		}
		// Controls after the nested list (an open job's "load more tracks") belong to the row.
	}
	// Controls in the list but outside every row of it (none today) are left alone.
}

function focusRow(row: HTMLElement | undefined | null): boolean {
	const item = row ? itemOf(row) : null;
	if (!item) return false;
	item.focus();
	return true;
}

/** After a change to `list`: re-apply its tab order and, when it held focus that has now
 * fallen to `<body>`, put focus back on the same row id, or the removed row's neighbour. */
function settle(list: HTMLElement): void {
	const key = list.dataset.kbList ?? '';
	const m = mem(key);
	const before = m.active;
	const order = m.order;
	const rows = rowsOf(list);
	const ids = rows.map(rowId);
	if (before !== null && !ids.includes(before)) {
		// The current row left (cancelled, archived, filtered out): its next surviving
		// neighbour in the old order, else the previous one.
		const at = order.indexOf(before);
		const next = order.slice(at + 1).find((id) => ids.includes(id));
		const prev = order
			.slice(0, Math.max(at, 0))
			.reverse()
			.find((id) => ids.includes(id));
		m.active = next ?? prev ?? ids[0] ?? null;
	}
	m.order = ids;
	for (const nested of list.querySelectorAll<HTMLElement>('[data-kb-list]')) applyTabOrder(nested);
	applyTabOrder(list);
	if (!focusLost() || !m.focusWithin) return;
	const activeRow = rows.find((r) => rowId(r) === m.active);
	// Focus was in this row's nested list (a track of the open job): that list puts it back
	// on its own row first, and only an emptied or closed one hands it to the job.
	const nested = activeRow ? nestedList(activeRow) : null;
	if (nested && mem(nested.dataset.kbList ?? '').focusWithin && rowsOf(nested).length) {
		settle(nested);
		if (!focusLost()) return;
	}
	focusRow(activeRow);
}

function focusLost(): boolean {
	return document.activeElement === null || document.activeElement === document.body;
}

/** Attachment for a list element. `name` keys its memory: `jobs`, `tracks`,
 * `job-tracks:<id>`, `chips:<scope>`. */
export function kbList(name: string) {
	return (list: HTMLElement) => {
		list.dataset.kbList = name;
		const m = mem(name);
		m.order = rowsOf(list).map(rowId);

		const onFocusIn = (event: FocusEvent) => {
			const row = rowAt(event.target as Element);
			// The row of *this* list that holds the focus (a nested track's job, say).
			let mine: HTMLElement | null = row;
			while (mine && listOf(mine) !== list) mine = rowAt(mine.parentElement);
			if (mine) {
				m.active = rowId(mine);
				m.focusWithin = true;
				for (const l of [list, ...list.querySelectorAll<HTMLElement>('[data-kb-list]')])
					applyTabOrder(l);
			}
		};
		const onFocusOut = (event: FocusEvent) => {
			const to = event.relatedTarget as Node | null;
			// Tab or a click to something else: the list no longer holds focus. A focused row
			// removed or moved by Svelte has no `relatedTarget`, and must keep its claim.
			if (to && !list.contains(to)) m.focusWithin = false;
		};
		const onPointerDown = (event: PointerEvent) => {
			if (!list.contains(event.target as Node)) m.focusWithin = false;
		};
		list.addEventListener('focusin', onFocusIn);
		list.addEventListener('focusout', onFocusOut);
		document.addEventListener('pointerdown', onPointerDown, true);

		const observer = new MutationObserver(() => settle(list));
		observer.observe(list, {
			subtree: true,
			childList: true,
			attributes: true,
			attributeFilter: ['aria-expanded']
		});
		settle(list);
		// Remounted after a reload that unmounted it with focus inside: take it back.
		if (focusLost() && performance.now() < m.restoreUntil) {
			m.focusWithin = true;
			focusRow(rowsOf(list).find((r) => rowId(r) === m.active) ?? rowsOf(list)[0]);
		}
		m.restoreUntil = 0;

		return () => {
			observer.disconnect();
			list.removeEventListener('focusin', onFocusIn);
			list.removeEventListener('focusout', onFocusOut);
			document.removeEventListener('pointerdown', onPointerDown, true);
			m.restoreUntil = m.focusWithin ? performance.now() + RESTORE_WINDOW_MS : 0;
			// Until it's back, focus anywhere else wins.
			const cancel = () => {
				m.restoreUntil = 0;
				m.focusWithin = false;
			};
			if (m.restoreUntil) {
				document.addEventListener('focusin', cancel, { once: true, capture: true });
				setTimeout(
					() => document.removeEventListener('focusin', cancel, { capture: true }),
					RESTORE_WINDOW_MS
				);
			}
		};
	};
}

/** Moves focus within `row`'s list: by `delta` rows, or to `'first'`/`'last'`. Returns
 * whether it moved. */
export function move(row: HTMLElement, to: number | 'first' | 'last'): boolean {
	const list = listOf(row);
	if (!list) return false;
	const rows = rowsOf(list);
	const at = rows.indexOf(row);
	const target =
		to === 'first'
			? rows[0]
			: to === 'last'
				? rows[rows.length - 1]
				: rows[Math.min(Math.max(at + to, 0), rows.length - 1)];
	if (!target || target === row) return false;
	return focusRow(target);
}

/** The current row of the named list, focused. */
export function focusList(name: string): boolean {
	const list = document.querySelector<HTMLElement>(`[data-kb-list="${CSS.escape(name)}"]`);
	if (!list) return false;
	const rows = rowsOf(list);
	const m = mem(name);
	return focusRow(rows.find((r) => rowId(r) === m.active) ?? rows[0]);
}

/** The first list (of `name`'s) nested in `row`, i.e. an open job's tracks. */
export function nestedList(row: Element): HTMLElement | null {
	return (
		[...row.querySelectorAll<HTMLElement>('[data-kb-list]')].find((l) => rowAt(l) === row) ?? null
	);
}

export function focusNested(row: Element): boolean {
	const nested = nestedList(row);
	if (!nested) return false;
	const rows = rowsOf(nested);
	const m = mem(nested.dataset.kbList ?? '');
	return focusRow(rows.find((r) => rowId(r) === m.active) ?? rows[0]);
}

export function focusRowEl(row: HTMLElement | null): boolean {
	return focusRow(row);
}

/** The row holding focus right now, if focus is in a list. */
export function focusedRow(): HTMLElement | null {
	const row = rowAt(document.activeElement);
	return row && listOf(row) ? row : null;
}

function horizontal(row: Element): boolean {
	return listOf(row)?.dataset.kbOrientation === 'horizontal';
}

/** Closes the focused row (focus stays on, or returns to, its own button). */
export function collapseFocused(): boolean {
	const row = focusedRow();
	if (!row || horizontal(row) || !isOpen(row)) return false;
	const item = itemOf(row);
	item?.click();
	item?.focus();
	return true;
}

type RowAction = keyof RowActions;

/** The list keys, registered by the page that has lists (`/`). `mainList` names the list j/k
 * enter from outside any list; `loadMore` pages that list (`End` on its last row, `Shift+G`). */
export function listHandlers(opts: {
	mainList: () => string;
	loadMore: () => unknown;
}): Record<string, (event: KeyboardEvent) => boolean> {
	const action = (name: RowAction) => () => {
		const fn = actionsOf(focusedRow())?.[name];
		return fn ? fn() !== false : false;
	};
	/** "load more" for the focused row's list: an open job's own button, else the page's. */
	const loadMoreFor = (row: HTMLElement | null): boolean => {
		const list = row ? listOf(row) : null;
		const parent = list ? rowAt(list.parentElement) : null;
		if (parent) {
			const button = parent.querySelector<HTMLElement>('[data-kb-load-more]');
			if (!button) return false;
			button.click();
			return true;
		}
		opts.loadMore();
		return true;
	};
	const step = (delta: number) => (event: KeyboardEvent) => {
		const row = focusedRow();
		if (!row) {
			// j/k start the list from anywhere on the page; the arrows keep scrolling it.
			return event.key.length === 1 ? focusList(opts.mainList()) : false;
		}
		move(row, delta);
		return true;
	};
	return {
		next: step(1),
		prev: step(-1),
		first: () => {
			const row = focusedRow();
			return row ? (move(row, 'first'), true) : false;
		},
		last: () => {
			const row = focusedRow();
			if (!row) return false;
			if (!move(row, 'last') && !horizontal(row)) loadMoreFor(row);
			return true;
		},
		'load-more': () => loadMoreFor(focusedRow()),
		expand: (event) => {
			const row = focusedRow();
			if (!row) return false;
			if (horizontal(row)) return event.key === 'ArrowRight' ? (move(row, 1), true) : false;
			if (!isOpen(row)) itemOf(row)?.click();
			else focusNested(row);
			return true;
		},
		collapse: () => {
			const row = focusedRow();
			if (!row) return false;
			if (horizontal(row)) return (move(row, -1), true);
			if (isOpen(row)) return collapseFocused();
			// A track inside a job: back to the job.
			const list = listOf(row);
			const parent = list ? rowAt(list.parentElement) : null;
			return parent ? focusRow(parent) : false;
		},
		retry: action('retry'),
		download: action('download'),
		cancel: action('cancel'),
		archive: action('archive'),
		bump: action('bump'),
		'priority-up': action('priorityUp'),
		'priority-down': action('priorityDown'),
		repeats: action('repeats')
	};
}
