<script lang="ts">
	import { SvelteMap } from 'svelte/reactivity';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import JobTrackList from '$lib/components/JobTrackList.svelte';
	import type { Job, JobLifecycle } from '$lib/api';

	let { job, allUsers }: { job: Job; allUsers: boolean } = $props();

	const { expanded } = queue;
	let isOpen = $derived(job.id in $expanded);

	// In-flight controls (cancel/bump/priority) only make sense while the job still has
	// somewhere to go; showing them on a settled/failed/cancelled row invites exactly the
	// backend footgun `cancel_job` has (it unconditionally sets `Job.state = CANCELLED`
	// regardless of track states) -- never calling cancel on those lifecycles from the UI
	// avoids ever hitting it, without needing a backend change out of this version's scope.
	const IN_FLIGHT_LIFECYCLES = new Set<JobLifecycle>(['expanding', 'active', 'waiting']);
	const ARCHIVABLE_LIFECYCLES = new Set<JobLifecycle>(['settled', 'failed', 'cancelled']);

	const JOB_STATUS_COND: Record<string, string> = {
		expanding: 'cond-live',
		active: 'cond-live',
		waiting: 'cond-waiting',
		'settled:complete': 'cond-settled',
		'settled:partial': 'cond-fail',
		cancelled: 'cond-idle',
		failed: 'cond-fail'
	};

	let statusToken = $derived(api.statusKey(job.status));
	let badgeLabel = $derived(api.STATUS_LABEL[statusToken] ?? statusToken);
	let cond = $derived(JOB_STATUS_COND[statusToken] ?? 'cond-idle');
	let showInFlight = $derived(IN_FLIGHT_LIFECYCLES.has(job.status.lifecycle));
	let showArchive = $derived(
		job.archived_at === null && ARCHIVABLE_LIFECYCLES.has(job.status.lifecycle)
	);

	interface Segment {
		cond: string;
		n: number;
	}

	let segments = $derived.by((): Segment[] => {
		const c = job.track_counts;
		const active = (c.pending ?? 0) + (c.queued ?? 0) + (c.downloading ?? 0);
		const settled = (c.completed ?? 0) + (c.skipped_duplicate ?? 0);
		const waiting = c.waiting ?? 0;
		const fail = c.lookup_failed ?? 0;
		const idle = c.cancelled ?? 0;
		return [
			{ cond: 'cond-live', n: active },
			{ cond: 'cond-waiting', n: waiting },
			{ cond: 'cond-settled', n: settled },
			{ cond: 'cond-fail', n: fail },
			{ cond: 'cond-idle', n: idle }
		].filter((s) => s.n > 0);
	});
	let totalTracks = $derived(segments.reduce((sum, s) => sum + s.n, 0));

	let breakdown = $derived.by((): string => {
		const c = job.track_counts;
		const active = (c.pending ?? 0) + (c.queued ?? 0) + (c.downloading ?? 0);
		const settled = (c.completed ?? 0) + (c.skipped_duplicate ?? 0);
		const waiting = c.waiting ?? 0;
		const fail = c.lookup_failed ?? 0;
		const idle = c.cancelled ?? 0;
		const parts: string[] = [];
		if (settled) parts.push(`${settled.toLocaleString()} done`);
		if (active) parts.push(`${active.toLocaleString()} active`);
		if (waiting) parts.push(`${waiting.toLocaleString()} waiting`);
		if (fail) parts.push(`${fail.toLocaleString()} not found`);
		if (idle) parts.push(`${idle.toLocaleString()} cancelled`);
		return parts.length ? parts.join(' · ') : '—';
	});

	const notice = new SvelteMap<string, string>();
	function showNotice(text: string) {
		notice.set(job.id, text);
		setTimeout(() => {
			if (notice.get(job.id) === text) notice.delete(job.id);
		}, 4000);
	}

	async function handleCancel() {
		try {
			await queue.cancelJob(job.id);
		} catch (err) {
			showNotice(err instanceof api.ApiError ? err.message : 'Could not cancel this job.');
		}
	}

	async function handleBump() {
		try {
			await queue.bumpJob(job.id);
			showNotice('bumped to front of the queue');
		} catch (err) {
			showNotice(err instanceof api.ApiError ? err.message : 'Could not bump this job.');
		}
	}

	async function handlePriority(value: string) {
		const priority = Number.parseInt(value, 10);
		if (Number.isNaN(priority)) return;
		try {
			await queue.setJobPriority(job.id, priority);
		} catch (err) {
			showNotice(err instanceof api.ApiError ? err.message : 'Could not set priority.');
		}
	}

	async function handleArchive() {
		try {
			await queue.archiveJobs({ jobIds: [job.id] });
		} catch (err) {
			showNotice(err instanceof api.ApiError ? err.message : 'Could not archive this job.');
		}
	}

	async function handleUnarchive() {
		try {
			await queue.unarchiveJobs([job.id]);
		} catch (err) {
			showNotice(err instanceof api.ApiError ? err.message : 'Could not unarchive this job.');
		}
	}
</script>

<li class="job">
	<div class="row">
		<button
			type="button"
			class="toggle"
			aria-expanded={isOpen}
			aria-label="{isOpen ? 'Collapse' : 'Expand'} tracks for {job.title}"
			onclick={() => queue.toggleExpand(job.id)}
		>
			<span class="chevron" aria-hidden="true">{isOpen ? '▾' : '▸'}</span>
			<span class="badge {cond} mono">{badgeLabel}</span>
			<span class="title">{job.title}</span>
			<span class="source-type mono">{job.source_type}</span>
			{#if allUsers}
				<span class="owner mono" title={job.owner_email}
					>{api.displayName(job.owner_username, job.owner_email)}</span
				>
			{/if}
		</button>

		{#if totalTracks > 0}
			<div class="bar" role="img" aria-label="Track progress: {breakdown}">
				{#each segments as seg, i (i)}
					<span
						class="seg {seg.cond}"
						style:flex-grow={seg.n}
						style:flex-basis={`${(seg.n / totalTracks) * 100}%`}
					></span>
				{/each}
			</div>
		{/if}
		<span class="breakdown mono">{breakdown}</span>

		<div class="row-actions">
			{#if showInFlight}
				<label class="priority mono">
					priority
					<input
						type="number"
						class="priority-input"
						value={job.priority}
						aria-label="Job priority"
						onchange={(e) => handlePriority(e.currentTarget.value)}
					/>
				</label>
				<button type="button" class="action" onclick={handleBump}>bump</button>
				<button type="button" class="action danger" onclick={handleCancel}>cancel</button>
			{/if}
			{#if showArchive}
				<button type="button" class="action" onclick={handleArchive}>archive</button>
			{/if}
			{#if job.archived_at !== null}
				<span class="archived-tag mono">archived</span>
				<button type="button" class="action" onclick={handleUnarchive}>unarchive</button>
			{/if}
		</div>
	</div>

	{#if notice.has(job.id)}
		<p class="notice mono" role="status">{notice.get(job.id)}</p>
	{/if}

	{#if isOpen}
		<JobTrackList jobId={job.id} />
	{/if}
</li>

<style>
	.job {
		border-bottom: 1px solid var(--line);
	}

	.job:last-child {
		border-bottom: none;
	}

	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
	}

	.toggle {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-width: 0;
		flex: 2 1 16rem;
		background: transparent;
		border: none;
		padding: 0;
		text-align: left;
		cursor: pointer;
		color: inherit;
	}

	.chevron {
		flex-shrink: 0;
		color: var(--text-dim);
		width: 1em;
	}

	.badge {
		flex-shrink: 0;
		padding: 0.125rem var(--space-2);
		border: 1px solid var(--line);
		border-radius: 3px;
		font-size: 0.6875rem;
		letter-spacing: 0.04em;
	}

	.title {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-weight: 500;
	}

	.source-type {
		flex-shrink: 0;
		color: var(--text-dim);
		font-size: 0.6875rem;
		text-transform: uppercase;
	}

	.owner {
		flex-shrink: 0;
		color: var(--text-muted);
		font-size: 0.75rem;
	}

	.bar {
		flex: 1 1 8rem;
		display: flex;
		height: 0.5rem;
		border-radius: 3px;
		overflow: hidden;
		background: var(--bg-0);
		border: 1px solid var(--line);
	}

	.seg.cond-live {
		background: var(--signal);
	}
	.seg.cond-waiting {
		background: var(--waiting);
	}
	.seg.cond-settled {
		background: var(--settled);
	}
	.seg.cond-fail {
		background: var(--fail);
	}
	.seg.cond-idle {
		background: var(--line-bright);
	}

	.breakdown {
		flex-shrink: 0;
		color: var(--text-muted);
		font-size: 0.75rem;
		white-space: nowrap;
	}

	.row-actions {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.priority {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		font-size: 0.6875rem;
		color: var(--text-dim);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.priority-input {
		width: 3.5rem;
		background: var(--bg-0);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-1) var(--space-2);
		color: var(--text-primary);
		font-family: var(--font-mono);
		font-size: 0.8125rem;
	}

	.priority-input:focus-visible {
		border-color: var(--signal-dim);
	}

	.action {
		background: var(--bg-2);
		border: 1px solid var(--line);
		border-radius: 4px;
		padding: var(--space-1) var(--space-3);
		font-size: 0.75rem;
		color: var(--text-muted);
		cursor: pointer;
		white-space: nowrap;
	}

	.action:hover,
	.action:focus-visible {
		border-color: var(--waiting);
		color: var(--text-primary);
	}

	.action.danger:hover,
	.action.danger:focus-visible {
		border-color: var(--fail);
		color: var(--fail);
	}

	.archived-tag {
		font-size: 0.6875rem;
		color: var(--text-dim);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.notice {
		margin: 0;
		padding: 0 var(--space-4) var(--space-2);
		color: var(--waiting);
		font-size: 0.8125rem;
	}

	/* Same one-cell-per-line mobile rule as TrackRow/QueueTable (DESIGN.md §6) -- a
	   flex-wrap row already reflows reasonably, but stacking explicitly removes any
	   ambiguity at the 390px width real screenshots are checked against.
	   `flex-wrap: nowrap` here is load-bearing, not a no-op override of the base rule's
	   `flex-wrap: wrap` (§.row above): a title-less job's title falls back to its raw
	   source_url (v18), a single long unbroken string with no wrap opportunity of its
	   own. With the row still multi-line-capable, `align-items: stretch` stretches each
	   child only within its own flex *line*, and a wrapping-capable container sizes each
	   line's cross axis (width, since direction is now column) to fit that line's
	   content instead of the full row width -- so `.toggle` was measured stretching to
	   its own unshrunk content width (up to 517px) rather than the row's real ~358px, a
	   real 390px screenshot overflow caught before this fix, gone after it. Forcing a
	   single nowrap line restores the intended behavior: `.toggle` stretches to the
	   row's actual width, and only then does `.title`'s own min-width:0/overflow:hidden/
	   text-overflow:ellipsis get to do its job and shrink+ellipsize the long string. */
	@media (max-width: 640px) {
		.row {
			flex-direction: column;
			flex-wrap: nowrap;
			align-items: stretch;
		}

		.bar {
			order: 3;
			flex-basis: 100%;
		}

		.breakdown {
			order: 4;
		}

		.row-actions {
			order: 5;
			flex-basis: 100%;
		}
	}
</style>
