<script lang="ts">
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import type { Scope } from '$lib/stores/queue';

	let {
		isAdmin,
		allUsers,
		onAllUsersChange,
		countsByStatus
	}: {
		isAdmin: boolean;
		allUsers: boolean;
		onAllUsersChange: (value: boolean) => void;
		countsByStatus: Record<string, number>;
	} = $props();

	const { filters } = queue;

	let searchInput = $state($filters.q);
	let searchTimer: ReturnType<typeof setTimeout> | undefined;

	function onSearchInput(value: string) {
		searchInput = value;
		clearTimeout(searchTimer);
		searchTimer = setTimeout(() => queue.setFilters({ q: searchInput }), 300);
	}

	function setScope(scope: Scope) {
		if (scope === $filters.scope) return;
		queue.setFilters({ scope });
	}

	// Track-state filter chips have no live counts backing them (v20 judgment call: v18's
	// counts_by_status is job-rollup-shaped, and a global per-track-state count has no
	// endpoint -- see docs/GOTCHAS.md's v20 entry) -- shown without a count, unlike the
	// Jobs-scope state filter below.
	const TRACK_STATE_TOKENS: api.TrackState[] = [
		'pending',
		'queued',
		'downloading',
		'waiting',
		'lookup_failed',
		'completed',
		'skipped_duplicate',
		'cancelled'
	];
	const TRACK_STATE_LABEL: Record<api.TrackState, string> = {
		pending: 'pending',
		queued: 'queued',
		downloading: 'downloading',
		waiting: 'waiting',
		lookup_failed: 'not found',
		completed: 'completed',
		skipped_duplicate: 'duplicate',
		cancelled: 'cancelled'
	};

	function toggleStatusToken(token: string) {
		const current = $filters.status;
		const next = current.includes(token) ? current.filter((t) => t !== token) : [...current, token];
		queue.setFilters({ status: next });
	}

	function toggleStateToken(token: string) {
		const current = $filters.state;
		const next = current.includes(token) ? current.filter((t) => t !== token) : [...current, token];
		queue.setFilters({ state: next });
	}

	interface SortField {
		value: string;
		label: string;
	}

	const JOB_SORT_FIELDS: SortField[] = [
		{ value: 'created_at', label: 'created' },
		{ value: 'title', label: 'title' },
		{ value: 'status', label: 'status' },
		{ value: 'track_count', label: 'tracks' },
		{ value: 'next_retry', label: 'next retry' }
	];
	const TRACK_SORT_FIELDS: SortField[] = [
		{ value: 'created_at', label: 'created' },
		{ value: 'title', label: 'title' },
		{ value: 'state', label: 'state' }
	];
	let sortFields = $derived($filters.scope === 'jobs' ? JOB_SORT_FIELDS : TRACK_SORT_FIELDS);

	function onSort(field: string) {
		if ($filters.sort === field) {
			queue.setFilters({ dir: $filters.dir === 'asc' ? 'desc' : 'asc' });
		} else {
			queue.setFilters({ sort: field, dir: 'desc' });
		}
	}

	async function onClearLog() {
		await queue.archiveJobs({ allSettled: true });
	}
</script>

<section class="controls panel" aria-label="Queue controls">
	<div class="row">
		<div class="scope-toggle" role="group" aria-label="Search scope">
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
			class="search"
			placeholder={$filters.scope === 'jobs' ? 'search jobs…' : 'search tracks…'}
			value={searchInput}
			oninput={(e) => onSearchInput(e.currentTarget.value)}
			aria-label={$filters.scope === 'jobs' ? 'Search jobs' : 'Search tracks'}
		/>

		<div class="toggle-group" role="group" aria-label="Archived visibility">
			<button
				type="button"
				aria-pressed={$filters.includeArchived}
				onclick={() => queue.setFilters({ includeArchived: !$filters.includeArchived })}
			>
				show archived
			</button>
		</div>

		{#if $filters.scope === 'jobs'}
			<button type="button" class="clear-log" onclick={onClearLog}>clear log</button>
		{/if}

		{#if isAdmin}
			<div class="toggle-group" role="group" aria-label="Viewing scope">
				<button type="button" aria-pressed={!allUsers} onclick={() => onAllUsersChange(false)}>
					mine
				</button>
				<button type="button" aria-pressed={allUsers} onclick={() => onAllUsersChange(true)}>
					all users
				</button>
			</div>
		{/if}
	</div>

	<div class="row">
		<span class="label">sort</span>
		<div class="sort-group" role="group" aria-label="Sort by">
			{#each sortFields as field (field.value)}
				<button
					type="button"
					aria-pressed={$filters.sort === field.value}
					onclick={() => onSort(field.value)}
				>
					{field.label}
					{#if $filters.sort === field.value}
						<span aria-hidden="true">{$filters.dir === 'asc' ? '▲' : '▼'}</span>
					{/if}
				</button>
			{/each}
		</div>
	</div>

	<div class="row">
		<span class="label">state</span>
		{#if $filters.scope === 'jobs'}
			<div class="filters" role="group" aria-label="Filter by status">
				{#each api.STATUS_TOKENS as token (token)}
					<button
						type="button"
						aria-pressed={$filters.status.includes(token)}
						onclick={() => toggleStatusToken(token)}
					>
						{api.STATUS_LABEL[token]} <span class="mono">{countsByStatus[token] ?? 0}</span>
					</button>
				{/each}
			</div>
		{:else}
			<div class="filters" role="group" aria-label="Filter by track state">
				{#each TRACK_STATE_TOKENS as token (token)}
					<button
						type="button"
						aria-pressed={$filters.state.includes(token)}
						onclick={() => toggleStateToken(token)}
					>
						{TRACK_STATE_LABEL[token]}
					</button>
				{/each}
			</div>
		{/if}
	</div>
</section>

<style>
	.controls {
		padding: var(--space-3) var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	.search {
		flex: 1 1 12rem;
		min-width: 0;
		background: var(--bg-0);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-2) var(--space-3);
		color: var(--text-primary);
		font-family: var(--font-sans);
	}

	.search:focus-visible {
		border-color: var(--signal-dim);
	}

	/* Same neutral (non-amber) toggle-tab convention as +page.svelte's pre-existing
	   mine/all-users toggle (DESIGN.md §6, "Scope toggle") -- these switch what's being
	   viewed, not a live/active condition, so §2's amber-exclusivity rule keeps them off
	   --signal. */
	.scope-toggle,
	.toggle-group,
	.sort-group,
	.filters {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.scope-toggle button,
	.toggle-group button,
	.sort-group button,
	.filters button,
	.clear-log {
		background: var(--bg-2);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-1) var(--space-3);
		font-family: var(--font-mono);
		font-size: 0.75rem;
		color: var(--text-muted);
		cursor: pointer;
	}

	.scope-toggle button[aria-pressed='true'],
	.toggle-group button[aria-pressed='true'],
	.sort-group button[aria-pressed='true'],
	.filters button[aria-pressed='true'] {
		border-color: var(--line-bright);
		color: var(--text-primary);
	}

	.scope-toggle button:hover:not([aria-pressed='true']),
	.toggle-group button:hover:not([aria-pressed='true']),
	.sort-group button:hover:not([aria-pressed='true']),
	.filters button:hover:not([aria-pressed='true']),
	.clear-log:hover,
	.scope-toggle button:focus-visible,
	.toggle-group button:focus-visible,
	.sort-group button:focus-visible,
	.filters button:focus-visible,
	.clear-log:focus-visible {
		border-color: var(--waiting-dim);
	}

	.clear-log:hover,
	.clear-log:focus-visible {
		border-color: var(--fail-dim);
		color: var(--fail);
	}
</style>
