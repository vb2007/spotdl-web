<script lang="ts">
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import type { Scope } from '$lib/stores/queue';
	import { SvelteSet } from 'svelte/reactivity';

	let {
		isAdmin,
		allUsers,
		onAllUsersChange,
		countsByStatus,
		countsByState,
		countText
	}: {
		isAdmin: boolean;
		allUsers: boolean;
		onAllUsersChange: (value: boolean) => void;
		countsByStatus: Record<string, number>;
		countsByState: Record<string, number>;
		/** The list's own size line ("7 of 7 jobs", "Loading…"), shown beside the heading. */
		countText: string;
	} = $props();

	const { filters } = queue;

	let searchTimer: ReturnType<typeof setTimeout> | undefined;

	// v42: the page's "clear search and filters" empties `q` from outside, so the box
	// follows the store -- but only when `q` itself changes: `storeQ` is a derived, which
	// only notifies on a new value, so typing (whose debounce writes the same value back)
	// and unrelated filter changes never overwrite the box mid-word.
	let storeQ = $derived($filters.q);
	let searchInput = $derived(storeQ);

	function onSearchInput(value: string) {
		searchInput = value;
		clearTimeout(searchTimer);
		searchTimer = setTimeout(() => queue.setFilters({ q: searchInput }), 300);
	}

	function setScope(scope: Scope) {
		if (scope === $filters.scope) return;
		queue.setFilters({ scope });
	}

	interface Chip {
		key: string;
		label: string;
		/** The filter tokens one chip stands for -- several for a merged chip. */
		tokens: string[];
	}

	// Track-state filter chips: v35 (g) gave them live counts (the tracks listing's
	// counts_by_state), the same way the Jobs-scope status filter has always had.
	const TRACK_CHIPS_ADMIN: Chip[] = [
		{ key: 'pending', label: 'pending', tokens: ['pending'] },
		{ key: 'queued', label: 'queued', tokens: ['queued'] },
		{ key: 'downloading', label: 'downloading', tokens: ['downloading'] },
		{ key: 'waiting', label: 'waiting', tokens: ['waiting'] },
		{ key: 'lookup_failed', label: 'not found', tokens: ['lookup_failed'] },
		{ key: 'completed', label: 'completed', tokens: ['completed'] },
		{ key: 'skipped_duplicate', label: 'duplicate', tokens: ['skipped_duplicate'] },
		{ key: 'cancelled', label: 'cancelled', tokens: ['cancelled'] }
	];
	// v42 (v39 outcome 3, owner's choice): pending/queued/downloading is the dispatcher's
	// distinction, not the listener's, so a non-admin gets one "in progress" chip for it.
	const TRACK_CHIPS_USER: Chip[] = [
		{ key: 'in-progress', label: 'in progress', tokens: ['pending', 'queued', 'downloading'] },
		...TRACK_CHIPS_ADMIN.slice(3)
	];
	const JOB_CHIPS: Chip[] = api.STATUS_TOKENS.map((token) => ({
		key: token,
		label: api.STATUS_LABEL[token],
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
	let touchedScope = $state<Scope>('jobs');

	// v42 (F11): a chip with nothing behind it is noise. It stays while pressed (so a filter
	// can always be switched off again) and once touched (above).
	let visibleChips = $derived(
		chips.filter(
			(c) =>
				chipCount(c) > 0 ||
				chipPressed(c) ||
				focusedChip === c.key ||
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
		label: string;
	}

	// "next retry" orders by the retry ladder's schedule: operator detail, admin only.
	let sortFields: SortField[] = $derived(
		$filters.scope === 'tracks'
			? [
					{ value: 'created_at', label: 'date added' },
					{ value: 'title', label: 'title' },
					{ value: 'state', label: 'state' }
				]
			: [
					{ value: 'created_at', label: 'date added' },
					{ value: 'title', label: 'title' },
					{ value: 'status', label: 'status' },
					{ value: 'track_count', label: 'track count' },
					...(isAdmin ? [{ value: 'next_retry', label: 'next retry' }] : [])
				]
	);

	// A different field starts descending, as the old sort buttons did.
	function onSortField(field: string) {
		if (field !== $filters.sort) queue.setFilters({ sort: field, dir: 'desc' });
	}

	function flipDir() {
		queue.setFilters({ dir: $filters.dir === 'asc' ? 'desc' : 'asc' });
	}

	async function onClearLog() {
		await queue.archiveJobs({ allSettled: true });
	}
</script>

<div class="queue-head">
	<h2 id="queue-heading" class="label">Queue</h2>
	<span class="count mono">{countText}</span>
	<div class="log-tools">
		<button
			type="button"
			class="chip"
			aria-pressed={$filters.includeArchived}
			onclick={() => queue.setFilters({ includeArchived: !$filters.includeArchived })}
		>
			show archived
		</button>
		{#if $filters.scope === 'jobs'}
			<!-- Archives this view's settled jobs. Its confirmation is v43's. -->
			<button type="button" class="chip danger" onclick={onClearLog}>clear log</button>
		{/if}
	</div>
</div>

<div class="controls" role="group" aria-label="Queue controls">
	<div class="find">
		<div class="segmented" role="group" aria-label="Search scope">
			<button
				type="button"
				aria-pressed={$filters.scope === 'jobs'}
				onclick={() => setScope('jobs')}
			>
				jobs
			</button>
			<button
				type="button"
				aria-pressed={$filters.scope === 'tracks'}
				onclick={() => setScope('tracks')}
			>
				tracks
			</button>
		</div>

		<input
			type="search"
			class="search well"
			placeholder={$filters.scope === 'jobs' ? 'search jobs…' : 'search tracks…'}
			value={searchInput}
			oninput={(e) => onSearchInput(e.currentTarget.value)}
			aria-label={$filters.scope === 'jobs' ? 'Search jobs' : 'Search tracks'}
		/>

		{#if isAdmin}
			<div class="segmented" role="group" aria-label="Viewing scope">
				<button type="button" aria-pressed={!allUsers} onclick={() => onAllUsersChange(false)}>
					mine
				</button>
				<button type="button" aria-pressed={allUsers} onclick={() => onAllUsersChange(true)}>
					all users
				</button>
			</div>
		{/if}
	</div>

	<div class="refine">
		{#if visibleChips.length > 0}
			<!-- F21: the label names what the counts count, so "waiting 1" (one job) isn't
			     read against a row's "8 waiting" (tracks). -->
			<div
				class="filters"
				role="group"
				aria-label={$filters.scope === 'jobs' ? 'Filter by status' : 'Filter by track state'}
			>
				<span class="label" aria-hidden="true">{$filters.scope === 'jobs' ? 'jobs' : 'tracks'}</span
				>
				{#each visibleChips as chip (chip.key)}
					<button
						type="button"
						class="chip"
						aria-pressed={chipPressed(chip)}
						onfocus={() => (focusedChip = chip.key)}
						onblur={() => (focusedChip = null)}
						onclick={() => toggleChip(chip)}
					>
						{chip.label}&nbsp;<span class="n mono">{chipCount(chip)}</span>
					</button>
				{/each}
			</div>
		{/if}

		<div class="sort">
			<label class="label" for="queue-sort">sort</label>
			<select
				id="queue-sort"
				class="well"
				value={$filters.sort}
				onchange={(e) => onSortField(e.currentTarget.value)}
			>
				{#each sortFields as field (field.value)}
					<option value={field.value}>{field.label}</option>
				{/each}
			</select>
			<button
				type="button"
				class="chip dir"
				aria-label={$filters.dir === 'asc'
					? 'Reverse sort order (now ascending)'
					: 'Reverse sort order (now descending)'}
				title={$filters.dir === 'asc' ? 'ascending' : 'descending'}
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

	.search {
		flex: 1 1 14rem;
		min-width: 0;
		padding: var(--space-2) var(--space-3);
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
		padding: var(--space-1) var(--space-2);
		color: var(--text-primary);
		font-family: var(--font-mono);
		font-size: var(--fs-meta);
	}

	/* A segmented switch: two options, one pressed, one shared edge. View scope, never
	   a live condition, so §2 keeps it off --signal. */
	.segmented {
		display: inline-flex;
		border: 1px solid var(--line-control);
		border-radius: 4px;
		overflow: hidden;
	}

	.segmented button {
		background: var(--bg-2);
		border: none;
		padding: var(--space-1) var(--space-3);
		font-family: var(--font-mono);
		font-size: var(--fs-meta);
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
		padding: var(--space-1) var(--space-3);
		font-family: var(--font-mono);
		font-size: var(--fs-meta);
		color: var(--text-muted);
		cursor: pointer;
		white-space: nowrap;
	}

	.chip .n {
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

	.chip:hover .n {
		color: var(--text-muted);
	}

	/* Hover lifts only the text: the fill and floor line stay the pressed state's. */
	.segmented button:hover:not([aria-pressed='true']),
	.chip:hover:not([aria-pressed='true']) {
		color: var(--text-primary);
	}

	/* Destructive-adjacent (it archives every settled job in view): outlined in the fail
	   tone at rest, as v41's row actions are, so it never reads as one more toggle. */
	.chip.danger {
		background: transparent;
		border-color: var(--fail-edge);
	}

	/* Stays transparent on hover: --fail on the generic --bg-3 hover is only 3.88:1. */
	.chip.danger:hover,
	.chip.danger:focus-visible {
		background: transparent;
		border-color: var(--fail);
		color: var(--fail);
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

	@media (max-width: 640px) {
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
