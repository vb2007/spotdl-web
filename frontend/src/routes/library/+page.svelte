<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import { confirmAction, keepFocus } from '$lib/stores/confirm';
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
	// v43 (F20): the backend can record one file's error twice (F34a, a v48 fix). The count
	// stays the backend's own (it matches the sweep's Matrix alert); the list folds identical
	// rows into one entry marked ×n rather than repeating them.
	const errorRows = $derived(
		(run?.errors ?? []).reduce<{ file: string; error: string; times: number }[]>((rows, e) => {
			const same = rows.find((r) => r.file === e.file && r.error === e.error);
			if (same) same.times += 1;
			else rows.push({ ...e, times: 1 });
			return rows;
		}, [])
	);
	// True from a progress event until the full report (with its error list) is read back.
	let reportPending = $state(false);
	let reportError = $state('');
	// The backend also records whole-sweep problems as "<post-move sync>" or "<sweep>" rows:
	// those aren't files, so they get their own list.
	const fileRows = $derived(errorRows.filter((e) => !e.file.startsWith('<')));
	const sweepRows = $derived(errorRows.filter((e) => e.file.startsWith('<')));
	const errorCount = $derived(running || reportPending ? errorsSoFar : (run?.errors.length ?? 0));
	// The library settings the start question names (folder, duplicates rule), read once on
	// load so asking makes no request of its own.
	let librarySettings = $state<api.LibrarySettings | undefined>();
	let progressEvents = 0;

	const stateSentence = $derived(
		run === null
			? ''
			: running
				? 'Sweep running.'
				: run.finished_at === null
					? ''
					: reportPending
						? reportError
							? "Sweep finished; its error list couldn't be read."
							: ''
						: `Sweep finished: ${run.moved} moved, ${run.errors.length} error${run.errors.length === 1 ? '' : 's'}.`
	);
	// Spoken only once the state changes from what the page opened on: a visit doesn't
	// announce an old sweep's result.
	let firstSentence: string | null = null;
	let stateChanged = $state(false);
	$effect(() => {
		if (!stateSentence) return;
		if (firstSentence === null) firstSentence = stateSentence;
		else if (stateSentence !== firstSentence) stateChanged = true;
	});
	const announcement = $derived(stateChanged ? stateSentence : '');
	let heading: HTMLElement | undefined = $state();

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
		const seen = progressEvents;
		const status = await api.getLibrarySortStatus();
		// A read issued before a progress event can land after it (a mount or reconnect read
		// racing a sweep): it's older than what the stream already said, so it's dropped. The
		// done event's own re-read is issued after the last event, so it always applies.
		if (progressEvents !== seen) return;
		run = status;
		loadError = '';
		reportPending = false;
		reportError = '';
	}

	// v43 (F08): a sweep moves real files and archives jobs for every user, so it asks.
	async function onStart() {
		const settings = librarySettings;
		const duplicates =
			settings === undefined
				? 'quarantined or deleted, as set in settings'
				: settings.library_quarantine_enabled
					? `moved to ${settings.library_quarantine_dir}`
					: 'deleted';
		const confirmed = await confirmAction({
			title: 'Start a library sweep?',
			subject: settings?.library_target_dir,
			body:
				'Every finished download not yet in the library moves there. A download the library ' +
				`already has is ${duplicates}. Finished jobs whose tracks get filed are archived, for every ` +
				'user. Nothing already in the library is deleted.',
			confirmLabel: 'start sweep',
			cancelLabel: 'not now'
		});
		if (!confirmed) return keepFocus(heading);
		// The question named the settings as this page read them on load; if they changed in the
		// meantime (another tab), it named the wrong consequence: start nothing, say so.
		const asked = librarySettings;
		if (asked) {
			try {
				const now = await api.getLibrarySettings();
				librarySettings = now;
				if (
					now.library_target_dir !== asked.library_target_dir ||
					now.library_quarantine_enabled !== asked.library_quarantine_enabled ||
					now.library_quarantine_dir !== asked.library_quarantine_dir
				) {
					error =
						'The library settings changed while you were deciding. Check them and start again.';
					return keepFocus(heading);
				}
			} catch {
				// Unreadable: the sweep reads the settings itself; go ahead as asked.
			}
		}
		// Started meanwhile (another tab): this one would only be refused. Say so.
		if (running) {
			error = 'A sweep is already running; its progress is below.';
			return keepFocus(heading);
		}
		starting = true;
		error = '';
		try {
			const seen = progressEvents;
			const started = await api.startLibrarySort();
			// A fast sweep can report (even finish) over the stream before this answer lands;
			// the stream is then newer than the answer and must not be overwritten by it.
			if (progressEvents === seen) run = started;
		} catch (err) {
			error = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		} finally {
			starting = false;
		}
		// The button is disabled while the sweep runs, which drops its focus: land on the panel.
		await keepFocus(heading);
	}

	let source: EventSource | undefined;
	let retryTimer: ReturnType<typeof setTimeout> | undefined;
	let retryDelay = 2000;
	let unmounted = false;

	function onProgress(event: MessageEvent) {
		const payload = JSON.parse(event.data) as api.StreamEvent;
		if (payload.type !== 'library.progress') return;
		progressEvents += 1;
		reportPending = true;
		// "Already running" (or a failed start) is about the moment it was said; the stream has
		// moved on.
		error = '';
		// A sweep started elsewhere (another tab) arrives here first as an event: its start and
		// errors are its own, not the previous run's.
		const fresh = run?.state !== 'running';
		run = {
			state: payload.done ? 'idle' : 'running',
			// Joined mid-run, its real start is unknown until the report is read ("took" waits).
			started_at: fresh ? null : (run?.started_at ?? null),
			finished_at: payload.done ? payload.ts : null,
			total: payload.total,
			processed: payload.processed,
			moved: payload.moved,
			skipped_present: payload.skipped_present,
			quarantined: payload.quarantined,
			errors: fresh ? [] : (run?.errors ?? [])
		};
		// The SSE payload doesn't carry the final error list -- re-fetch the full report
		// once the sweep reports done, rather than trying to accumulate per-file errors
		// client-side from a stream that was designed as a light progress signal, not a log.
		if (payload.done) {
			loadStatus().catch(() => {
				// The four counts came with the event; only the error list is missing, so the
				// error count stays the one derived from the event and the gap is said.
				reportError = "Couldn't read the list of files that weren't filed; reload to see it.";
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
				loadStatus().catch(() => {
					// Back online but the status read failed: a sweep that ended meanwhile may
					// still read as running. Say so rather than freeze silently.
					reportError = "Reconnected, but couldn't re-read the sweep; reload to be sure.";
				});
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
		api
			.getLibrarySettings()
			.then((settings) => (librarySettings = settings))
			.catch(() => {
				// The start question then names the rule generically, without the folder.
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
				<!-- One sentence per state, never per file: the counts tick, the announcement doesn't. -->
				<p class="sr-only" role="status">{announcement}</p>
				<header class="head">
					<div class="head-text">
						<h2 id="sweep-heading" class="label" tabindex="-1" bind:this={heading}>Sweep</h2>
						<p class="hint">
							Moves finished downloads into the music library, into folders named by the folder
							template. The folder, the template and what happens to duplicates are set in
							<a href={resolve('/settings')}>settings</a>.
						</p>
					</div>
					<button type="button" class="btn" disabled={starting || running} onclick={onStart}>
						{running ? 'sweeping…' : starting ? 'starting…' : 'start sweep'}
					</button>
				</header>
				<!-- One alert line for the page: a start that failed, or a report that couldn't be read. -->
				<p class="form-error" role="alert">{error || reportError}</p>

				{#if run === null}
					{#if loadError}
						<p class="form-error">
							Couldn't read the last sweep: {loadError}
							<button
								type="button"
								class="btn small"
								onclick={() =>
									loadStatus().catch((err) => {
										loadError =
											err instanceof api.ApiError
												? `${err.message} (tried again at ${new Date().toLocaleTimeString()})`
												: `Could not reach the server (tried again at ${new Date().toLocaleTimeString()}).`;
									})}>try again</button
							>
						</p>
					{:else}
						<p class="hint">Reading the last sweep…</p>
					{/if}
				{:else if !running && run.finished_at === null}
					<p class="status">No sweep has run yet.</p>
				{:else}
					<div class="status-block">
						<p class="status">
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
								class:stale={running && linkDown}
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

						<dl class="counts">
							<div class="count">
								<dt>moved</dt>
								<dd class="mono">{run.moved.toLocaleString()}</dd>
							</div>
							<div class="count">
								<dt>duplicates deleted</dt>
								<dd class="mono">{run.skipped_present.toLocaleString()}</dd>
							</div>
							<div class="count">
								<dt>duplicates quarantined</dt>
								<dd class="mono">{run.quarantined.toLocaleString()}</dd>
							</div>
							<div class="count" class:fail={errorCount > 0}>
								<dt>errors</dt>
								<dd class="mono">{errorCount.toLocaleString()}</dd>
							</div>
						</dl>
						<!-- A crash before the count (errors > 0, total 0) is not "nothing to move". -->
						{#if !running && run.total === 0 && errorCount === 0}
							<p class="hint">Nothing to move: no download was waiting to go into the library.</p>
						{/if}
					</div>

					{#if !running && !reportPending && sweepRows.length > 0}
						<div class="errors">
							<h3 class="label">Sweep problems</h3>
							<p class="hint">
								Not about one file: the sweep itself hit these (bookkeeping after the moves, or a
								crash). Files it already filed stay filed.
							</p>
							<ul class="error-list">
								{#each sweepRows as e, i (i)}
									<li>
										<span class="file mono">{e.file}</span>
										<span class="reason">{e.error}</span>
									</li>
								{/each}
							</ul>
						</div>
					{/if}
					{#if !running && !reportPending && fileRows.length > 0}
						<div class="errors">
							<h3 class="label">Not filed</h3>
							<p class="hint">
								The sweep hit an error on these. A file it couldn't read or copy stays where it was:
								fix the cause and run the sweep again. Nothing already in the library was deleted.
							</p>
							<ul class="error-list">
								{#each fileRows as e, i (i)}
									<li>
										<span class="file mono">{e.file}</span>
										<span class="reason"
											>{e.error}{#if e.times > 1}<span class="times mono">
													×{e.times}</span
												>{/if}</span
										>
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

	/* v42's rule for stale data: with the link down the fill can't be trusted as live, so it
	   drops the amber. */
	.progress-bar.stale .progress-fill {
		background: var(--line-bright);
	}

	.times {
		color: var(--text-muted);
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
