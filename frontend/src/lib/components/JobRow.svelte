<script lang="ts">
	import { SvelteMap } from 'svelte/reactivity';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import JobTrackList from '$lib/components/JobTrackList.svelte';
	import type { Job, JobLifecycle } from '$lib/api';

	let { job, allUsers, isAdmin }: { job: Job; allUsers: boolean; isAdmin: boolean } = $props();

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
	// v42 (F28): red is for a real gap. A job that is partial only because its owner
	// cancelled tracks has nothing missing they didn't choose, so it reads muted.
	let cond = $derived(
		statusToken === 'settled:partial' && !(job.track_counts.lookup_failed ?? 0)
			? 'cond-idle'
			: (JOB_STATUS_COND[statusToken] ?? 'cond-idle')
	);
	// v42 (F28): with no tracks read yet the backend falls back to the link itself; show it
	// as the address it is, not as a bold title.
	let titleIsUrl = $derived(job.title === job.source_url);
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
	// v41: the visible copy wraps only between parts ("120 done · 3 waiting"), never
	// inside one, so every count stays readable in the fixed progress column.
	let breakdownVisible = $derived(
		breakdown
			.split(' · ')
			.map((part) => part.replace(/ /g, '\u00a0'))
			.join(' · ')
	);

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

<li class="job" aria-labelledby="job-title-{job.id}">
	<div class="row">
		<!-- v41 (F16): no aria-label, so the button's name is what it shows (status, title,
		     type, owner; WCAG 2.5.3), and aria-controls ties it to the track list (F29). -->
		<button
			type="button"
			class="toggle"
			aria-expanded={isOpen}
			aria-controls="job-tracks-{job.id}"
			onclick={() => queue.toggleExpand(job.id)}
		>
			<span class="chevron" aria-hidden="true"></span>
			<span class="badge-cell"><span class="badge {cond} mono">{badgeLabel}</span></span>
			<span class="title" class:address={titleIsUrl} id="job-title-{job.id}" title={job.title}
				>{job.title}</span
			>
			<span class="tags">
				<span class="source-type mono">{job.source_type}</span>
				{#if allUsers}
					<span class="owner mono" title={job.owner_email}
						>{api.displayName(job.owner_username, job.owner_email)}</span
					>
				{/if}
			</span>
		</button>

		<div class="progress">
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
			<!-- v42 (F28): one track's count only repeats its badge and bar; the bar's name keeps
			     it. Not for a partial job: "done — partial" doesn't say whether the track was not
			     found or cancelled, and the bar's colour alone mustn't carry that (WCAG 1.4.1). -->
			{#if totalTracks !== 1 || statusToken === 'settled:partial'}
				<span class="breakdown mono">{breakdownVisible}</span>
			{/if}
		</div>

		<div class="row-actions">
			{#if showInFlight}
				<label class="priority mono">
					priority
					<input
						type="number"
						class="priority-input"
						value={job.priority}
						aria-label="priority of {job.title}"
						onchange={(e) => handlePriority(e.currentTarget.value)}
					/>
				</label>
				<button
					type="button"
					class="action"
					aria-label="bump {job.title} to the front"
					onclick={handleBump}>bump</button
				>
				<button
					type="button"
					class="action danger"
					aria-label="cancel {job.title}"
					onclick={handleCancel}>cancel</button
				>
			{/if}
			{#if showArchive}
				<button
					type="button"
					class="action"
					aria-label="archive {job.title}"
					onclick={handleArchive}>archive</button
				>
			{/if}
			{#if job.archived_at !== null}
				<span class="archived-tag mono">archived</span>
				<button
					type="button"
					class="action"
					aria-label="unarchive {job.title}"
					onclick={handleUnarchive}>unarchive</button
				>
			{/if}
		</div>
	</div>

	<p class="notice mono" role="status">{notice.get(job.id) ?? ''}</p>

	{#if isOpen}
		<JobTrackList jobId={job.id} {isAdmin} total={totalTracks} />
	{/if}
</li>

<style>
	.job {
		border-bottom: 1px solid var(--line);
	}

	.job:last-child {
		border-bottom: none;
	}

	/* v41: the shared row grid (app.css "Row grid") -- chevron, badge, title, progress,
	   actions. The fixed-width progress column sits last, at the row's right edge, so every
	   job's bar lines up while the title takes whatever its actions don't use; a nested
	   track's state and title land under this row's badge and title (F02). */
	.row {
		display: grid;
		grid-template-columns:
			var(--col-lead) var(--col-state) minmax(0, 1fr) auto
			var(--col-progress);
		column-gap: var(--row-gap);
		row-gap: var(--space-2);
		align-items: center;
		padding: var(--space-3) var(--row-pad-x);
	}

	/* Spans the row's first three columns with the same tokens and gap, so its chevron,
	   badge and title sit exactly on them; the title and its tags share the third. */
	.toggle {
		grid-column: 1 / 4;
		display: grid;
		grid-template-columns: var(--col-lead) var(--col-state) minmax(0, max-content) minmax(0, auto);
		column-gap: var(--row-gap);
		align-items: center;
		min-width: 0;
		background: transparent;
		border: none;
		padding: 0;
		text-align: left;
		cursor: pointer;
		color: inherit;
	}

	.chevron {
		justify-self: center;
		width: 0.45rem;
		height: 0.45rem;
		border-right: 1.5px solid var(--text-muted);
		border-bottom: 1.5px solid var(--text-muted);
		transform: translateX(-20%) rotate(-45deg);
		transition: transform var(--dur-fast) var(--ease-signal);
	}

	.toggle[aria-expanded='true'] .chevron {
		transform: translateY(-20%) rotate(45deg);
	}

	.badge-cell {
		min-width: 0;
	}

	.badge {
		display: inline-block;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		vertical-align: middle;
		padding: 0.125rem var(--space-2);
		border: 1px solid var(--line);
		border-radius: 3px;
		font-size: 0.6875rem;
		letter-spacing: 0.04em;
	}

	/* Title and tags share whatever the toggle has left, so a long owner (an email, when
	   there's no username) ellipsizes instead of crushing the title to nothing. */
	.tags {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		min-width: 0;
		overflow: hidden;
		margin-left: calc(var(--space-2) - var(--row-gap));
	}

	.title {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-weight: 500;
	}

	.title.address {
		font-family: var(--font-mono);
		font-size: var(--fs-meta);
		font-weight: var(--fw-regular);
		color: var(--text-muted);
	}

	.source-type {
		flex-shrink: 0;
		color: var(--text-muted);
		font-size: 0.6875rem;
		text-transform: uppercase;
	}

	.owner {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--text-muted);
		font-size: 0.75rem;
	}

	.progress {
		grid-column: 5;
		grid-row: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.bar {
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
		color: var(--text-muted);
		font-size: 0.75rem;
	}

	.row-actions {
		grid-column: 4;
		grid-row: 1;
		display: flex;
		align-items: center;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.priority {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		font-size: 0.6875rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.priority-input {
		width: 3.5rem;
		background: var(--bg-0);
		border: 1px solid var(--line-control);
		border-radius: 4px;
		padding: var(--space-1) var(--space-2);
		color: var(--text-primary);
		font-family: var(--font-mono);
		font-size: 0.8125rem;
	}

	.action {
		background: var(--bg-2);
		border: 1px solid var(--line-control);
		border-radius: 4px;
		padding: var(--space-1) var(--space-3);
		font-family: var(--font-mono);
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

	/* Destructive: outlined in the fail tone at rest, full red only when about to be used
	   -- the same treatment as TrackRow's "cancel track". */
	.action.danger {
		background: transparent;
		border-color: var(--fail-edge);
	}

	.action.danger:hover,
	.action.danger:focus-visible {
		border-color: var(--fail);
		color: var(--fail);
	}

	.archived-tag {
		font-size: 0.6875rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.notice {
		margin: 0;
		padding: 0 var(--row-pad-x) var(--space-2) calc(var(--row-pad-x) + var(--row-nest));
		color: var(--waiting);
		font-size: 0.8125rem;
	}

	/* Empty, it stays in the accessibility tree (a status region inserted together with
	   its text is often not announced) but takes no room. */
	.notice:empty {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
	}

	/* Tablet: the actions drop to a second line under the title instead of squeezing it
	   (F37, for this row; v42 owns the page breakpoint). */
	@media (max-width: 960px) {
		.row {
			grid-template-columns: var(--col-lead) var(--col-state) minmax(0, 1fr) 10rem;
		}

		.progress {
			grid-column: 4;
		}

		.row-actions {
			grid-column: 3 / -1;
			grid-row: 2;
			justify-content: flex-start;
		}

		.row-actions:empty {
			display: none;
		}
	}

	/* Phone (v39.1 F01, redesigned in v41): one line for chevron, badge and title, then
	   the bar with its breakdown, then the actions, all hanging off the same second
	   column the nested tracks indent to. No flex-basis sizes a height here any more:
	   the stack is grid rows, each as tall as its content. */
	/* v42 (F32): a finger needs a 44px target; a mouse keeps the dense row. */
	@media (pointer: coarse) {
		.toggle,
		.action,
		.priority-input {
			min-height: 2.75rem;
		}
	}

	@media (max-width: 640px) {
		.row {
			grid-template-columns: var(--col-lead) minmax(0, 1fr);
		}

		/* Badge and tags on the first line, the whole title width on the second. */
		.toggle {
			grid-column: 1 / -1;
			grid-template-columns: var(--col-lead) auto minmax(0, 1fr);
			grid-template-areas:
				'chevron badge tags'
				'. title title';
		}

		.chevron {
			grid-area: chevron;
		}

		.badge-cell {
			grid-area: badge;
		}

		.tags {
			grid-area: tags;
			margin-left: 0;
			min-width: 0;
			overflow: hidden;
		}

		.title {
			grid-area: title;
		}

		.progress,
		.row-actions {
			grid-column: 2;
			grid-row: auto;
		}
	}
</style>
