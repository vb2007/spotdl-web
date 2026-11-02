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
 *   the median drifts by a quarter: every move of it shifts every unmeasured row at once, and a
 *   mean (one 400-track group among single tracks) moved with each row measured, which the
 *   anchoring then chased up the page. A resize keeps the heights (the rendered rows
 *   re-measure; forgetting them all lost the view on a width change). The window's last
 *   rendered row ignores changes under 2.5px unless it's the list's real last: the rows'
 *   `:last-child` rule drops their bottom border, and a window edge measured 1px short moved
 *   the window, which moved the edge (an endless re-render).
 * - Scroll anchoring by hand: padding changes suppress the browser's own anchoring (CSS Scroll
 *   Anchoring's suppression triggers), so the first row in view is held in place after every
 *   render and resize, the way the browser holds a plain list. The browser's own anchoring
 *   stays on (switched off for the whole page, nothing held the layout no window corrects: a
 *   plain list around an open job's windowed tracks, a wrapping chip row). A correction is
 *   skipped when something else scrolled since the anchor was taken: a scroll event not the
 *   window's own, or a scrollY change from before the render reached the DOM (read as the
 *   slice is worked out); a change the render itself made is corrected through.
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
import { currentRowId, registerVirtual, rowAt, showRow } from '$lib/keyboard/lists';

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

/** The rows holding the view: the first window row in view and the next few after it (so one
 * of them is still there when the first is removed), each with where it should stay, and the
 * page's scroll then. */
interface Anchor {
	rows: { el: Element; top: number }[];
	/** The window's count of scrolls not its own (`#scrolled`) when taken: one since makes it
	 * stale. A count, not the page's scrollY: the browser's own anchoring moves scrollY during
	 * the very render being corrected (its scroll event comes later), and a scrollY guard then
	 * refused the correction (an open job far above archived: the view lost by 2,000px). */
	scrolled: number;
	/** The page's scrollY then: a change since that no scroll event has told of yet (the user's
	 * scrollBy, a jump) makes it stale too, except one a render of this list caused itself
	 * (`#preY`, read before the render reached the DOM). */
	scrollY: number;
}

/** How many rows in view an anchor follows at most: all of them on any screen, so a batch
 * removing the first few in view still leaves one to hold. */
const ANCHOR_ROWS = 40;

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
	/** The row holding the view, where it was, and the page's scroll then. */
	#anchor: Anchor | null = null;
	/** Where this window's own last correction left the page (its scroll event isn't the
	 * user's, so it doesn't re-take the anchor). */
	#ownScroll: number | null = null;
	/** scrollY before the render being handled (`$effect.pre`), or null. */
	#preY: number | null = null;
	/** The anchor as this frame's first render found it (`#holdFrame`). */
	#frameAnchor: Anchor | null = null;
	/** A near list's anchor is waiting for the next frame. */
	#captureQueued = false;
	/** Counts scrolls not made by this window (the user's, a focus() bringing a row in). */
	#scrolled = 0;
	/** The nested window holding the view instead (an open job's tracks filling it). */
	#delegate: ListWindow<unknown> | null = null;
	/** While delegating: the open job's own row and where it is, to place the window by
	 * (`#anchoredTop`) when rows above it change. */
	#placeAnchor: Anchor | null = null;
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

	/** How many keyboard rows the items hold (the threshold counts these, not items). */
	readonly #rows = $derived.by(() => {
		let rows = 0;
		for (const item of this.#items()) rows += this.#rowIds(item).length;
		return rows;
	});

	/** Whether the list renders a window (above the threshold) rather than every row. */
	readonly active = $derived.by(() => this.#rows > this.#threshold);

	/** Half way to the threshold: every row is still rendered, but heights, the anchor and the
	 * rows to keep are already followed, so the first window starts from them. */
	readonly #near = $derived.by(() => this.#rows * 2 >= this.#threshold);

	/** Every row id in order (windowed only). */
	readonly #allRowIds = $derived.by(() =>
		this.active ? this.#items().flatMap((item) => this.#rowIds(item)) : null
	);

	/** Item index by key, and by row id. */
	readonly #index = $derived.by(() => {
		const byKey = new Map<string, number>();
		const byRow = new Map<string, number>();
		if (!this.#near) return { byKey, byRow };
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
		this.#preY = window.scrollY;
		if (!this.active) return (this.#lastSlice = null);
		// The page's scroll as this render begins, before it reaches the DOM (the slice is worked
		// out during the render): a change the render itself makes (removing an open job moved
		// scrollY by 100px) is corrected through, while a scroll before it (the user's, its event
		// not yet in) makes the anchor stale. A plain field: an $effect.pre reading the same
		// deriveds looped (effect_update_depth_exceeded).
		this.#preY = window.scrollY;
		const offsets = this.#offsets;
		const n = offsets.length - 1;
		const { height } = this.#view;
		const top = this.#anchoredTop(offsets) ?? this.#view.top;
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
			// The scroll this window's own correction made: the anchor keeps its targets (the
			// browser rounds a scrollBy to whole pixels, and re-taking the anchor there lost the
			// fraction each time: a quarter pixel a removed row, 10px over 40).
			const own = this.#ownScroll !== null && Math.abs(window.scrollY - this.#ownScroll) < 1;
			this.#ownScroll = null;
			// Only a list near or above the threshold ever uses its anchor.
			if (!own) this.#scrolled++;
			if (this.#near && !own) this.#capture();
			this.#readView();
		};
		// The element that held focus when the browser window lost it: its focus coming back with
		// the window (alt-tab, the address bar) is no move, and must not pull the view to it.
		let returning: EventTarget | null = null;
		const onWindowBlur = () => {
			returning = document.activeElement;
		};
		// Event handlers and the keyboard module's callbacks read this window's reactive state; a
		// focus() or a settle inside some other attachment's effect runs them synchronously, and
		// untracked they'd make that effect depend on this list (re-running it on every patch).
		const onFocusIn = (event: FocusEvent) => untrack(() => focusIn(event));
		const onFocusOut = (event: FocusEvent) => untrack(() => focusOut(event));
		const focusIn = (event: FocusEvent) => {
			this.#focusKey = this.#childKey(event.target as Node);
			this.#updatePins();
			const back = returning !== null && event.target === returning;
			returning = null;
			if (back) return;
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
					// The row (or, taller than the view, its button) holding focus.
					const row = rowAt(event.target as Element);
					if (row) showRow(row);
				});
			}
		};
		const focusOut = (event: FocusEvent) => {
			const to = event.relatedTarget as Node | null;
			// Focus gone elsewhere. A row removed with focus inside has no `relatedTarget`, and
			// its key leaves the items anyway.
			if (to && !list.contains(to)) {
				this.#focusKey = null;
				this.#updatePins();
			}
		};
		window.addEventListener('scroll', onScroll, { passive: true });
		window.addEventListener('blur', onWindowBlur);
		// A resize keeps the heights: the rendered rows re-measure through the ResizeObserver.
		// (Forgetting every height on a width change threw the view hundreds of rows away, deep
		// in an open playlist or across the 900px layout step: the window was rebuilt from
		// estimates before the anchor could hold.)
		window.addEventListener('resize', onScroll, { passive: true });
		list.addEventListener('focusin', onFocusIn);
		list.addEventListener('focusout', onFocusOut);
		// A row opened or closed (its detail is kept while open).
		const opened = new MutationObserver(() => this.#updatePins());
		opened.observe(list, { subtree: true, attributes: true, attributeFilter: ['aria-expanded'] });
		this.#resize = new ResizeObserver((entries) => this.#onResize(entries));
		windows.set(list, this as ListWindow<unknown>);
		const unregister = registerVirtual(list, {
			ids: () => untrack(() => this.#allRowIds),
			reveal: (id) => untrack(() => this.reveal(id)),
			// The list's current row moved (a removed row's neighbour): keep that one rendered.
			changed: () => untrack(() => this.#updatePins()),
			// A focus() or a row scrolled into view moved the page: that is the place now.
			moved: () =>
				untrack(() => {
					this.#scrolled++;
					if (this.#near) this.#capture();
				})
		});
		this.#readView();
		return () => {
			unregister();
			if (windows.get(list) === (this as ListWindow<unknown>)) windows.delete(list);
			window.removeEventListener('scroll', onScroll);
			window.removeEventListener('blur', onWindowBlur);
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
		if (shown) showRow(shown);
		return shown;
	}

	/** An anchor nothing but this window has moved the page since. */
	#fresh(anchor: Anchor): boolean {
		return anchor.scrolled === this.#scrolled && Math.abs(window.scrollY - anchor.scrollY) < 1;
	}

	/** The view's top in the list's coordinates as the anchor puts it: where its row now is in
	 * the list, less where it is held in the view. Null without a valid anchor (none, or the
	 * page scrolled by something else since). The window is placed from this rather than from the
	 * last scroll position: when rows above change (an open job far above archived, 14,000px
	 * gone), the old position names rows far past the overscan, the rows read unmount, and the
	 * correction has nothing left to hold. Not tracked: the anchor isn't state. */
	#anchoredTop(offsets: number[]): number | null {
		const anchor = this.#anchor ?? this.#placeAnchor;
		if (!anchor || !this.#fresh(anchor)) return null;
		for (const row of anchor.rows) {
			const key = this.#keys.get(row.el);
			const at = key === undefined ? undefined : this.#index.byKey.get(key);
			if (at !== undefined) return offsets[at] - row.top;
		}
		return null;
	}

	/** Whether a rendered row (a child of the list) is one of the window's own, not a kept row
	 * outside it. Below the threshold every row is. */
	#isWindowRow(el: Element): boolean {
		if (!this.active) return true;
		const key = this.#keys.get(el);
		const at = key === undefined ? undefined : this.#index.byKey.get(key);
		return at !== undefined && this.#inWindow(at);
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
			// The render that turned the window off (rows removed above the view, the list back to
			// 200) also dropped the padding, which the browser's anchoring ignores: hold the view.
			const leaving = this.#annotated;
			if (leaving) {
				for (const el of children) {
					el.removeAttribute('aria-setsize');
					el.removeAttribute('aria-posinset');
				}
				this.#annotated = false;
				this.#correct(true);
			}
			// Nearing the threshold, every row is rendered: their heights are learned now, so
			// the first window has its rows' real places (with 56px guesses, crossing 200 moved
			// the view by thousands of pixels), and the view's anchor is kept for that render.
			// So are the rows to keep: the first window must already keep the focused, current
			// and open rows, or crossing 200 unmounts them (focus to <body>, a detail closed).
			// Heights come from the ResizeObserver alone here (each row once, then each real
			// change: a job collapsing), so a patch forces no layout; the anchor is taken once a
			// frame.
			const items = this.#items();
			if (this.#near && children.length === items.length) {
				const seen = new Set<Element>();
				for (let c = 0; c < children.length; c++) {
					const el = children[c];
					this.#keys.set(el, this.#key(items[c]));
					this.#sizeKeys.set(el, this.#sizeKey(items[c]));
					seen.add(el);
					if (!this.#observed.has(el)) {
						this.#observed.add(el);
						this.#resize?.observe(el);
					}
				}
				for (const el of this.#observed) {
					if (!seen.has(el)) {
						this.#resize?.unobserve(el);
						this.#observed.delete(el);
					}
				}
				const focused = this.#childKey(document.activeElement);
				if (focused !== null) this.#focusKey = focused;
				this.#updatePins();
				this.#captureSoon();
			} else {
				this.#resize?.disconnect();
				this.#observed.clear();
				this.#anchor = null;
			}
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
			const height = el.getBoundingClientRect().height;
			changed = this.#record(sizeKey, height, this.#tolerance(el, key, lastKey)) || changed;
		}
		for (const el of this.#observed) {
			if (!seen.has(el)) {
				this.#resize?.unobserve(el);
				this.#observed.delete(el);
			}
		}
		if (changed) this.#remeasured();
		this.#updatePins();
		this.#holdFrame();
		this.#correct(true);
		this.#readView();
	}

	/** Every render is corrected at once (so the window never drifts away from the rows read),
	 * and once more at the frame's end against the anchor as the frame began. Live removals land
	 * a few milliseconds apart and not in the list's order: corrected render by render, the row
	 * held could be one a later removal of the same frame shifted (a batch archive at the top of
	 * the view moved it by rows). requestAnimationFrame runs before the frame's layout and paint,
	 * so nothing shifted is shown; the browser's own anchoring works per frame too. */
	#holdFrame(): void {
		if (this.#frameAnchor !== null || !this.#anchor) return;
		const start = this.#anchor;
		const scrolled = this.#scrolled;
		this.#frameAnchor = start;
		requestAnimationFrame(() => {
			this.#frameAnchor = null;
			const now = this.#anchor;
			// Only while the page moved by this window's corrections alone since (a focus()
			// scrolling a restored neighbour into view is the place now).
			if (!this.#list || !now || scrolled !== this.#scrolled || !this.#fresh(now)) {
				return;
			}
			const row = start.rows.find((r) => r.el.isConnected && this.#isWindowRow(r.el));
			if (!row) return;
			const delta = row.el.getBoundingClientRect().top - row.top;
			if (Math.abs(delta) < 1) return;
			const y = window.scrollY;
			window.scrollBy({ top: delta, behavior: 'instant' });
			// Clamped at the page's edge (nothing moved): the anchor is taken where the page is.
			if (Math.abs(window.scrollY - y) < 1) {
				this.#capture();
				return;
			}
			this.#ownScroll = window.scrollY;
			this.#anchor = {
				rows: start.rows
					.filter((r) => r.el.isConnected && this.#isWindowRow(r.el))
					.map((r) =>
						r === row
							? r
							: {
									el: r.el,
									top:
										r.el.getBoundingClientRect().top -
										(row.el.getBoundingClientRect().top - row.top)
								}
					),
				scrolled: this.#scrolled,
				scrollY: window.scrollY
			};
			this.#readView();
		});
	}

	#onResize(entries: ResizeObserverEntry[]): void {
		let changed = false;
		const items = this.#items();
		const lastKey = items.length ? this.#key(items[items.length - 1]) : null;
		for (const entry of entries) {
			const key = this.#keys.get(entry.target);
			const sizeKey = this.#sizeKeys.get(entry.target);
			if (key === undefined || sizeKey === undefined || !entry.target.isConnected) continue;
			const tolerance = this.#tolerance(entry.target, key, lastKey);
			const height = entry.borderBoxSize?.[0]?.blockSize ?? entry.contentRect.height;
			changed = this.#record(sizeKey, height, tolerance) || changed;
		}
		if (changed) this.#remeasured();
		// Below the threshold the browser's own anchoring holds a plain list.
		if (this.active) this.#correct();
	}

	/** Takes the anchor once, at the next frame (a near list's patches force no layout). */
	#captureSoon(): void {
		if (this.#captureQueued) return;
		this.#captureQueued = true;
		requestAnimationFrame(() => {
			this.#captureQueued = false;
			if (this.#list && !this.active) this.#capture();
		});
	}

	/** What a height is remembered by: the item, and how many rows it holds (a job's group in
	 * the tracks scope grows when a page brings more of its tracks, rendered or not). */
	#sizeKey(item: T): string {
		return `${this.#key(item)}\u0000${this.#rowIds(item).length}`;
	}

	/** How far a measured height may differ from the known one before it's taken. The last
	 * element shown, when it isn't the list's last item, is styled by `:last-child` (no bottom
	 * border): a pixel or two there is that, not the row (taking it moved the window, which moved
	 * the last child, forever). A real change there (an open job collapsing: skipping that row
	 * outright kept its open height, and the window blank) is taken. */
	#tolerance(el: Element, key: string, lastKey: string | null): number {
		return el === this.#list?.lastElementChild && key !== lastKey ? 2.5 : 0.5;
	}

	#record(key: string, height: number, tolerance = 0.5): boolean {
		if (height <= 0) return false;
		const known = this.#heights.get(key);
		if (known !== undefined && Math.abs(known - height) < tolerance) return false;
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
		this.#delegate = null;
		this.#placeAnchor = null;
		const list = this.#list;
		// Below the threshold every child is a row in place (no kept rows around a window).
		const slice = this.#lastSlice ?? { before: 0, after: 0 };
		if (!list || list.getBoundingClientRect().top >= 0) return;
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
					// Only if that list has a row of its own in view (not while the view shows the
					// job's header above its tracks, or its "load more" below them): else this row
					// holds the view itself.
					if (inner !== list && nested.active && el.contains(inner) && nested.probe()) {
						this.#delegate = nested;
						this.#placeAnchor = {
							rows: [{ el, top: box.top }],
							scrolled: this.#scrolled,
							scrollY: window.scrollY
						};
						return;
					}
				}
				const rows = [{ el, top: box.top }];
				for (let n = c + 1; n < end && rows.length < ANCHOR_ROWS; n++) {
					const next = children[n].getBoundingClientRect();
					if (next.top >= window.innerHeight) break;
					rows.push({ el: children[n], top: next.top });
				}
				this.#anchor = { rows, scrolled: this.#scrolled, scrollY: window.scrollY };
				return;
			}
		}
	}

	/** Holds the view for an outer window whose row this list fills (it changed above it). */
	hold(): void {
		this.#correct();
		this.#readView();
	}

	/** Takes this list's anchor (for an outer window deciding whether to hand it the hold);
	 * whether it has one, of its own or delegated in turn. */
	probe(): boolean {
		// An anchor still valid (nothing scrolled since) is kept, with the fraction its own
		// corrections carry: re-taking it on every outer pass lost that, as before.
		const kept = this.#anchor;
		if (
			kept &&
			this.#fresh(kept) &&
			kept.rows.some((r) => r.el.isConnected && this.#isWindowRow(r.el))
		) {
			return true;
		}
		this.#capture();
		return this.#anchor !== null || this.#delegate !== null;
	}

	/** Puts the anchor row back where it was (rows above it measured, or padding changed). */
	/** `rendered`: called for a render of this list (its own changes may have moved scrollY). */
	#correct(rendered = false): void {
		const pre = this.#preY;
		this.#preY = null;
		const delegate = this.#delegate;
		if (!this.#anchor && delegate) {
			delegate.hold();
			this.#capture();
			return;
		}
		const anchor = this.#anchor;
		// Something scrolled the page since the anchor was taken (a focus() scrolling its row
		// into view, before its scroll event): that scroll is the user's place now, so the
		// anchor is taken again rather than restored over it.
		// The first of its rows still in the window (the first itself can be the one removed; one
		// still connected may since have become a kept stand-in at the window's edge, after a
		// jump, and following it would throw the page there).
		const live = (el: Element) => el.isConnected && this.#isWindowRow(el);
		const row = anchor?.rows.find((r) => live(r.el));
		const fresh = (a: Anchor) =>
			rendered && pre !== null
				? a.scrolled === this.#scrolled && Math.abs(pre - a.scrollY) < 1
				: this.#fresh(a);
		if (anchor && row && fresh(anchor)) {
			const delta = row.el.getBoundingClientRect().top - row.top;
			if (Math.abs(delta) >= 1) {
				const y = window.scrollY;
				window.scrollBy({ top: delta, behavior: 'instant' });
				// Clamped at the page's edge (the rows below the view went, at the bottom): no
				// scroll of its own, and the anchor is taken where the page is, not kept at a
				// target it can't reach (the next growth would apply it unasked).
				if (Math.abs(window.scrollY - y) < 1) {
					this.#capture();
					return;
				}
				this.#ownScroll = window.scrollY;
			}
			// The first row's target stays (the fraction the browser rounded away is made up next
			// time); the others' follow the page as it is now, relative to it (one of them may
			// have changed size, an open row, without anything scrolling).
			const off = row.el.getBoundingClientRect().top - row.top;
			this.#anchor = {
				rows: anchor.rows
					.filter((r) => live(r.el))
					.map((r) => (r === row ? r : { el: r.el, top: r.el.getBoundingClientRect().top - off })),
				scrolled: this.#scrolled,
				scrollY: window.scrollY
			};
			return;
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
		if (!list || !this.#near) {
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
