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
	// In place: a list still mounted (the chips, through a reset on an identity change) keeps
	// its own reference to its entry, and must see the reset rather than a stale copy.
	for (const m of memory.values()) {
		m.active = null;
		m.order = [];
		m.focusWithin = false;
		m.restoreUntil = 0;
	}
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
	// Only `settle` moves the remembered row (it knows a removed row's neighbour); until it
	// has, the first row stands in for one that isn't there.
	const current = m.active !== null && ids.includes(m.active) ? m.active : (ids[0] ?? null);
	const reachable = gateOpen(list);
	for (const row of rows) {
		const active = rowId(row) === current;
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

function focusRow(row: HTMLElement | undefined | null, opts?: FocusOptions): boolean {
	const item = row ? itemOf(row) : null;
	if (!item) return false;
	item.focus(opts);
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
	// No rows (yet, or for now): nothing to place, and nothing learned about the order.
	if (ids.length === 0) return;
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
	if (m.active === null) m.active = ids[0];
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
	// The same row back after a re-order stays where the user is reading; a neighbour after a
	// removal is scrolled to.
	focusRow(activeRow, { preventScroll: before === m.active });
}

function focusLost(): boolean {
	return document.activeElement === null || document.activeElement === document.body;
}

/** Attachment for a list element. `name` keys its memory: `jobs`, `tracks`,
 * `job-tracks:<id>`, `chips`. `fallback` is where focus goes when the list goes away with
 * focus inside and doesn't come back (its last row removed, so an empty state replaced it);
 * it returns null while a reload is still under way, since the list then remounts and takes
 * focus back itself. */
export function kbList(name: string, opts: { fallback?: () => HTMLElement | null } = {}) {
	return (list: HTMLElement) => {
		list.dataset.kbList = name;
		const m = mem(name);

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
		// A press anywhere ends the claim: on a control it comes straight back with that
		// control's `focusin`, while a press on a row's plain text (which drops focus to <body>)
		// must not let the next live update pull focus, and the page, back to the old row.
		const onPointerDown = () => {
			m.focusWithin = false;
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
		// Remounted after a reload that unmounted it with focus inside: it takes focus back
		// (`settle` focuses the remembered row, or its neighbour, while focus is on <body>).
		// The rows may not exist yet when this runs, so the observer's next settle and a
		// microtask both try again; focus anywhere else meanwhile ends the claim.
		if (focusLost() && performance.now() < m.restoreUntil) m.focusWithin = true;
		m.restoreUntil = 0;
		settle(list);
		queueMicrotask(() => {
			if (list.isConnected) settle(list);
		});

		return () => {
			observer.disconnect();
			list.removeEventListener('focusin', onFocusIn);
			list.removeEventListener('focusout', onFocusOut);
			document.removeEventListener('pointerdown', onPointerDown, true);
			m.restoreUntil = m.focusWithin ? performance.now() + RESTORE_WINDOW_MS : 0;
			// An open job's track list is forgotten once closed (one entry per job opened would
			// otherwise pile up for the life of the tab), unless it still has a claim on focus.
			if (name.startsWith('job-tracks:') && !m.restoreUntil && memory.get(name) === m) {
				memory.delete(name);
			}
			// Until it's back, focus anywhere else wins.
			const cancel = () => {
				m.restoreUntil = 0;
				m.focusWithin = false;
			};
			if (m.restoreUntil) {
				const until = m.restoreUntil;
				document.addEventListener('focusin', cancel, { once: true, capture: true });
				setTimeout(() => {
					document.removeEventListener('focusin', cancel, { capture: true });
					// Never remounted in time: this claim lapses with its window (a later
					// unmount's own claim is left alone).
					if (m.restoreUntil === until) cancel();
				}, RESTORE_WINDOW_MS);
				if (opts.fallback) awaitFallback(m, opts.fallback);
			}
		};
	};
}

/** While an unmounted list's claim on focus lasts: once nothing remounted it and the page
 * names a fallback (no reload under way), focus goes there rather than staying on <body>. */
function awaitFallback(m: ListMemory, fallback: () => HTMLElement | null): void {
	const timer = setInterval(() => {
		if (!m.restoreUntil || performance.now() > m.restoreUntil || !focusLost()) {
			clearInterval(timer);
			return;
		}
		const target = fallback();
		if (!target) return;
		clearInterval(timer);
		target.focus();
	}, 150);
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

/** Closes the focused row (focus stays on, or returns to, its own button). On a closed track
 * inside an open job, closes the job and focuses it. */
export function collapseFocused(): boolean {
	const focused = focusedRow();
	if (!focused || horizontal(focused)) return false;
	let row: HTMLElement | null = focused;
	if (!isOpen(row)) {
		const list = listOf(row);
		row = list ? rowAt(list.parentElement) : null;
		if (!row || !isOpen(row)) return false;
	}
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
	/** Starts loading the next page; whether there was one to load. */
	loadMore: () => boolean;
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
		return opts.loadMore();
	};
	const step = (delta: number) => (event: KeyboardEvent) => {
		const row = focusedRow();
		const letter = event.key.length === 1;
		// The chips roam with ←/→ only: there j/k mean the rows, as they do anywhere outside a
		// list, and ↑/↓ keep scrolling the page.
		if (!row || horizontal(row)) {
			// j/k start the list from anywhere on the page; the arrows keep scrolling it.
			return letter ? focusList(opts.mainList()) : false;
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
			if (move(row, 'last')) return true;
			// Already on the last row: load more if there is more, else let End scroll.
			return !horizontal(row) && loadMoreFor(row);
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
