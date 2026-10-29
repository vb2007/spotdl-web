<script lang="ts">
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import { confirmAction, keepFocus } from '$lib/stores/confirm';
	import type { Scope } from '$lib/stores/queue';
	import { SvelteSet } from 'svelte/reactivity';
	import { focusList, kbList } from '$lib/keyboard/lists';
	import * as m from '$lib/paraglide/messages';
	import { errorText } from '$lib/i18n/errors';
	import { formatNumber } from '$lib/i18n/format';
	import { jobStatusLabel, trackStateLabel } from '$lib/i18n/labels';

	let {
		isAdmin,
		view,
		onViewChange,
		countsByStatus,
		countsByState,
		countText
	}: {
		isAdmin: boolean;
		/** v54: the admin's mine/all/others scope. */
		view: api.View;
		onViewChange: (value: api.View) => void;
		countsByStatus: Record<string, number>;
		countsByState: Record<string, number>;
		/** The list's own size line ("7 of 7 jobs", "Loading…"), shown beside the heading. */
		countText: string;
	} = $props();

	const { filters, page } = queue;

	// v54: three ways to look at the queue, in the order the view key (Shift+V) cycles them.
	const VIEW_OPTIONS: { view: api.View; label: () => string }[] = [
		{ view: 'mine', label: m.queuectl_viewing_mine },
		{ view: 'all', label: m.queuectl_viewing_all },
		{ view: 'others', label: m.queuectl_viewing_others }
	];

	// v47 (v39 §4.3): a search, filter or scope change ends in one announced sentence, the
	// list's size, once its load lands. The visible count changes with every live update
	// too, so it isn't a live region itself: that would talk over the page all day. Only a
	// load whose filters differ from the last announced one speaks (a stream reconnect's
	// resync reloads with the same filters, and the first load isn't a change), and the
	// region is emptied first so a repeated count is announced again.
	let announcedCount = $state('');
	let wasLoading = false;
	let announcedFor: string | null = null;
	const FAILED = '\u0000failed';
	let announceTimer: ReturnType<typeof setTimeout> | undefined;
	$effect(() => {
		const loading = $page.loading;
		const f = $filters;
		const key = JSON.stringify([
			f.scope,
			f.q,
			f.status,
			f.state,
			f.includeArchived,
			queue.getView()
		]);
		if (wasLoading && !loading) {
			if (!$page.error && announcedFor !== null && key !== announcedFor) {
				const text = countText;
				announcedCount = '';
				clearTimeout(announceTimer);
				announceTimer = setTimeout(() => (announcedCount = text), 50);
			}
			// A failed load marks nothing as heard: the retry that lands next (same filters, or the
			// first load's) is announced, and so is every change after it.
			announcedFor = $page.error ? FAILED : key;
		}
		wasLoading = loading;
	});
	$effect(() => () => clearTimeout(announceTimer));

	let searchTimer: ReturnType<typeof setTimeout> | undefined;

	// v42: the page's "clear search and filters" empties `q` from outside, so the box
	// follows the store -- but only when `q` itself changes: `storeQ` is a derived, which
	// only notifies on a new value, so typing (whose debounce writes the same value back)
	// and unrelated filter changes never overwrite the box mid-word.
	let storeQ = $derived($filters.q);
	let searchInput = $derived(storeQ);

	/** v42: the page's "clear search and filters". Here, not on the page, so a search still
	 * waiting in the debounce can't re-apply itself right after the clear. */
	export function clearSearchAndFilters() {
		clearTimeout(searchTimer);
		searchInput = '';
		queue.setFilters({ q: '', status: [], state: [] });
		// On touch, a programmatic focus on the search box would pop the keyboard up over
		// the list just unfiltered: the queue heading instead.
		document
			.getElementById(
				// i18n-ignore: a media query
				window.matchMedia('(pointer: coarse)').matches ? 'queue-heading' : 'queue-search'
			)
			?.focus();
	}

	// A search still waiting must never land in the module-level store after queue.reset()
	// and filter the next identity's queue: the debounce checks the reset count when it
	// fires (below), and unmounting cancels it too.
	$effect(() => () => clearTimeout(searchTimer));

	function onSearchInput(value: string) {
		searchInput = value;
		clearTimeout(searchTimer);
		// Dropped if the store was reset meanwhile (a logout, or a session expiry that resets
		// before this page unmounts): it belongs to the previous identity.
		const session = queue.getResetCount();
		searchTimer = setTimeout(() => {
			if (queue.getResetCount() === session) queue.setFilters({ q: searchInput });
		}, 300);
	}

	export function setScope(scope: Scope) {
		if (scope === $filters.scope) return;
		queue.setFilters({ scope });
	}

	/** v45's Esc in the search box: empties it (and the store's `q`), dropping a search still
	 * waiting in the debounce. Whether anything was there to clear. */
	export function clearSearch(): boolean {
		clearTimeout(searchTimer);
		const had = searchInput !== '' || $filters.q !== '';
		searchInput = '';
		if ($filters.q !== '') queue.setFilters({ q: '' });
		return had;
	}

	/** v45's `s`: the next sort field, wrapping; a new field starts descending, as picking it
	 * in the select does. */
	export function cycleSort() {
		const at = sortFields.findIndex((f) => f.value === $filters.sort);
		onSortField(sortFields[(at + 1) % sortFields.length].value);
	}

	/** v45's `Shift+A`. */
	export function toggleArchived() {
		queue.setFilters({ includeArchived: !$filters.includeArchived });
	}

	/** v45's `Shift+F`: into the chips (one Tab stop, the arrows roam them). With none shown
	 * (nothing to filter), the sort is the next control. */
	export function focusFilters(): boolean {
		if (focusList('chips')) return true;
		document.getElementById('queue-sort')?.focus();
		return true;
	}

	interface Chip {
		key: string;
		/** v46: a function, so the chip re-renders in the new language on a switch. */
		label: () => string;
		/** The filter tokens one chip stands for -- several for a merged chip. */
		tokens: string[];
	}

	// Track-state filter chips: v35 (g) gave them live counts (the tracks listing's
	// counts_by_state), the same way the Jobs-scope status filter has always had.
	const TRACK_CHIPS_ADMIN: Chip[] = (
		[
			'pending',
			'queued',
			'downloading',
			'waiting',
			'lookup_failed',
			'completed',
			'skipped_duplicate',
			'cancelled'
		] as const
	).map((state) => ({ key: state, label: () => trackStateLabel(state), tokens: [state] }));
	// v42 (v39 outcome 3, owner's choice): pending/queued/downloading is the dispatcher's
	// distinction, not the listener's, so a non-admin gets one "in progress" chip for it.
	const TRACK_CHIPS_USER: Chip[] = [
		{
			key: 'in-progress',
			label: m.queuectl_chip_in_progress,
			tokens: ['pending', 'queued', 'downloading']
		},
		...TRACK_CHIPS_ADMIN.slice(3)
	];
	const JOB_CHIPS: Chip[] = api.STATUS_TOKENS.map((token) => ({
		key: token,
		label: () => jobStatusLabel(token),
		tokens: [token]
	}));

	let chips = $derived(
		$filters.scope === 'jobs' ? JOB_CHIPS : isAdmin ? TRACK_CHIPS_ADMIN : TRACK_CHIPS_USER
	);
	let selected = $derived($filters.scope === 'jobs' ? $filters.status : $filters.state);
	let counts = $derived($filters.scope === 'jobs' ? countsByStatus : countsByState);

	function chipCount(chip: Chip): number {
		return chip.tokens.reduce((sum, t) => sum + (counts[t] ?? 0), 0);
	}

	function chipPressed(chip: Chip): boolean {
		return chip.tokens.every((t) => selected.includes(t));
	}

	// A chip the user has toggled in this scope stays put even once its count reaches zero,
	// so unpressing it never pulls the focused button out from under the keyboard; so does
	// whichever chip has focus while a live count refresh drops it to zero.
	const touched = new SvelteSet<string>();
	let focusedChip = $state<string | null>(null);
	// While the pointer is over the chips, the set on screen holds still: a live count
	// refresh hiding a zero chip would shift its neighbours under a click in progress.
	let pointerChips = $state<Set<string> | null>(null);
	// A scope switch swaps the whole chip set (and may unmount the row, which then never
	// sees pointerleave): the freeze must not outlive the scope it was taken in.
	let scopeForFreeze = $derived($filters.scope);
	$effect(() => {
		void scopeForFreeze;
		pointerChips = null;
		focusedChip = null;
	});
	let touchedScope = $state<Scope>('jobs');

	// v42 (F11): a chip with nothing behind it is noise. It stays while pressed (so a filter
	// can always be switched off again) and once touched (above).
	let visibleChips = $derived(
		chips
			.filter(
				(c) =>
					// Frozen under the pointer: nothing appears or disappears mid-aim.
					!pointerChips || pointerChips.has(c.key) || chipPressed(c) || focusedChip === c.key
			)
			.filter(
				(c) =>
					chipCount(c) > 0 ||
					chipPressed(c) ||
					focusedChip === c.key ||
					pointerChips?.has(c.key) ||
					(touchedScope === $filters.scope && touched.has(c.key))
			)
	);

	function toggleChip(chip: Chip) {
		if (touchedScope !== $filters.scope) {
			touchedScope = $filters.scope;
			touched.clear();
		}
		touched.add(chip.key);
		const next = chipPressed(chip)
			? selected.filter((t) => !chip.tokens.includes(t))
			: [...selected, ...chip.tokens.filter((t) => !selected.includes(t))];
		queue.setFilters($filters.scope === 'jobs' ? { status: next } : { state: next });
	}

	interface SortField {
		value: string;
		label: () => string;
	}

	// "next retry" orders by the retry ladder's schedule: operator detail, admin only.
	let sortFields: SortField[] = $derived(
		$filters.scope === 'tracks'
			? [
					{ value: 'created_at', label: m.queuectl_sort_created },
					{ value: 'title', label: m.queuectl_sort_title },
					{ value: 'state', label: m.queuectl_sort_state }
				]
			: [
					{ value: 'created_at', label: m.queuectl_sort_created },
					{ value: 'title', label: m.queuectl_sort_title },
					{ value: 'status', label: m.queuectl_sort_status },
					{ value: 'track_count', label: m.queuectl_sort_track_count },
					...(isAdmin ? [{ value: 'next_retry', label: m.queuectl_sort_next_retry }] : [])
				]
	);

	// A different field starts descending, as the old sort buttons did.
	function onSortField(field: string) {
		if (field !== $filters.sort) queue.setFilters({ sort: field, dir: 'desc' });
	}

	function flipDir() {
		queue.setFilters({ dir: $filters.dir === 'asc' ? 'desc' : 'asc' });
	}

	// v62 (F8): what "clear log" archives (archive.py's eligible jobs): every finished one.
	const CLEARABLE = ['settled:complete', 'settled:partial', 'cancelled', 'failed'];
	// Off (aria-disabled, still focusable so its reason is read) when the view's counts say
	// there's nothing finished to archive. Only where those counts can say it: the viewer's jobs
	// are all in them (mine, all; not others, which leaves them out, nor under a search, which
	// counts only its matches), and the page has loaded. Anywhere else it stays on: the
	// action archives every finished job of yours, whatever the view shows.
	const nothingToClear = $derived(
		!$page.loading &&
			$page.error === null &&
			view !== 'others' &&
			!$filters.q.trim() &&
			CLEARABLE.every((key) => !((countsByStatus[key] ?? 0) > 0))
	);

	// v43 (F08): archives every settled job of yours in one go, so it asks first.
	let clearError = $state('');
	// It answers one press; it doesn't stay under the heading for the rest of the visit.
	function showClearNote(text: string) {
		clearError = text;
		setTimeout(() => {
			if (clearError === text) clearError = '';
		}, 10_000);
	}
	async function onClearLog() {
		if (nothingToClear) {
			// Says why where a sighted keyboard user sees it too, and asks the server again in
			// case the local counts drifted (review round 7): if it has something to clear, the
			// button turns back on.
			showClearNote(m.queuectl_clear_none());
			void queue.recountJobs();
			return;
		}
		const session = queue.getResetCount();
		clearError = '';
		const confirmed = await confirmAction({
			title: m.queuectl_clear_title(),
			body: m.queuectl_clear_body(),
			confirmLabel: m.queuectl_clear_yes(),
			cancelLabel: m.queuectl_clear_no()
		});
		// Kept or Esc: a switch to tracks scope meanwhile takes "clear log" away.
		if (!confirmed) return keepFocus(document.getElementById('queue-heading'));
		// Another identity took over meanwhile: this answer belongs to the previous session.
		if (queue.getResetCount() !== session) return;
		try {
			await queue.archiveJobs({ allSettled: true });
		} catch (err) {
			if (queue.getResetCount() !== session) return;
			showClearNote(
				m.queuectl_clear_failed({
					reason: errorText(err, m.queuectl_clear_unreachable)
				})
			);
		}
	}
</script>

<div class="queue-head">
	<h2 id="queue-heading" class="label" tabindex="-1">{m.queuectl_heading()}</h2>
	<span class="count mono">{countText}</span>
	<span class="sr-only" role="status">{announcedCount}</span>
	<div class="log-tools">
		<button
			type="button"
			class="chip"
			aria-pressed={$filters.includeArchived}
			onclick={toggleArchived}
		>
			{m.queuectl_show_archived()}
		</button>
		{#if $filters.scope === 'jobs'}
			<!-- Archives every settled job of *yours*, whatever the search, filters or all-users
			     view (archive.archive_jobs), after a confirmation (v43). -->
			<button
				type="button"
				class="chip danger"
				aria-disabled={nothingToClear ? 'true' : undefined}
				aria-describedby={nothingToClear ? 'clear-log-none' : undefined}
				title={nothingToClear ? m.queuectl_clear_none() : undefined}
				onclick={onClearLog}>{m.queuectl_clear()}</button
			>
			<span id="clear-log-none" class="sr-only"
				>{nothingToClear ? m.queuectl_clear_none() : ''}</span
			>
		{/if}
	</div>
</div>
<p class="clear-error" role="alert">{clearError}</p>

<div class="controls" role="group" aria-label={m.queuectl_controls_label()}>
	<div class="find">
		<div class="segmented" role="group" aria-label={m.queuectl_scope_label()}>
			<button
				type="button"
				aria-pressed={$filters.scope === 'jobs'}
				onclick={() => setScope('jobs')}
			>
				{m.queuectl_scope_jobs()}
			</button>
			<button
				type="button"
				aria-pressed={$filters.scope === 'tracks'}
				onclick={() => setScope('tracks')}
			>
				{m.queuectl_scope_tracks()}
			</button>
		</div>

		<input
			type="search"
			id="queue-search"
			class="search well"
			placeholder={$filters.scope === 'jobs'
				? m.queuectl_search_jobs_placeholder()
				: m.queuectl_search_tracks_placeholder()}
			value={searchInput}
			oninput={(e) => onSearchInput(e.currentTarget.value)}
			aria-label={$filters.scope === 'jobs'
				? m.queuectl_search_jobs_label()
				: m.queuectl_search_tracks_label()}
		/>

		{#if isAdmin}
			<div class="segmented" role="group" aria-label={m.queuectl_viewing_label()}>
				{#each VIEW_OPTIONS as option (option.view)}
					<button
						type="button"
						aria-pressed={view === option.view}
						onclick={() => onViewChange(option.view)}
					>
						{option.label()}
					</button>
				{/each}
			</div>
		{/if}
	</div>

	<div class="refine">
		{#if visibleChips.length > 0}
			<!-- F21: the label names what the counts count, so "waiting 1" (one job) isn't
			     read against a row's "8 waiting" (tracks). -->
			<div
				class="filters"
				onpointerenter={() => (pointerChips = new Set(visibleChips.map((c) => c.key)))}
				onpointerleave={() => (pointerChips = null)}
				role="group"
				aria-label={$filters.scope === 'jobs'
					? m.queuectl_filter_jobs_label()
					: m.queuectl_filter_tracks_label()}
				data-kb-orientation="horizontal"
				{@attach kbList('chips')}
			>
				<span class="label" aria-hidden="true"
					>{$filters.scope === 'jobs' ? m.queuectl_scope_jobs() : m.queuectl_scope_tracks()}</span
				>
				{#each visibleChips as chip (chip.key)}
					<button
						type="button"
						class="chip"
						data-kb-row={chip.key}
						data-kb-item
						aria-pressed={chipPressed(chip)}
						onfocus={() => (focusedChip = chip.key)}
						onblur={(e) => {
							// Switching tab or window blurs the chip but leaves it the active
							// element; it must keep its place for when the user comes back.
							if (document.activeElement !== e.currentTarget) focusedChip = null;
						}}
						onclick={() => toggleChip(chip)}
					>
						{chip.label()}&nbsp;<span class="n mono">{formatNumber(chipCount(chip))}</span>
					</button>
				{/each}
			</div>
		{/if}

		<div class="sort">
			<label class="label" for="queue-sort">{m.queuectl_sort()}</label>
			<select
				id="queue-sort"
				class="well"
				value={$filters.sort}
				onchange={(e) => onSortField(e.currentTarget.value)}
			>
				{#each sortFields as field (field.value)}
					<option value={field.value}>{field.label()}</option>
				{/each}
			</select>
			<button
				type="button"
				class="chip dir"
				aria-label={$filters.dir === 'asc'
					? m.queuectl_dir_label_asc()
					: m.queuectl_dir_label_desc()}
				title={$filters.dir === 'asc' ? m.queuectl_dir_asc() : m.queuectl_dir_desc()}
				onclick={flipDir}
			>
				<span aria-hidden="true">{$filters.dir === 'asc' ? '↑' : '↓'}</span>
			</button>
		</div>
	</div>
</div>

<style>
	/* The queue panel's head: its heading and size on the left, the log's own tools
	   (archive visibility and clearing) on the right, apart from the view controls. */
	.queue-head {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-3);
		padding: var(--space-3) var(--space-4) 0;
	}

	.count {
		color: var(--text-muted);
		font-size: var(--fs-meta);
	}

	/* Outside the head's flex row, so it takes no space at rest (an empty <p> has no height)
	   and stays a live region, never display:none. */
	.clear-error {
		padding: 0 var(--space-4);
		font-size: var(--fs-meta);
		color: var(--fail);
	}

	.log-tools {
		display: flex;
		gap: var(--space-2);
		margin-left: auto;
	}

	.controls {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		border-bottom: 1px solid var(--line);
	}

	.find,
	.refine {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	.refine {
		justify-content: space-between;
	}

	/* v47: every control on the find and refine rows shares one height (--control-h), so
	   segments, the search well, chips and the sort select line up instead of 26-41px. */
	.search {
		flex: 1 1 14rem;
		min-width: 0;
		min-height: var(--control-h);
		padding: var(--space-1) var(--space-3);
		color: var(--text-primary);
		font-family: var(--font-sans);
	}

	.filters {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.filters .label {
		margin-right: var(--space-1);
	}

	.sort {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin-left: auto;
	}

	.sort select {
		font: inherit;
		min-height: var(--control-h);
		padding: var(--space-1) var(--space-2);
		color: var(--text-primary);
		font-size: var(--fs-detail);
	}

	/* A segmented switch: two or three options, one pressed, one shared edge. View scope,
	   never a live condition, so §2 keeps it off --signal. */
	.segmented {
		display: inline-flex;
		border: 1px solid var(--line-control);
		border-radius: 4px;
	}

	.segmented button:first-child {
		border-radius: 3px 0 0 3px;
	}

	.segmented button:last-child {
		border-radius: 0 3px 3px 0;
	}

	/* v45: the ring sits inside the segment. Drawn outside, it spilled over the neighbour's
	   face and read as marking both. */
	.segmented button:focus-visible {
		outline-offset: -3px;
	}

	.segmented button {
		background: var(--bg-2);
		border: none;
		min-height: calc(var(--control-h) - 2px);
		padding: var(--space-1) var(--space-3);
		font-size: var(--fs-detail);
		font-weight: var(--fw-medium);
		line-height: 1.25;
		color: var(--text-muted);
		cursor: pointer;
	}

	.segmented button + button {
		border-left: 1px solid var(--line-control);
	}

	/* Pressed carries a mark hover never has: a 2px floor line (shape, not only fill), so
	   a hovered option can't pass for the selected one. */
	.segmented button[aria-pressed='true'] {
		background: var(--bg-3);
		color: var(--text-primary);
		box-shadow: inset 0 -2px 0 var(--text-muted);
	}

	.chip {
		background: var(--bg-2);
		border: 1px solid var(--line-control);
		border-radius: 4px;
		min-height: var(--control-h);
		padding: var(--space-1) var(--space-3);
		font-size: var(--fs-detail);
		font-weight: var(--fw-medium);
		line-height: 1.25;
		color: var(--text-muted);
		cursor: pointer;
		white-space: nowrap;
	}

	/* The count is a reading: it keeps the instrument face (DESIGN.md §3). */
	.chip .n {
		font-size: var(--fs-meta);
		color: var(--text-dim);
	}

	/* Pressed is a selection, not a signal: a brighter edge and full-strength text. */
	.chip[aria-pressed='true'] {
		background: var(--bg-3);
		border-color: var(--text-muted);
		color: var(--text-primary);
		box-shadow: inset 0 -2px 0 var(--text-muted);
	}

	/* On a pressed chip's --bg-3 the dim count would drop under 4.5:1. */
	.chip[aria-pressed='true'] .n {
		color: var(--text-primary);
	}

	@media (hover: hover) {
		.chip:hover .n {
			color: var(--text-muted);
		}
	}

	/* Hover lifts only the text: the fill and floor line stay the pressed state's. A
	   documented exception to the neutral hover (DESIGN.md §6 Filter tabs). */
	@media (hover: hover) {
		.segmented button:hover:not([aria-pressed='true']),
		.chip:hover:not([aria-pressed='true']) {
			color: var(--text-primary);
		}
	}

	/* Destructive-adjacent (it archives all of your settled jobs): outlined in the fail
	   tone at rest, as v41's row actions are, so it never reads as one more toggle. */
	.chip.danger {
		background: transparent;
		border-color: var(--fail-edge);
	}

	/* Stays transparent on hover: --fail on the generic --bg-3 hover is only 3.88:1. */
	.chip.danger:focus-visible {
		background: transparent;
		border-color: var(--fail);
		color: var(--fail);
	}

	@media (hover: hover) {
		.chip.danger:hover {
			background: transparent;
			border-color: var(--fail);
			color: var(--fail);
		}
	}

	/* v62 (F8): nothing to clear. The disabled look of a .btn (DESIGN.md §6): the edge drops to
	   --line and the text to --text-dim, and no hover answers it. */
	.chip.danger[aria-disabled='true'],
	.chip.danger[aria-disabled='true']:hover,
	.chip.danger[aria-disabled='true']:focus-visible {
		border-color: var(--line);
		color: var(--text-dim);
		cursor: default;
	}

	.chip.dir {
		padding: var(--space-1) var(--space-2);
		min-width: 2rem;
	}

	/* F32: a finger needs a 44px target; a mouse keeps the dense rows. */
	@media (pointer: coarse) {
		.chip,
		.segmented button,
		.sort select,
		.search {
			min-height: 2.75rem;
		}

		.chip.dir {
			min-width: 2.75rem;
		}
	}

	@media (max-width: 40em) {
		.queue-head,
		.controls {
			padding-left: var(--space-3);
			padding-right: var(--space-3);
		}

		/* Scope switch and search share the first line; the admin's scope wraps under. */
		.search {
			flex-basis: 10rem;
		}

		.sort {
			margin-left: 0;
		}
	}
</style>
