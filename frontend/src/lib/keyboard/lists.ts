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
 *
 * v68 (U4): a long list renders only a window of its rows (`$lib/listWindow.svelte`). It
 * registers here (`registerVirtual`), so every move, restore and lookup goes by the list's whole
 * order rather than the rows in the DOM, and a row outside the window is rendered (and scrolled
 * to) before it takes focus. A list below the threshold renders every row and registers nothing
 * that changes this module's behaviour.
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
	/** v63: a job's watch toggle and "retry failed". */
	watch?: () => unknown;
	retryFailed?: () => unknown;
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
	/** The row this list is nested in (an open job, for its tracks), if any. */
	parent: string | null;
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
/** How many elements are mounted under each name. An entry is only ever deleted while none
 * is, so a mounted list's cached entry and `mem(name)` are always the same object. */
const mounted = new Map<string, number>();

/** Drops a closed job's track-list entry (one per job opened would pile up for the life of
 * the tab), once no list of that name is mounted. */
function forget(name: string): void {
	if (name.startsWith('job-tracks:') && !mounted.get(name)) memory.delete(name);
}
const RESTORE_WINDOW_MS = 10_000;

/** Whether the latest input was a key rather than a pointer. Focus restoration is for the
 * keyboard: a mouse user's clicked row is never a claim, so a background reload never pulls
 * their page back to it (before v45 focus simply fell to <body> there, unscrolled). */
let keyboardInput = false;
if (typeof document !== 'undefined') {
	document.addEventListener(
		'keydown',
		() => {
			keyboardInput = true;
			// A key pressed on a row a click had focused: from here the keyboard drives it, so
			// its lists hold the claim (an `a` that archives it hands focus on, not to <body>).
			for (
				let list = document.activeElement?.closest<HTMLElement>('[data-kb-list]');
				list;
				list = list.parentElement?.closest<HTMLElement>('[data-kb-list]')
			) {
				mem(list.dataset.kbList ?? '').focusWithin = true;
			}
		},
		true
	);
	document.addEventListener('pointerdown', () => (keyboardInput = false), true);
}

function mem(key: string): ListMemory {
	let m = memory.get(key);
	if (!m) {
		m = { active: null, parent: null, order: [], focusWithin: false, restoreUntil: 0 };
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

/** v68: a windowed list's rows beyond the DOM. */
export interface VirtualRows {
	/** Every row id of the list in order, rendered or not; null while it renders them all. */
	ids(): string[] | null;
	/** Renders the row with this id (scrolled into view) and returns it; null if it has none. */
	reveal(id: string): HTMLElement | null;
	/** The list's current row changed (so the window can keep it rendered). */
	changed?(): void;
}

const virtuals = new Map<HTMLElement, VirtualRows>();

/** Called by a windowed list on its element; returns the unregister. */
export function registerVirtual(list: HTMLElement, rows: VirtualRows): () => void {
	virtuals.set(list, rows);
	return () => {
		if (virtuals.get(list) === rows) virtuals.delete(list);
	};
}

/** The list's current row id (its roving tab stop), which a windowed list keeps rendered. */
export function currentRowId(list: HTMLElement): string | null {
	return memory.get(list.dataset.kbList ?? '')?.active ?? null;
}

/** Every row id of `list`, in order: a windowed list's whole order, else its rows in the DOM. */
function orderOf(list: HTMLElement): string[] {
	return virtuals.get(list)?.ids() ?? rowsOf(list).map(rowId);
}

/** `list`'s row with this id: the rendered one, else (`reveal`) the one a windowed list renders
 * for it. Revealing renders synchronously (Svelte's `flushSync`), so it's never done inside an
 * effect (a list's own attachment). */
function rowIn(
	list: HTMLElement,
	id: string | null | undefined,
	reveal = true
): HTMLElement | null {
	if (id === null || id === undefined) return null;
	// A windowed list decides even when the row is rendered: a kept row outside its window is
	// only a stand-in at the window's edge.
	const windowed = virtuals.get(list);
	if (reveal && windowed?.ids()) return windowed.reveal(id);
	return rowsOf(list).find((r) => rowId(r) === id) ?? null;
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

// i18n-ignore: a selector
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
 * fallen to `<body>`, put focus back on the same row id, or the removed row's neighbour.
 * `reveal`: a windowed list may render that row (never from inside an effect). */
function settle(list: HTMLElement, reveal = true): void {
	const key = list.dataset.kbList ?? '';
	const m = mem(key);
	const before = m.active;
	const order = m.order;
	// v68: the list's whole order: a windowed list's row outside the window is still there.
	const ids = orderOf(list);
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
	// v68: a windowed list keeps the current row rendered, so Tab still finds it after its
	// predecessor went away with focus elsewhere.
	if (m.active !== before) virtuals.get(list)?.changed?.();
	m.order = ids;
	for (const nested of list.querySelectorAll<HTMLElement>('[data-kb-list]')) applyTabOrder(nested);
	applyTabOrder(list);
	if (!focusLost() || !m.focusWithin) return;
	// The document itself isn't focused (Tab went on into the browser's own UI, or another
	// window has it): never pull focus back from there. Once the page has it again, and
	// focus is still nowhere, the row takes it.
	if (!document.hasFocus()) {
		if (!awaitingFocus.has(list)) {
			awaitingFocus.add(list);
			window.addEventListener(
				'focus',
				() => {
					awaitingFocus.delete(list);
					if (list.isConnected) settle(list);
				},
				{ once: true }
			);
		}
		return;
	}
	// v68: a windowed list renders it first (its neighbour after a removal may be outside the
	// window).
	const activeRow = rowIn(list, m.active, reveal);
	// That row's own nested list (an open job's tracks) is reloading with focus inside: it
	// takes focus back itself when it remounts, onto the same track.
	if (activeRow) {
		const id = rowId(activeRow);
		const now = performance.now();
		for (const entry of memory.values())
			if (entry.parent === id && entry.restoreUntil > now) return;
	}
	// Focus was in this row's nested list (a track of the open job): that list puts it back
	// on its own row first, and only an emptied or closed one hands it to the job.
	const nested = activeRow ? nestedList(activeRow) : null;
	if (nested && mem(nested.dataset.kbList ?? '').focusWithin && rowsOf(nested).length) {
		settle(nested, reveal);
		if (!focusLost()) return;
	}
	// The same row back after a re-order stays where the user is reading, unless it moved
	// out of view (a reload re-sorted it); a neighbour after a removal is scrolled to.
	const same = before === m.active;
	if (focusRow(activeRow, { preventScroll: same }) && same && activeRow) {
		const box = activeRow.getBoundingClientRect();
		if (box.bottom < 0 || box.top > window.innerHeight) {
			activeRow.scrollIntoView({ block: 'nearest' });
		}
	}
}

/** Lists waiting for the page to have focus again before they put focus back. */
const awaitingFocus = new WeakSet<HTMLElement>();

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
		mounted.set(name, (mounted.get(name) ?? 0) + 1);
		const m = mem(name);
		const parentRow = rowAt(list.parentElement);
		m.parent = parentRow ? rowId(parentRow) : null;

		const onFocusIn = (event: FocusEvent) => {
			const row = rowAt(event.target as Element);
			// The row of *this* list that holds the focus (a nested track's job, say).
			let mine: HTMLElement | null = row;
			while (mine && listOf(mine) !== list) mine = rowAt(mine.parentElement);
			if (mine) {
				m.active = rowId(mine);
				m.focusWithin = keyboardInput;
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
		// Inside the attachment's effect: no reveal here (the microtask's settle may).
		settle(list, false);
		queueMicrotask(() => {
			if (list.isConnected) settle(list);
		});

		return () => {
			observer.disconnect();
			list.removeEventListener('focusin', onFocusIn);
			list.removeEventListener('focusout', onFocusOut);
			document.removeEventListener('pointerdown', onPointerDown, true);
			const left = (mounted.get(name) ?? 1) - 1;
			if (left > 0) mounted.set(name, left);
			else mounted.delete(name);
			m.restoreUntil = m.focusWithin ? performance.now() + RESTORE_WINDOW_MS : 0;
			// Unless it still has a claim on focus (a remount may come to take it back).
			if (!m.restoreUntil) forget(name);
			// Until it's back, focus anywhere else wins.
			const cancel = () => {
				m.restoreUntil = 0;
				m.focusWithin = false;
				// A closed job's track list that held focus is forgotten once its claim ends,
				// unless it has been mounted again meanwhile.
				forget(name);
			};
			if (m.restoreUntil) {
				const until = m.restoreUntil;
				// A press on plain text moves no focus but is just as clearly elsewhere.
				document.addEventListener('focusin', cancel, { once: true, capture: true });
				document.addEventListener('pointerdown', cancel, { once: true, capture: true });
				setTimeout(() => {
					document.removeEventListener('focusin', cancel, { capture: true });
					document.removeEventListener('pointerdown', cancel, { capture: true });
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
	// v68: by id through the list's whole order; a windowed list renders the target first.
	const ids = orderOf(list);
	const at = ids.indexOf(rowId(row));
	const target =
		to === 'first'
			? ids[0]
			: to === 'last'
				? ids[ids.length - 1]
				: ids[Math.min(Math.max(at + to, 0), ids.length - 1)];
	if (target === undefined || target === rowId(row)) return false;
	const next = rowIn(list, target);
	if (!focusRow(next)) return false;
	// A windowed list scrolls the row's whole button into view: the browser leaves one it can
	// partly see where it is, and one past the window's edge must not hide the focus ring.
	// The button, not the row: an open job's row can be taller than the view.
	if (next && virtuals.get(list)?.ids()) {
		const box = (itemOf(next) ?? next).getBoundingClientRect();
		if (box.top < 0 || box.bottom > window.innerHeight) showRow(next);
	}
	return true;
}

/** v68: scrolls `row` into view for its focus ring: the whole row when it fits the view (its
 * button alone would sit flush on the edge, the ring cut), else (an open job taller than the
 * view) its own button, centered. */
export function showRow(row: HTMLElement): void {
	const item = itemOf(row);
	const box = row.getBoundingClientRect();
	if (item && box.height > window.innerHeight) {
		item.scrollIntoView({ block: 'center' });
		return;
	}
	// A row not in view at all is centered (as the browser's own focus scroll does); one partly
	// in view is brought in with room for its ring (a track row is no taller than its button).
	if (box.bottom <= 0 || box.top >= window.innerHeight) {
		row.scrollIntoView({ block: 'center' });
		return;
	}
	const room = RING_ROOM_PX;
	if (box.top < room) window.scrollBy({ top: box.top - room, behavior: 'instant' });
	else if (box.bottom > window.innerHeight - room) {
		window.scrollBy({ top: box.bottom - window.innerHeight + room, behavior: 'instant' });
	}
}

/** The focus ring's width and offset (DESIGN §2 Focus: 3px at 2px), with a pixel to spare. */
const RING_ROOM_PX = 6;

/** The current row of the named list, focused. */
export function focusList(name: string): boolean {
	const list = document.querySelector<HTMLElement>(`[data-kb-list="${CSS.escape(name)}"]`);
	if (!list) return false;
	return focusCurrent(list);
}

/** `list`'s current row, else its first, focused (v68: rendered first if windowed). */
function focusCurrent(list: HTMLElement): boolean {
	const ids = orderOf(list);
	const m = mem(list.dataset.kbList ?? '');
	return focusRow(rowIn(list, m.active !== null && ids.includes(m.active) ? m.active : ids[0]));
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
	return focusCurrent(nested);
}

/** The button of the row with this id, wherever it is mounted now (a remounted row is a new
 * element), or null. */
export function rowItemById(id: string): HTMLElement | null {
	const row = rowById(id);
	return row ? itemOf(row) : null;
}

/** v68: the row with this id, wherever it is mounted now; a windowed list that has it outside
 * its window renders it (scrolled into view) first. Null if no list has it. */
export function rowById(id: string): HTMLElement | null {
	const row = document.querySelector<HTMLElement>(`[data-kb-row="${CSS.escape(id)}"]`);
	if (row) {
		// Rendered, but perhaps as a kept stand-in outside its list's window.
		const list = listOf(row);
		const windowed = list ? virtuals.get(list) : undefined;
		return windowed?.ids() ? (windowed.reveal(id) ?? row) : row;
	}
	for (const [list, rows] of virtuals) {
		if (list.isConnected && rows.ids()?.includes(id)) return rows.reveal(id);
	}
	return null;
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
		const row = focusedRow();
		let fn = actionsOf(row)?.[name];
		// v63: a job's watch and "retry failed" also answer from a track inside the open job.
		if (!fn && (name === 'watch' || name === 'retryFailed') && row) {
			const list = listOf(row);
			fn = actionsOf(list ? rowAt(list.parentElement) : null)?.[name];
		}
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
	/** Focus is on an open job's "load more tracks": it pages that job's tracks. */
	const onLoadMoreButton = (): boolean => {
		const button = document.activeElement?.closest<HTMLElement>('[data-kb-load-more]');
		if (!button) return false;
		button.click();
		return true;
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
			// On an open job's "load more tracks": that list's own load more.
			if (onLoadMoreButton()) return true;
			const row = focusedRow();
			if (!row) return false;
			if (move(row, 'last')) return true;
			// Already on the last row: load more if there is more, else let End scroll.
			return !horizontal(row) && loadMoreFor(row);
		},
		'load-more': () => onLoadMoreButton() || loadMoreFor(focusedRow()),
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
		repeats: action('repeats'),
		watch: action('watch'),
		'retry-failed': action('retryFailed')
	};
}
