/**
 * v68 (U4): windowed rendering for the dashboard's long lists (the jobs, the tracks scope's job
 * groups, an open job's tracks). A fully loaded 1600-row log was about 28k DOM nodes (DESIGN
 * §8.6); above `VIRTUAL_THRESHOLD` rows a list renders only the rows near the viewport.
 *
 * In house rather than a library: the lists live in the page's own scroll (the window, not a
 * scrolling box), their rows vary in height (an open job holds its tracks, an open track its
 * detail), the keyboard model (`$lib/keyboard/lists`) must render any row by id synchronously,
 * and below the threshold the markup must stay exactly what it was. Weighed (their packages
 * read, none integrated; the PR has the comparison):
 * - `@tanstack/svelte-virtual` 3.13: window scrolling, measured sizes and a range extractor
 *   (pinned rows) would all fit, but it's headless (the positioning is still ours), its Svelte
 *   adapter is a `svelte/store` wrapper around a core with its own scheduling, and it would be
 *   a new dependency for what is ~300 lines here.
 * - `virtua` 0.54 (Svelte 5): renders its own absolutely positioned wrapper per item, which
 *   breaks `ul > li` (list semantics, the rows' scoped styles, the e2e selectors).
 * - `svelte-tiny-virtual-list` 4.0 (Svelte 5): scrolls its own fixed-height box.
 *
 * How it stays out of the way:
 * - The list element keeps its markup: the rows not rendered are the list's own top and bottom
 *   padding (inline, only above the threshold), so the page's scoped styles still apply and
 *   below the threshold the DOM is exactly what it was.
 * - Heights are measured once per render (one read pass, `getBoundingClientRect`) and then by a
 *   ResizeObserver (a row that opens, a font that loads). A row never measured counts as the
 *   median measured height per keyboard row, times its rows, and that estimate moves only when
 *   the median drifts by a quarter (a resize to a phone's width): every move of it shifts every
 *   unmeasured row at once, and a mean (one 400-track group among single tracks) moved with each
 *   row measured, which the anchoring then chased up the page. The last rendered row isn't measured unless it's the list's real
 *   last: the rows' `:last-child` rule drops their bottom border, and a window edge measured 1px
 *   short moved the window, which moved the edge (an endless re-render).
 * - Scroll anchoring by hand: padding changes suppress the browser's own anchoring (CSS Scroll
 *   Anchoring's suppression triggers), so the first row in view is held in place after every
 *   render and resize, the way the browser holds a plain list.
 * - Kept rendered outside the window: the row holding focus, the list's current (roving) row,
 *   and any open row (a track's detail is the row's own state, lost if it unmounted). They sit
 *   just past the window's edge, out of view, in their own place in the padding.
 * - A kept row is only a stand-in at the window's edge: anything that focuses it (a key, Tab,
 *   the help overlay putting focus back) renders the window around its real place first.
 * - Each rendered row carries `aria-setsize`/`aria-posinset`, so a screen reader says "812 of
 *   1600" for a list it only partly has. The size is the list's whole total when the page knows
 *   it exactly (`total`), else the rows loaded.
 * - A window holding an open, windowed list of its own (a job's 400 tracks) leaves the scroll to
 *   the inner one while that row fills the view: both correcting it undid each other.
 */
/* eslint-disable svelte/prefer-svelte-reactivity -- deliberately plain: the Maps and Sets here are
   temporaries built inside a derived, or caches whose changes are announced by `#measured` (a
   reactive Map of 1600 heights would re-run every reader on each row measured). */
import { flushSync, untrack } from 'svelte';
import { currentRowId, registerVirtual } from '$lib/keyboard/lists';

/** Above this many rows a list renders a window; at or below it, every row (as before v68). */
export const VIRTUAL_THRESHOLD = 200;
/** How far past the viewport, above and below, rows stay rendered. */
const OVERSCAN_PX = 1000;
/** A row's height before any row of the list has been measured. */
const FIRST_ESTIMATE_PX = 56;
/** How far the measured median may drift before the estimate follows it. */
const ESTIMATE_DRIFT = 0.25;

/** `offsets[i]` is item `i`'s top within the list, `offsets[n]` the whole height. */
export function offsetsOf(heights: readonly number[]): number[] {
	const offsets = new Array<number>(heights.length + 1);
	offsets[0] = 0;
	for (let i = 0; i < heights.length; i++) offsets[i + 1] = offsets[i] + heights[i];
	return offsets;
}

/** The items `[start, end)` overlapping `[lo, hi)` of the list (binary search on `offsets`). */
export function rangeOf(offsets: readonly number[], lo: number, hi: number): [number, number] {
	const n = offsets.length - 1;
	if (n <= 0) return [0, 0];
	// The first item whose bottom is below `lo`.
	let a = 0;
	let b = n;
	while (a < b) {
		const mid = (a + b) >> 1;
		if (offsets[mid + 1] > lo) b = mid;
		else a = mid + 1;
	}
	const start = Math.min(a, n - 1);
	// The first item from `start` whose top is at or below `hi`.
	a = start;
	b = n;
	while (a < b) {
		const mid = (a + b) >> 1;
		if (offsets[mid] >= hi) b = mid;
		else a = mid + 1;
	}
	return [start, Math.max(a, start + 1)];
}

export interface ListWindowOptions<T> {
	items: () => T[];
	key: (item: T) => string;
	/** The keyboard row ids (`data-kb-row`) an item holds, in order. Default: its key (an item
	 * is one row). The tracks scope's item is a job's group, holding its tracks. */
	rowIds?: (item: T) => string[];
	threshold?: number;
	/** The whole list's size when known exactly (more than the loaded rows); null if not. */
	total?: () => number | null;
}

/** Every attached window by its list element, so an outer one can tell a nested one's row. */
const windows = new Map<HTMLElement, ListWindow<unknown>>();

interface Slice {
	/** Item indices in render order: the window, with kept rows before and after it. */
	indices: number[];
	/** How many of `indices` are kept rows before the window, and after it. */
	before: number;
	after: number;
	padTop: number;
	padBottom: number;
}

export class ListWindow<T> {
	#items: () => T[];
	#key: (item: T) => string;
	#rowIds: (item: T) => string[];
	#total: () => number | null;
	#threshold: number;

	/** The viewport in the list's own coordinates (its top edge is 0). */
	#view = $state({ top: 0, height: 0 });
	/** An item the window is kept around (a revealed row) until the page next scrolls. */
	#hold = $state<number | null>(null);
	/** Bumped when a height changes (the heights themselves aren't reactive). */
	#measured = $state(0);
	/** Item keys kept rendered outside the window. */
	#pinned = $state<string[]>([]);
	/** The list element is attached. */
	#mounted = $state(false);

	#heights = new Map<string, number>();
	/** The estimated height of one keyboard row (an item holds `rowIds(item).length`). */
	#perRow = FIRST_ESTIMATE_PX;
	#perRowFrom = 0;
	#list: HTMLElement | null = null;
	#keys = new WeakMap<Element, string>();
	/** A rendered row's height key (`#sizeKey`). */
	#sizeKeys = new WeakMap<Element, string>();
	#observed = new Set<Element>();
	#resize: ResizeObserver | null = null;
	#focusKey: string | null = null;
	#anchor: { el: Element; top: number } | null = null;
	#annotated = false;
	#lastSlice: Slice | null = null;
	/** Height changes taken this frame: past a budget, the rest wait for the next frame, so no
	 * feedback between measuring and rendering can ever spin. */
	#burst = 0;
	#burstReset = 0;
	#deferred = false;

	constructor(opts: ListWindowOptions<T>) {
		this.#items = opts.items;
		this.#key = opts.key;
		this.#rowIds = opts.rowIds ?? ((item) => [opts.key(item)]);
		this.#threshold = opts.threshold ?? VIRTUAL_THRESHOLD;
		this.#total = opts.total ?? (() => null);
		// After every render of the window (its rows, its padding): measure, keep the reading
		// position, and learn where the viewport is now.
		// Only while the list is mounted: its items aren't read otherwise (between a scope switch
		// and its reload, the tracks scope's groups would be built from the jobs still listed).
		$effect(() => {
			if (!this.#mounted) return;
			void this.rendered;
			void this.style;
			untrack(() => this.#afterRender());
		});
	}

	/** Whether the list renders a window (above the threshold) rather than every row. */
	readonly active = $derived.by(() => {
		let rows = 0;
		for (const item of this.#items()) {
			rows += this.#rowIds(item).length;
			if (rows > this.#threshold) return true;
		}
		return false;
	});

	/** Every row id in order (windowed only). */
	readonly #allRowIds = $derived.by(() =>
		this.active ? this.#items().flatMap((item) => this.#rowIds(item)) : null
	);

	/** Item index by key, and by row id. */
	readonly #index = $derived.by(() => {
		const byKey = new Map<string, number>();
		const byRow = new Map<string, number>();
		if (!this.active) return { byKey, byRow };
		this.#items().forEach((item, i) => {
			byKey.set(this.#key(item), i);
			for (const id of this.#rowIds(item)) byRow.set(id, i);
		});
		return { byKey, byRow };
	});

	readonly #offsets = $derived.by(() => {
		if (!this.active) return [0];
		void this.#measured;
		const perRow = this.#perRow;
		return offsetsOf(
			this.#items().map(
				(item) => this.#heights.get(this.#sizeKey(item)) ?? perRow * this.#rowIds(item).length
			)
		);
	});

	readonly #slice = $derived.by((): Slice | null => {
		if (!this.active) return (this.#lastSlice = null);
		const offsets = this.#offsets;
		const n = offsets.length - 1;
		const { top, height } = this.#view;
		let [start, end] = rangeOf(offsets, top - OVERSCAN_PX, top + height + OVERSCAN_PX);
		const hold = this.#hold;
		if (hold !== null && hold < n && (hold < start || hold >= end)) {
			const middle = (offsets[hold] + offsets[hold + 1]) / 2;
			[start, end] = rangeOf(
				offsets,
				middle - height / 2 - OVERSCAN_PX,
				middle + height / 2 + OVERSCAN_PX
			);
		}
		const kept = this.#pinned
			.map((key) => this.#index.byKey.get(key))
			.filter((i): i is number => i !== undefined && (i < start || i >= end))
			.sort((a, b) => a - b);
		const before = kept.filter((i) => i < start);
		const after = kept.filter((i) => i >= end);
		const sum = (list: number[]) => list.reduce((s, i) => s + offsets[i + 1] - offsets[i], 0);
		const indices = [...before];
		for (let i = start; i < end; i++) indices.push(i);
		indices.push(...after);
		const slice: Slice = {
			indices,
			before: before.length,
			after: after.length,
			padTop: Math.max(0, offsets[start] - sum(before)),
			padBottom: Math.max(0, offsets[n] - offsets[end] - sum(after))
		};
		// The same rows and padding: the same object, so nothing re-renders.
		const last = this.#lastSlice;
		if (
			last &&
			Math.abs(last.padTop - slice.padTop) < 0.5 &&
			Math.abs(last.padBottom - slice.padBottom) < 0.5 &&
			last.indices.length === indices.length &&
			last.indices.every((v, i) => v === indices[i])
		) {
			return last;
		}
		return (this.#lastSlice = slice);
	});

	/** The items to render, in order: all of them below the threshold. */
	readonly rendered = $derived.by((): T[] => {
		const items = this.#items();
		const slice = this.#slice;
		return slice ? slice.indices.map((i) => items[i]) : items;
	});

	/** The list element's inline style: the unrendered rows' room. Undefined below the
	 * threshold, so the element has no `style` attribute at all. */
	readonly style = $derived.by((): string | undefined => {
		const slice = this.#slice;
		if (!slice) return undefined;
		// i18n-ignore: CSS
		return `padding-top: ${Math.round(slice.padTop)}px; padding-bottom: ${Math.round(slice.padBottom)}px`;
	});

	/** Attachment for the list element. */
	attach = (list: HTMLElement) => {
		this.#list = list;
		this.#mounted = true;
		const onScroll = () => {
			// The page moved: a held row has been scrolled to (or away from) by now.
			this.#hold = null;
			this.#capture();
			this.#readView();
		};
		const onFocusIn = (event: FocusEvent) => {
			this.#focusKey = this.#childKey(event.target as Node);
			this.#updatePins();
			// Focus reached a kept row at its stand-in place (Tab, a dialog or the help overlay
			// putting it back): the window moves to the row's real place. In a microtask, since a
			// `focus()` called from an effect lands here too, where flushSync isn't allowed.
			const key = this.#focusKey;
			const at = key === null ? undefined : this.#index.byKey.get(key);
			if (at !== undefined && this.active && !this.#inWindow(at)) {
				queueMicrotask(() => {
					if (this.#focusKey !== key || this.#index.byKey.get(key!) !== at) return;
					this.#hold = at;
					flushSync();
					(event.target as Element).closest?.('li')?.scrollIntoView({ block: 'nearest' });
				});
			}
		};
		const onFocusOut = (event: FocusEvent) => {
			const to = event.relatedTarget as Node | null;
			// Focus gone elsewhere. A row removed with focus inside has no `relatedTarget`, and
			// its key leaves the items anyway.
			if (to && !list.contains(to)) {
				this.#focusKey = null;
				this.#updatePins();
			}
		};
		window.addEventListener('scroll', onScroll, { passive: true });
		window.addEventListener('resize', onScroll, { passive: true });
		list.addEventListener('focusin', onFocusIn);
		list.addEventListener('focusout', onFocusOut);
		// A row opened or closed (its detail is kept while open).
		const opened = new MutationObserver(() => this.#updatePins());
		opened.observe(list, { subtree: true, attributes: true, attributeFilter: ['aria-expanded'] });
		this.#resize = new ResizeObserver((entries) => this.#onResize(entries));
		windows.set(list, this as ListWindow<unknown>);
		const unregister = registerVirtual(list, {
			ids: () => this.#allRowIds,
			reveal: (id) => this.reveal(id)
		});
		this.#readView();
		return () => {
			unregister();
			if (windows.get(list) === (this as ListWindow<unknown>)) windows.delete(list);
			window.removeEventListener('scroll', onScroll);
			window.removeEventListener('resize', onScroll);
			list.removeEventListener('focusin', onFocusIn);
			list.removeEventListener('focusout', onFocusOut);
			opened.disconnect();
			this.#resize?.disconnect();
			this.#resize = null;
			this.#observed.clear();
			this.#anchor = null;
			if (this.#list === list) {
				this.#list = null;
				this.#mounted = false;
			}
		};
	};

	/** Renders the item holding row `id` (scrolled into view) and returns that row's element. */
	reveal(id: string): HTMLElement | null {
		const list = this.#list;
		if (!list) return null;
		const find = () => list.querySelector<HTMLElement>(`[data-kb-row="${CSS.escape(id)}"]`);
		const row = find();
		if (!this.active) return row;
		const at = this.#index.byRow.get(id);
		if (at === undefined) return row;
		// Rendered inside the window: where it really is. A kept row outside the window is only a
		// stand-in at the window's edge, so it's revealed like an unrendered one.
		if (row && this.#inWindow(at)) return row;
		this.#hold = at;
		flushSync();
		const shown = find();
		shown?.scrollIntoView({ block: 'nearest' });
		return shown;
	}

	/** Whether item `index` is in the window proper (not a kept row outside it). */
	#inWindow(index: number): boolean {
		const slice = this.#lastSlice;
		if (!slice) return true;
		const first = slice.indices[slice.before];
		const last = slice.indices[slice.indices.length - slice.after - 1];
		return first !== undefined && index >= first && index <= last;
	}

	#afterRender(): void {
		const list = this.#list;
		if (!list) return;
		const children = list.children;
		if (!this.active) {
			// Back below the threshold: every row is rendered, and none carries the window's
			// annotations any more.
			if (this.#annotated) {
				for (const el of children) {
					el.removeAttribute('aria-setsize');
					el.removeAttribute('aria-posinset');
				}
				this.#annotated = false;
			}
			this.#resize?.disconnect();
			this.#observed.clear();
			this.#anchor = null;
			return;
		}
		const slice = this.#slice;
		const items = this.#items();
		// Mid-update (a row's component not mounted yet): the next render catches up.
		if (!slice || children.length !== slice.indices.length) return;
		this.#annotated = true;
		const size = String(Math.max(items.length, this.#total() ?? 0));
		const lastKey = items.length ? this.#key(items[items.length - 1]) : null;
		const seen = new Set<Element>();
		let changed = false;
		for (let c = 0; c < children.length; c++) {
			const el = children[c];
			const index = slice.indices[c];
			const key = this.#key(items[index]);
			const sizeKey = this.#sizeKey(items[index]);
			this.#keys.set(el, key);
			this.#sizeKeys.set(el, sizeKey);
			seen.add(el);
			if (el.getAttribute('aria-setsize') !== size) el.setAttribute('aria-setsize', size);
			const pos = String(index + 1);
			if (el.getAttribute('aria-posinset') !== pos) el.setAttribute('aria-posinset', pos);
			if (!this.#observed.has(el)) {
				this.#observed.add(el);
				this.#resize?.observe(el);
			}
			if (this.#measurable(el, key, lastKey)) {
				changed = this.#record(sizeKey, el.getBoundingClientRect().height) || changed;
			}
		}
		for (const el of this.#observed) {
			if (!seen.has(el)) {
				this.#resize?.unobserve(el);
				this.#observed.delete(el);
			}
		}
		if (changed) this.#remeasured();
		this.#updatePins();
		this.#correct();
		this.#readView();
	}

	#onResize(entries: ResizeObserverEntry[]): void {
		let changed = false;
		const items = this.#items();
		const lastKey = items.length ? this.#key(items[items.length - 1]) : null;
		for (const entry of entries) {
			const key = this.#keys.get(entry.target);
			const sizeKey = this.#sizeKeys.get(entry.target);
			if (key === undefined || sizeKey === undefined || !entry.target.isConnected) continue;
			if (!this.#measurable(entry.target, key, lastKey)) continue;
			const height = entry.borderBoxSize?.[0]?.blockSize ?? entry.contentRect.height;
			changed = this.#record(sizeKey, height) || changed;
		}
		if (changed) this.#remeasured();
		this.#correct();
	}

	/** What a height is remembered by: the item, and how many rows it holds (a job's group in
	 * the tracks scope grows when a page brings more of its tracks, rendered or not). */
	#sizeKey(item: T): string {
		return `${this.#key(item)}\u0000${this.#rowIds(item).length}`;
	}

	/** A rendered row's height is its own unless it's the last element shown without being the
	 * list's last item (`:last-child` styles it differently there). */
	#measurable(el: Element, key: string, lastKey: string | null): boolean {
		return el !== this.#list?.lastElementChild || key === lastKey;
	}

	#record(key: string, height: number): boolean {
		if (height <= 0) return false;
		const known = this.#heights.get(key);
		if (known !== undefined && Math.abs(known - height) < 0.5) return false;
		this.#heights.set(key, height);
		return true;
	}

	#remeasured(): void {
		const now = performance.now();
		if (now - this.#burstReset > 16) {
			this.#burst = 0;
			this.#burstReset = now;
		}
		if (++this.#burst > 8) {
			if (!this.#deferred) {
				this.#deferred = true;
				requestAnimationFrame(() => {
					this.#deferred = false;
					this.#remeasured();
				});
			}
			return;
		}
		// Keys of rows no longer loaded are dropped once they outnumber the loaded ones.
		const items = this.#items();
		if (this.#heights.size > 2 * items.length + 100) {
			const live = new Set(items.map((item) => this.#sizeKey(item)));
			for (const key of this.#heights.keys()) if (!live.has(key)) this.#heights.delete(key);
		}
		this.#estimatePerRow();
		this.#measured++;
	}

	/** Re-reads the per-row median when the samples have grown by half (or are few). */
	#estimatePerRow(): void {
		const count = this.#heights.size;
		if (count === 0 || (count >= 32 && count < this.#perRowFrom * 1.5)) return;
		this.#perRowFrom = count;
		const samples: number[] = [];
		for (const [key, height] of this.#heights) {
			const rows = Number(key.slice(key.lastIndexOf('\u0000') + 1)) || 1;
			samples.push(height / rows);
		}
		samples.sort((a, b) => a - b);
		const median = samples[samples.length >> 1];
		const first = this.#perRow === FIRST_ESTIMATE_PX && count <= 64;
		if (first || Math.abs(median - this.#perRow) > this.#perRow * ESTIMATE_DRIFT) {
			this.#perRow = median;
		}
	}

	/** The first rendered row in view and where it is, while the list runs past the viewport's
	 * top (above that, what's over the list holds the place). */
	#capture(): void {
		this.#anchor = null;
		const list = this.#list;
		const slice = this.#lastSlice;
		if (!list || !slice || list.getBoundingClientRect().top >= 0) return;
		// Only the window's own rows, and only one in view: a kept row outside the window moves
		// with the window's edge (after a jump it's far from the viewport, and following it
		// once threw the page back to the top), and a row below the view says nothing about it.
		const children = list.children;
		const end = children.length - slice.after;
		for (let c = slice.before; c < end; c++) {
			const el = children[c];
			const box = el.getBoundingClientRect();
			if (box.top >= window.innerHeight) return;
			if (box.bottom > 0) {
				// An open row holding a windowed list of its own: that list holds the view.
				for (const [inner, nested] of windows) {
					if (inner !== list && nested.active && el.contains(inner)) return;
				}
				this.#anchor = { el, top: box.top };
				return;
			}
		}
	}

	/** Puts the anchor row back where it was (rows above it measured, or padding changed). */
	#correct(): void {
		const anchor = this.#anchor;
		if (anchor && anchor.el.isConnected) {
			const delta = anchor.el.getBoundingClientRect().top - anchor.top;
			if (Math.abs(delta) >= 1) window.scrollBy({ top: delta, behavior: 'instant' });
		}
		this.#capture();
	}

	#readView(): void {
		const list = this.#list;
		if (!list) return;
		const top = -list.getBoundingClientRect().top;
		const height = window.innerHeight;
		const view = untrack(() => this.#view);
		if (Math.abs(view.top - top) >= 1 || view.height !== height) this.#view = { top, height };
	}

	/** The key of the list's item (its direct child) holding `node`. */
	#childKey(node: Node | null): string | null {
		const list = this.#list;
		let el: Element | null = node instanceof Element ? node : (node?.parentElement ?? null);
		while (el && el.parentElement !== list) el = el.parentElement;
		return el ? (this.#keys.get(el) ?? null) : null;
	}

	#updatePins(): void {
		const list = this.#list;
		if (!list || !this.active) {
			if (untrack(() => this.#pinned).length) this.#pinned = [];
			return;
		}
		const keys = new Set<string>();
		if (this.#focusKey !== null) keys.add(this.#focusKey);
		const current = currentRowId(list);
		const at = current === null ? undefined : this.#index.byRow.get(current);
		if (at !== undefined) keys.add(this.#key(this.#items()[at]));
		for (const item of list.querySelectorAll('[data-kb-item][aria-expanded="true"]')) {
			const key = this.#childKey(item);
			if (key !== null) keys.add(key);
		}
		const next = [...keys].sort();
		const pinned = untrack(() => this.#pinned);
		if (next.length !== pinned.length || next.some((k, i) => k !== pinned[i])) this.#pinned = next;
	}
}
