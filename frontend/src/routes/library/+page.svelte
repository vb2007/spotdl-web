<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import { confirmAction } from '$lib/stores/confirm';
	import SubpageHeader from '$lib/components/SubpageHeader.svelte';
	import AdminOnlyNotice from '$lib/components/AdminOnlyNotice.svelte';

	let { data } = $props();
	const isAdmin = $derived(data.session?.is_admin ?? false);

	let run = $state<api.LibrarySortRun | null>(null);
	let starting = $state(false);
	let error = $state('');
	let loadError = $state('');
	// v43 (F20): the stream can drop mid-sweep; say so instead of freezing the counts.
	let linkDown = $state(false);

	const running = $derived(run?.state === 'running');
	const percent = $derived(
		run !== null && run.total > 0 ? Math.round((run.processed / run.total) * 100) : 0
	);
	// The progress event carries no error count, but every processed file is filed one of
	// three ways or left in place with an error, so the difference is the errors so far.
	const errorsSoFar = $derived(
		run === null
			? 0
			: Math.max(0, run.processed - run.moved - run.skipped_present - run.quarantined)
	);
	// v43 (F20, F34a's display half): the backend can record one file's error twice; the
	// report lists each (file, reason) once.
	const errorRows = $derived(
		(run?.errors ?? []).filter(
			(e, i, all) => all.findIndex((o) => o.file === e.file && o.error === e.error) === i
		)
	);
	const errorCount = $derived(running ? errorsSoFar : errorRows.length);

	function formatWhen(iso: string): string {
		return new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
	}

	function formatTook(startIso: string | null, endIso: string | null): string | null {
		if (!startIso || !endIso) return null;
		const seconds = Math.max(0, Math.round((Date.parse(endIso) - Date.parse(startIso)) / 1000));
		if (seconds < 60) return `${seconds}s`;
		const minutes = Math.floor(seconds / 60);
		return minutes < 60
			? `${minutes}m ${seconds % 60}s`
			: `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
	}

	async function loadStatus() {
		run = await api.getLibrarySortStatus();
		loadError = '';
	}

	// v43 (F08): a sweep moves real files and archives jobs for every user, so it asks.
	async function onStart() {
		let target: string | undefined;
		try {
			target = (await api.getLibrarySettings()).library_target_dir;
		} catch {
			// The question still stands without the folder in it.
		}
		const confirmed = await confirmAction({
			title: 'Start a library sweep?',
			subject: target,
			body:
				'Every finished download not yet in the library moves there. Settled jobs whose ' +
				'tracks move are archived, for every user. Nothing already in the library is changed ' +
				'or deleted.',
			confirmLabel: 'start sweep',
			cancelLabel: 'not now'
		});
		if (!confirmed) return;
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

	let source: EventSource | undefined;
	let retryTimer: ReturnType<typeof setTimeout> | undefined;
	let retryDelay = 2000;
	let unmounted = false;

	function onProgress(event: MessageEvent) {
		const payload = JSON.parse(event.data) as api.StreamEvent;
		if (payload.type !== 'library.progress') return;
		run = {
			state: payload.done ? 'idle' : 'running',
			started_at: run?.started_at ?? null,
			finished_at: payload.done ? payload.ts : null,
			total: payload.total,
			processed: payload.processed,
			moved: payload.moved,
			skipped_present: payload.skipped_present,
			quarantined: payload.quarantined,
			errors: run?.errors ?? []
		};
		// The SSE payload doesn't carry the final error list -- re-fetch the full report
		// once the sweep reports done, rather than trying to accumulate per-file errors
		// client-side from a stream that was designed as a light progress signal, not a log.
		if (payload.done) {
			loadStatus().catch(() => {
				// A transient failure here isn't worth surfacing -- the counts already
				// rendered from the event are still accurate.
			});
		}
	}

	// Same reason as `/`'s stream (v12): a 502 or 401 closes an EventSource for good, so a
	// closed one is reopened here, with a capped backoff, and the status re-read on open.
	function connect() {
		source = api.createEventSource();
		source.onmessage = onProgress;
		source.onopen = () => {
			retryDelay = 2000;
			if (linkDown) {
				linkDown = false;
				loadStatus().catch(() => {});
			}
		};
		source.onerror = () => {
			linkDown = true;
			if (source?.readyState !== EventSource.CLOSED || unmounted) return;
			retryTimer = setTimeout(connect, retryDelay);
			retryDelay = Math.min(retryDelay * 2, 30000);
		};
	}

	onMount(() => {
		// A non-admin gets the notice: no status request and no stream (F17).
		if (!isAdmin) return;
		loadStatus().catch((err) => {
			loadError = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		});
		connect();
		return () => {
			unmounted = true;
			clearTimeout(retryTimer);
			source?.close();
		};
	});
</script>

<svelte:head>
	<title>spotdl-web — library</title>
</svelte:head>

<div class="stage">
	<SubpageHeader current="library" {isAdmin} />

	<main id="main" class="main">
		<h1 class="page-title">Library sort &amp; move</h1>
		{#if !isAdmin}
			<AdminOnlyNotice what="The music library" />
		{:else}
			<section class="panel sweep" aria-labelledby="sweep-heading">
				<header class="head">
					<div class="head-text">
						<h2 id="sweep-heading" class="label">Sweep</h2>
						<p class="hint">
							Moves finished downloads into the music library, one folder per album. The folder, the
							template and what happens to duplicates are set in
							<a href={resolve('/settings')}>settings</a>.
						</p>
					</div>
					<button type="button" class="btn" disabled={starting || running} onclick={onStart}>
						{running ? 'sweeping…' : starting ? 'starting…' : 'start sweep'}
					</button>
				</header>
				<p class="form-error" role="alert">{error}</p>

				{#if run === null}
					{#if loadError}
						<p class="form-error">
							Couldn't read the last sweep: {loadError}
							<button type="button" class="btn small" onclick={() => loadStatus().catch(() => {})}
								>try again</button
							>
						</p>
					{:else}
						<p class="hint">Reading the last sweep…</p>
					{/if}
				{:else if !running && run.finished_at === null}
					<p class="status">No sweep has run yet.</p>
				{:else}
					<div class="status-block">
						<p class="status" class:live={running}>
							{#if running}
								Sweeping · <span class="mono">{run.processed.toLocaleString()}</span> of
								<span class="mono">{run.total.toLocaleString()}</span> files
							{:else if run.finished_at}
								Last sweep finished {formatWhen(run.finished_at)}
								{#if formatTook(run.started_at, run.finished_at)}
									<span class="took">· took {formatTook(run.started_at, run.finished_at)}</span>
								{/if}
							{/if}
						</p>
						{#if running && linkDown}
							<p class="link-lost">Live updates lost. Reconnecting; the counts may be behind.</p>
						{/if}

						<!-- v28: transform-animated fill (never width). v43: amber-dim only while a sweep
						     runs; a finished run's bar is settled (F10, F20). -->
						{#if run.total > 0}
							<div
								class="progress-bar"
								class:done={!running}
								role="progressbar"
								aria-label="Sweep progress"
								aria-valuenow={percent}
								aria-valuemin={0}
								aria-valuemax={100}
								aria-valuetext="{run.processed} of {run.total} files"
							>
								<div class="progress-fill" style:transform="scaleX({percent / 100})"></div>
							</div>
						{/if}

						<dl class="counts" aria-label={running ? 'So far' : 'Last sweep'}>
							<div class="count">
								<dt>moved</dt>
								<dd class="mono">{run.moved.toLocaleString()}</dd>
							</div>
							<div class="count">
								<dt>already in library</dt>
								<dd class="mono">{run.skipped_present.toLocaleString()}</dd>
							</div>
							<div class="count">
								<dt>quarantined</dt>
								<dd class="mono">{run.quarantined.toLocaleString()}</dd>
							</div>
							<div class="count" class:fail={errorCount > 0}>
								<dt>errors</dt>
								<dd class="mono">{errorCount.toLocaleString()}</dd>
							</div>
						</dl>
						{#if !running && run.total === 0}
							<p class="hint">Nothing to move: no download was waiting to go into the library.</p>
						{/if}
					</div>

					{#if !running && errorRows.length > 0}
						<div class="errors">
							<h3 class="label">Not moved</h3>
							<p class="hint">
								These files stayed where they were. Fix the cause and run the sweep again; nothing
								in the library was changed for them.
							</p>
							<ul class="error-list">
								{#each errorRows as e, i (i)}
									<li>
										<span class="file mono">{e.file}</span>
										<span class="reason">{e.error}</span>
									</li>
								{/each}
							</ul>
						</div>
					{/if}
				{/if}
			</section>
		{/if}
	</main>
</div>

<style>
	.stage {
		max-width: 64rem;
		margin: 0 auto;
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.main {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		margin-top: var(--space-2);
	}

	.sweep {
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-3) var(--space-5);
	}

	.head-text {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.hint {
		font-size: var(--fs-detail);
		color: var(--text-muted);
		max-width: 68ch;
	}

	.status-block {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.status {
		font-size: var(--fs-body);
		color: var(--text-primary);
	}

	.took {
		color: var(--text-muted);
	}

	.link-lost {
		font-size: var(--fs-detail);
		color: var(--waiting);
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
		width: 100%;
		background: var(--signal-dim);
		transform-origin: left;
		transform: scaleX(0);
		transition: transform var(--dur-med) var(--ease-signal);
	}

	.progress-bar.done .progress-fill {
		background: var(--settled-dim);
	}

	/* The report reads as four labelled numbers in a row, the number first. */
	.counts {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		margin: 0;
		border-top: 1px solid var(--line);
	}

	.count {
		display: flex;
		flex-direction: column-reverse;
		gap: var(--space-1);
		padding: var(--space-3) var(--space-3) 0 0;
	}

	.count + .count {
		padding-left: var(--space-3);
		border-left: 1px solid var(--line);
	}

	.count dt {
		font-size: var(--fs-meta);
		color: var(--text-muted);
	}

	.count dd {
		margin: 0;
		font-size: var(--fs-title);
		font-weight: var(--fw-medium);
		line-height: 1.2;
		color: var(--text-primary);
	}

	.count.fail dd {
		color: var(--fail);
	}

	.errors {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding-top: var(--space-3);
		border-top: 1px solid var(--line);
	}

	.error-list {
		list-style: none;
		margin: 0;
		padding: 0;
		max-height: 20rem;
		overflow-y: auto;
	}

	.error-list li {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--line);
	}

	.file {
		font-size: var(--fs-meta);
		color: var(--text-primary);
		overflow-wrap: anywhere;
	}

	.reason {
		font-size: var(--fs-detail);
		color: var(--fail);
	}

	@media (max-width: 640px) {
		.stage {
			padding: var(--space-4);
		}

		.sweep {
			padding: var(--space-4);
		}

		.head {
			flex-direction: column;
		}

		.counts {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		.count:nth-child(3) {
			padding-left: 0;
			border-left: none;
		}
	}
</style>
