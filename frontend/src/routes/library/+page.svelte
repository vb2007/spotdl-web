<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';

	let run = $state<api.LibrarySortRun | null>(null);
	let starting = $state(false);
	let error = $state('');

	let running = $derived(run?.state === 'running');
	let percent = $derived(
		run !== null && run.total > 0 ? Math.round((run.processed / run.total) * 100) : 0
	);

	async function loadStatus() {
		run = await api.getLibrarySortStatus();
	}

	async function onStart() {
		starting = true;
		error = '';
		try {
			run = await api.startLibrarySort();
		} catch (err) {
			error = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		} finally {
			starting = false;
		}
	}

	// No admin-gating client-side (same convention as /settings) -- the backend's
	// require_admin is the real enforcement; a non-admin here just sees the 403 surface
	// as an error message rather than a working page.
	let source: EventSource | undefined;

	onMount(() => {
		loadStatus().catch((err) => {
			error = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		});

		source = api.createEventSource();
		source.onmessage = (event) => {
			const data = JSON.parse(event.data) as api.StreamEvent;
			if (data.type !== 'library.progress') return;
			run = {
				state: data.done ? 'idle' : 'running',
				started_at: run?.started_at ?? null,
				finished_at: data.done ? new Date().toISOString() : null,
				total: data.total,
				processed: data.processed,
				moved: data.moved,
				skipped_present: data.skipped_present,
				quarantined: data.quarantined,
				errors: run?.errors ?? []
			};
			// The SSE payload doesn't carry the final error list -- re-fetch the full
			// report once the sweep reports done, rather than trying to accumulate
			// per-file errors client-side from a stream that was designed as a light
			// progress signal, not a log.
			if (data.done) {
				loadStatus().catch(() => {
					// A transient poll failure here isn't worth surfacing -- the counts
					// already rendered from the event are still accurate.
				});
			}
		};

		return () => {
			source?.close();
		};
	});
</script>

<svelte:head>
	<title>spotdl-web — library</title>
</svelte:head>

<main class="stage">
	<header>
		<div class="ident">
			<span class="label">SPOTDL // WEB</span>
			<span class="label dim">LIBRARY SORT &amp; MOVE</span>
		</div>
		<a class="back mono" href={resolve('/settings')}>‹ back to settings</a>
	</header>

	<section class="panel">
		<p class="hint mono">
			Sorts every downloaded file not already in the library into the real music library — target
			directory, folder template, and the quarantine toggle live on
			<a class="inline-link" href={resolve('/settings')}>settings</a>.
		</p>

		<button type="button" class="start" disabled={starting || running} onclick={onStart}>
			{running ? 'SWEEP RUNNING…' : starting ? 'STARTING…' : 'START SWEEP'}
		</button>
		<p class="form-error mono" role="alert">{error}</p>

		{#if run !== null}
			<div class="progress-block">
				{#if running || run.total > 0}
					<div
						class="progress-bar"
						role="progressbar"
						aria-valuenow={percent}
						aria-valuemin={0}
						aria-valuemax={100}
					>
						<div class="progress-fill" style:width="{percent}%"></div>
					</div>
					<p class="hint mono">{run.processed} / {run.total} ({percent}%)</p>
				{/if}

				{#if !running && run.finished_at !== null}
					<div class="report">
						<h2 class="label">Last sweep</h2>
						<ul class="report-counts mono">
							<li><span class="count">{run.moved}</span> moved</li>
							<li><span class="count">{run.skipped_present}</span> already present</li>
							<li><span class="count">{run.quarantined}</span> quarantined</li>
							<li>
								<span class="count" class:fail={run.errors.length > 0}>{run.errors.length}</span> errors
							</li>
						</ul>
						{#if run.errors.length > 0}
							<ul class="error-list mono">
								{#each run.errors as e, i (i)}
									<li><span class="file">{e.file}</span> — {e.error}</li>
								{/each}
							</ul>
						{/if}
					</div>
				{/if}
			</div>
		{/if}
	</section>
</main>

<style>
	.stage {
		max-width: 64rem;
		margin: 0 auto;
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}

	header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-4);
		flex-wrap: wrap;
	}

	.ident {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.ident .dim {
		color: var(--text-dim);
	}

	.back {
		color: var(--text-muted);
		font-size: 0.8125rem;
		text-decoration: none;
	}

	.back:hover,
	.back:focus-visible {
		color: var(--signal-dim);
	}

	.panel {
		padding: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.hint {
		margin: 0;
		color: var(--text-dim);
		font-size: 0.75rem;
	}

	.inline-link {
		color: var(--signal-dim);
	}

	.inline-link:hover,
	.inline-link:focus-visible {
		color: var(--signal);
	}

	.start {
		align-self: start;
		background: var(--bg-2);
		border: 1px solid var(--line-bright);
		border-radius: 4px;
		padding: var(--space-3) var(--space-4);
		font-family: var(--font-mono);
		font-weight: 600;
		letter-spacing: 0.06em;
		cursor: pointer;
	}

	.start:hover:not(:disabled),
	.start:focus-visible {
		border-color: var(--signal);
		background: var(--bg-3);
	}

	.start:disabled {
		opacity: 0.6;
		cursor: default;
	}

	.form-error {
		min-height: 1rem;
		margin: 0;
		color: var(--fail);
		font-size: 0.8125rem;
	}

	.progress-block {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.progress-bar {
		height: 0.5rem;
		background: var(--bg-0);
		border: 1px solid var(--line);
		border-radius: 4px;
		overflow: hidden;
	}

	.progress-fill {
		height: 100%;
		background: var(--signal-dim);
		transition: width 0.3s ease;
	}

	.report {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding-top: var(--space-2);
		border-top: 1px solid var(--line);
	}

	.report-counts {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-4);
		font-size: 0.8125rem;
		color: var(--text-muted);
	}

	.count {
		color: var(--text-primary);
		font-weight: 600;
	}

	.count.fail {
		color: var(--fail);
	}

	.error-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-size: 0.75rem;
		color: var(--fail);
		max-height: 16rem;
		overflow-y: auto;
	}

	.file {
		color: var(--text-primary);
	}
</style>
