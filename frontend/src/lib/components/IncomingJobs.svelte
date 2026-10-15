<script lang="ts">
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import type { Job } from '$lib/api';

	/** `allUsers`: the admin's all-users scope, where rows can be someone else's -- they
	 * then carry their owner, and "try again" (which submits as *this* session) is offered
	 * only on the viewer's own. */
	let {
		jobs,
		allUsers = false,
		sessionEmail = ''
	}: { jobs: Job[]; allUsers?: boolean; sessionEmail?: string } = $props();

	const SOURCE_LABEL: Record<Job['source_type'], string> = {
		track: 'track',
		album: 'album',
		playlist: 'playlist',
		artist: 'artist',
		search: 'search'
	};

	let tuning = $derived(jobs.filter((j) => j.state === 'expanding'));
	// Newest first: the one just submitted is the one the user is looking for.
	let failed = $derived(
		jobs
			.filter((j) => j.state !== 'expanding')
			.sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
	);

	// v42 (F27): failed reads pile up (they stay until dismissed), and in the all-users
	// scope they're often days old. The newest always shows; older ones fold into one line.
	let showOlder = $state(false);
	let newestFailed = $derived(failed[0]);
	let olderFailed = $derived(failed.slice(1));

	let rowError = $state<Record<string, string>>({});
	let busy = $state<Record<string, boolean>>({});
	// Rows whose link was already submitted again: never offered twice, even if the dismiss
	// that follows fails and leaves the row up.
	let resubmitted = $state<Record<string, boolean>>({});

	function setError(jobId: string, message: string) {
		rowError = { ...rowError, [jobId]: message };
	}

	async function handleCancel(jobId: string) {
		try {
			await queue.cancelJob(jobId);
		} catch (err) {
			setError(jobId, err instanceof api.ApiError ? err.message : 'Could not cancel this job.');
		}
	}

	/** Submits the same link again as a new job, then dismisses the failed one -- what a
	 * user would do by pasting it again, in one step. */
	async function handleRetry(job: Job) {
		busy = { ...busy, [job.id]: true };
		try {
			queue.addJob(await api.createJob(job.source_url));
			resubmitted = { ...resubmitted, [job.id]: true };
		} catch (err) {
			setError(job.id, err instanceof api.ApiError ? err.message : 'Could not submit it again.');
			busy = { ...busy, [job.id]: false };
			return;
		}
		await handleCancel(job.id);
		busy = { ...busy, [job.id]: false };
	}

	function isOwn(job: Job): boolean {
		return !allUsers || job.owner_email === sessionEmail;
	}
</script>

{#snippet failedRow(job: Job)}
	<li class="row failed">
		<span class="dot fail" aria-hidden="true"></span>
		<span class="mono state">no signal — could not read this {SOURCE_LABEL[job.source_type]}</span>
		<span class="url mono" title={job.source_url}>{job.source_url}</span>
		{#if allUsers}
			<span class="owner mono" title={job.owner_email}
				>{api.displayName(job.owner_username, job.owner_email)}</span
			>
		{/if}
		{#if job.error}
			<span class="reason" title={job.error}>{job.error}</span>
		{/if}
		<span class="actions">
			{#if isOwn(job) && !resubmitted[job.id]}
				<button
					type="button"
					class="action"
					disabled={busy[job.id]}
					onclick={() => handleRetry(job)}>try again</button
				>
			{/if}
			<button type="button" class="action" onclick={() => handleCancel(job.id)}>dismiss</button>
		</span>
		{#if rowError[job.id]}
			<span class="error" role="alert">{rowError[job.id]}</span>
		{/if}
	</li>
{/snippet}

{#if jobs.length > 0}
	<section class="incoming panel" aria-labelledby="incoming-heading">
		<h2 id="incoming-heading" class="sr-only">Incoming submissions</h2>
		<ul class="rows" aria-label="Incoming submissions">
			{#each tuning as job (job.id)}
				<li class="row">
					<span class="dot" aria-hidden="true"></span>
					<span class="mono state">tuning in {SOURCE_LABEL[job.source_type]}</span>
					<span class="url mono" title={job.source_url}>{job.source_url}</span>
					{#if allUsers}
						<span class="owner mono" title={job.owner_email}
							>{api.displayName(job.owner_username, job.owner_email)}</span
						>
					{/if}
					<span class="actions">
						<button type="button" class="action" onclick={() => handleCancel(job.id)}>cancel</button
						>
					</span>
					{#if rowError[job.id]}
						<span class="error" role="alert">{rowError[job.id]}</span>
					{/if}
				</li>
			{/each}

			{#if newestFailed}
				{@render failedRow(newestFailed)}
			{/if}

			{#if olderFailed.length > 0}
				<li class="row summary">
					<span class="dot fail" aria-hidden="true"></span>
					<span class="summary-text"
						>{olderFailed.length} older link{olderFailed.length === 1 ? '' : 's'} couldn't be read</span
					>
					<span class="actions">
						<button
							type="button"
							class="action"
							aria-expanded={showOlder}
							onclick={() => (showOlder = !showOlder)}>{showOlder ? 'hide' : 'show'}</button
						>
					</span>
				</li>
				{#if showOlder}
					{#each olderFailed as job (job.id)}
						{@render failedRow(job)}
					{/each}
				{/if}
			{/if}
		</ul>
	</section>
{/if}

<style>
	.incoming {
		padding: var(--space-1) 0;
	}

	.rows {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.row {
		display: grid;
		grid-template-columns: 0.5rem auto minmax(0, 1fr) auto auto;
		align-items: center;
		column-gap: var(--space-3);
		row-gap: var(--space-1);
		padding: var(--space-2) var(--space-4);
		font-size: var(--fs-detail);
	}

	.row + .row {
		border-top: 1px solid var(--line);
	}

	.row.summary {
		grid-template-columns: 0.5rem minmax(0, 1fr) auto;
	}

	.row.summary .actions {
		grid-column: auto;
	}

	.summary-text {
		color: var(--fail);
	}

	.dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 50%;
		background: var(--signal);
		box-shadow: 0 0 6px 1px var(--signal-glow);
		animation: pulse 1.2s ease-in-out infinite;
	}

	.dot.fail {
		background: var(--fail);
		box-shadow: none;
		animation: none;
	}

	@media (prefers-reduced-motion: reduce) {
		.dot {
			animation: none;
		}
	}

	@keyframes pulse {
		0%,
		100% {
			opacity: 0.4;
		}
		50% {
			opacity: 1;
		}
	}

	.state {
		color: var(--text-muted);
		white-space: nowrap;
	}

	.row.failed .state {
		color: var(--fail);
	}

	.url {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--text-dim);
		font-size: var(--fs-meta);
	}

	.owner {
		max-width: 12rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--text-muted);
		font-size: var(--fs-meta);
	}

	/* The actions hold the first line's end; the reason and any error flow onto the lines
	   under it (they come before the actions in reading order). */
	.row:not(.summary) .actions {
		grid-row: 1;
		grid-column: 5;
	}

	.row:not(.summary):not(:has(.owner)) .actions {
		grid-column: 4 / -1;
	}

	.actions {
		display: flex;
		gap: var(--space-2);
		justify-content: flex-end;
	}

	/* The reason and any error sit under the state and link, on their columns. */
	.reason,
	.error {
		grid-column: 2 / -1;
		min-width: 0;
	}

	.reason {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--text-muted);
	}

	.error {
		color: var(--fail);
	}

	.action {
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

	.action:hover:not(:disabled),
	.action:focus-visible {
		background: var(--bg-3);
		color: var(--text-primary);
	}

	.action:disabled {
		opacity: 0.6;
		cursor: default;
	}

	@media (pointer: coarse) {
		.action {
			min-height: 2.75rem;
		}
	}

	/* Phone: state and link on the first line, the actions under them. */
	@media (max-width: 640px) {
		.row:not(.summary) {
			grid-template-columns: 0.5rem minmax(0, 1fr) auto;
		}

		.row .state {
			white-space: normal;
		}

		.row .url,
		.row .owner,
		.reason,
		.error {
			grid-column: 2 / -1;
		}

		.row:not(.summary) .actions,
		.row:not(.summary):not(:has(.owner)) .actions {
			grid-row: auto;
			grid-column: 2 / -1;
			justify-content: flex-start;
		}
	}
</style>
