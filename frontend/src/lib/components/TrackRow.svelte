<script lang="ts">
	import { untrack } from 'svelte';
	import { SvelteMap, SvelteSet } from 'svelte/reactivity';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import { worker } from '$lib/stores/worker';
	import { confirmAction, keepFocus } from '$lib/stores/confirm';
	import Countdown from '$lib/components/Countdown.svelte';
	import {
		attemptVia,
		formatDuration,
		groupAttempts,
		relativeTime,
		summarizeVia
	} from '$lib/attempts';
	import type { TrackAttempt, TrackAttemptOutcome, TrackState } from '$lib/api';
	import type { LiveTrack } from '$lib/stores/queue';

	let { track, jobId, isAdmin }: { track: LiveTrack; jobId: string; isAdmin: boolean } = $props();

	let expanded = $state(false);
	const detailId = $derived(`track-detail-${track.id}`);

	const { status: workerStatus } = worker;

	// Attempt history (v24) is diagnostic, not part of the live queue -- fetched lazily on
	// first expand rather than carried in the queue store, and cached per track id so
	// re-collapsing/re-expanding the same row doesn't refetch. v41: admin-only (master plan
	// amendment, v39 outcome 3). A non-admin never requests it and its markup never renders.
	let attempts = $state<TrackAttempt[]>([]);
	let attemptsLoading = $state(false);
	let attemptsError = $state<string | null>(null);
	let attemptsLoadedFor = $state<string | null>(null);

	// v41 (F21): the same words the state-filter chips use, so a state reads the same on a
	// chip and on a row (and none of them truncates in the state column, F13).
	const STATE_LABEL: Record<TrackState, string> = {
		pending: 'pending',
		queued: 'queued',
		downloading: 'downloading',
		completed: 'completed',
		waiting: 'waiting',
		lookup_failed: 'not found',
		skipped_duplicate: 'duplicate',
		cancelled: 'cancelled'
	};

	const STATE_COND: Record<TrackState, string> = {
		pending: 'cond-idle',
		queued: 'cond-idle',
		downloading: 'cond-live',
		completed: 'cond-settled',
		waiting: 'cond-waiting',
		lookup_failed: 'cond-fail',
		skipped_duplicate: 'cond-settled',
		cancelled: 'cond-idle'
	};

	// The first thing the expanded view says: what this state means for the listener, in
	// plain words, with the next step where there is one (F24, F25).
	const STATUS_TEXT: Record<TrackState, string> = {
		pending: 'in line, not dispatched yet',
		queued: 'queued for the downloader',
		downloading: 'downloading',
		completed: 'downloaded',
		waiting: 'waiting to retry',
		lookup_failed: "won't retry on its own · retry now to try again",
		skipped_duplicate: 'already downloaded earlier · nothing fetched',
		cancelled: "cancelled · won't be downloaded"
	};

	const ATTEMPT_OUTCOME_LABEL: Record<TrackAttemptOutcome, string> = {
		completed: 'completed',
		failed: 'failed',
		cancelled: 'cancelled',
		skipped_duplicate: 'duplicate',
		held: 'held · not attempted'
	};

	// Same `.cond-*` vocabulary as the row (app.css), so a color means one thing everywhere.
	// v41 (F03): only a terminal verdict is red. A failure the ladder retries is the
	// waiting condition (DESIGN.md §2: fail is "terminal only, never backoff"), so a
	// recoverable track's history is no longer a wall of red.
	function outcomeCond(attempt: TrackAttempt): string {
		if (attempt.outcome === 'failed') {
			return attempt.error_type === 'lookup' ? 'cond-fail' : 'cond-waiting';
		}
		if (attempt.outcome === 'completed' || attempt.outcome === 'skipped_duplicate') {
			return 'cond-settled';
		}
		return attempt.outcome === 'held' ? 'cond-waiting' : 'cond-idle';
	}

	const CANCELLABLE_STATES = new Set<TrackState>(['pending', 'queued', 'downloading', 'waiting']);
	// v41 (F24, owner's call): a lookup_failed track is already terminal, so it offers
	// "retry now" only. The backend still accepts a cancel; the UI no longer asks for one.
	const RETRYABLE_STATES = new Set<TrackState>(['waiting', 'lookup_failed']);
	// The only two states download_track ever sets `output_path` from (backend/app/tasks/
	// download.py) -- every other state never had a file, so the action simply doesn't
	// render rather than rendering and failing (v27's plan: "nothing for tracks without a
	// file"). A file deleted from disk after the fact still shows the button; that request
	// 404s and surfaces through the same notice as any other action error.
	const DOWNLOADABLE_STATES = new Set<TrackState>(['completed', 'skipped_duplicate']);

	let canRetry = $derived(RETRYABLE_STATES.has(track.state));
	let canDownload = $derived(DOWNLOADABLE_STATES.has(track.state));
	let canCancel = $derived(CANCELLABLE_STATES.has(track.state));
	let rowButton: HTMLButtonElement | undefined = $state();

	// v41 (F04, the countdown half): beat dispatches nothing while the breaker holds, so a
	// waiting track's real next try is the later of its own slot and the breaker's clear.
	let nextTry = $derived.by((): { at: string; heldByBreaker: boolean } | null => {
		if (track.state !== 'waiting' || !track.scheduled_at) return null;
		const breakerUntil = $workerStatus?.breaker_tripped_until ?? null;
		// An expired trip keeps its timestamp until the next success or release, so it only
		// counts while it's still in the future (the backend's own `breaker_active` test).
		if (
			breakerUntil &&
			Date.parse(breakerUntil) > Date.now() &&
			Date.parse(breakerUntil) > Date.parse(track.scheduled_at)
		) {
			return { at: breakerUntil, heldByBreaker: true };
		}
		return { at: track.scheduled_at, heldByBreaker: false };
	});
	let workerPaused = $derived($workerStatus?.paused ?? false);

	let groups = $derived(groupAttempts(attempts));
	let lastPath = $derived.by(() => {
		const reached = attempts.filter((a) => a.network_path !== null || a.proxy_id !== null);
		if (!reached.length) return null;
		// The strip names the family; the proxy's address is in the timeline's own entry.
		const via = attemptVia(reached[reached.length - 1]);
		return via.startsWith('via proxy') ? 'via proxy' : via;
	});
	// `last_error` is the newest failure's text, which the timeline already shows. It only
	// gets its own line when the timeline can't: a track failed before v24 kept attempts.
	let lastErrorUnshown = $derived(
		track.last_error !== null && !attempts.some((a) => a.error_message === track.last_error)
	);

	// Relative times in the timeline tick coarsely while the row is open.
	let now = $state(Date.now());
	$effect(() => {
		if (!expanded) return;
		now = Date.now();
		const id = setInterval(() => {
			now = Date.now();
		}, 30_000);
		return () => clearInterval(id);
	});

	// The cache is keyed on what writing an attempt row changes, not just the track id: a
	// failure or success moves the counts, a `held` row (which moves no count) moves
	// `scheduled_at`, and a settle moves the state. The in-flight states share one key, so
	// pending → queued → downloading (no row written) never refetches, nor does a progress tick.
	const IN_FLIGHT_KEY = new Set<TrackState>(['pending', 'queued', 'downloading']);
	let attemptsKey = $derived(
		[
			track.id,
			IN_FLIGHT_KEY.has(track.state) ? 'in-flight' : track.state,
			track.attempts_made,
			track.failure_count,
			// Parsed: REST and the worker's events spell the same instant in different zones.
			track.scheduled_at ? Date.parse(track.scheduled_at) : null
		].join('|')
	);

	/** `force` re-reads a key already loaded, keeping the current list on screen meanwhile
	 * (clearing `attemptsLoadedFor` instead would swap it for the loading line and drop any
	 * focus inside it). */
	async function loadAttempts(key: string, force = false) {
		if (!force && attemptsLoadedFor === key) {
			// Back on a key already loaded: whatever request is still out is superseded.
			attemptsLoading = false;
			return;
		}
		attemptsLoading = true;
		attemptsError = null;
		try {
			const loaded = await api.getTrackAttempts(track.id);
			if (key !== attemptsKey) return;
			attempts = loaded;
			attemptsLoadedFor = key;
		} catch (err) {
			// A request superseded by a newer key never touches the newer one's state.
			if (key !== attemptsKey) return;
			attemptsError = err instanceof api.ApiError ? err.message : 'Could not load attempt history.';
		} finally {
			if (key === attemptsKey) attemptsLoading = false;
		}
	}

	// Lazy: only an open row of an admin ever requests its history (no per-row loop).
	$effect(() => {
		const key = attemptsKey;
		if (expanded && isAdmin) untrack(() => loadAttempts(key));
	});

	// The worker publishes a cancelled download's event before it writes that attempt's
	// row (and without counts), so a cancelled track's key can't see the row land. Its
	// history is refetched on every open rather than served from the cache.
	function toggleExpanded() {
		expanded = !expanded;
		// Forced, so the history already on screen stays there while it's re-read; a row
		// never loaded is fetched by the effect below as usual.
		if (expanded && isAdmin && track.state === 'cancelled' && attemptsLoadedFor !== null) {
			loadAttempts(attemptsKey, true);
		}
	}

	// Collapsed runs the operator opened, and long messages they unclamped -- keyed by the
	// group's *oldest* attempt id (attempts.ts), which survives the run growing.
	const openRuns = new SvelteSet<string>();
	const openMessages = new SvelteSet<string>();
	const pinnedTimes = new SvelteSet<string>();
	// Esc hides an open time tooltip until the pointer or focus leaves (WCAG 1.4.13).
	const dismissedTimes = new SvelteSet<string>();
	// The time under the pointer, so Esc can dismiss a tooltip opened by hover alone while
	// keyboard focus sits elsewhere.
	let hoveredTime = $state<string | null>(null);

	function dismissTimeOnEscape(e: KeyboardEvent) {
		if (e.key !== 'Escape' || hoveredTime === null) return;
		pinnedTimes.delete(hoveredTime);
		dismissedTimes.add(hoveredTime);
	}
	const clampable = new SvelteMap<string, boolean>();

	function toggleIn(set: SvelteSet<string>, key: string) {
		if (set.has(key)) set.delete(key);
		else set.add(key);
	}

	/** Shows a message's expand control only when the 3-line clamp actually cut it. */
	function measureClamp(key: string) {
		return (node: HTMLElement) => {
			const check = () => {
				if (untrack(() => openMessages.has(key))) return;
				clampable.set(key, node.scrollHeight > node.clientHeight + 1);
			};
			const observer = new ResizeObserver(check);
			observer.observe(node);
			untrack(check);
			return () => observer.disconnect();
		};
	}

	function formatTimestamp(value: string): string {
		return new Date(value).toLocaleString();
	}

	// Per-row transient feedback (e.g. "held behind the global pause") -- SvelteMap so
	// mutations are tracked without wholesale reassignment (see v09's reactivity gotcha).
	const notice = new SvelteMap<string, string>();

	function showNotice(text: string) {
		notice.set(track.id, text);
		setTimeout(() => {
			if (notice.get(track.id) === text) notice.delete(track.id);
		}, 4000);
	}

	// The pending re-read, cleared when the row is destroyed (a collapsed job, a scope
	// switch, a logout) so no request goes out from a row that's gone.
	let cancelReread: ReturnType<typeof setTimeout> | undefined;
	let destroyed = false;
	$effect(() => () => {
		destroyed = true;
		clearTimeout(cancelReread);
	});

	function awaitCancelledAttempt(seen: number, delays: number[]) {
		const [delay, ...rest] = delays;
		if (delay === undefined) return;
		clearTimeout(cancelReread);
		cancelReread = setTimeout(async () => {
			if (destroyed || !expanded || !isAdmin) return;
			await loadAttempts(attemptsKey, true);
			// A read still out when the row went away must not schedule another.
			if (!destroyed && attempts.length <= seen) awaitCancelledAttempt(seen, rest);
		}, delay);
	}

	// v43 (F08): a cancelled track can't be retried, so cancelling asks first.
	async function handleCancel() {
		const artists = track.artists?.join(', ');
		const confirmed = await confirmAction({
			title: 'Cancel this track?',
			subject: [track.title ?? 'Unknown title', artists].filter(Boolean).join(' — '),
			body:
				(track.state === 'downloading'
					? 'The download in progress finishes, but the track stays cancelled. '
					: "It won't be downloaded. ") +
				"This can't be undone, but the link can be submitted again.",
			confirmLabel: 'cancel track',
			cancelLabel: 'keep track'
		});
		if (!confirmed) return;
		// A row gone while the question was open has stale props: do nothing, and put focus on
		// the queue it left rather than <body>.
		if (destroyed) {
			await keepFocus(document.getElementById('queue-heading'));
			return;
		}
		// The question can stay open while the track settles (or turns lookup_failed, which
		// v41 deliberately offers no cancel for): ask the current state, not the old one.
		if (!canCancel) {
			showNotice(`Not cancelled: it's ${STATE_LABEL[track.state]} now.`);
			await keepFocus(rowButton);
			return;
		}
		const wasDownloading = track.state === 'downloading';
		const seenAttempts = attempts.length;
		try {
			await queue.cancelTrack(track.id, jobId);
			// Same reason as above: the worker records the cancelled attempt only once its
			// download call returns, seconds later. Re-read a few times, bounded, until the
			// newest attempt is that cancel.
			if (wasDownloading) awaitCancelledAttempt(seenAttempts, [3000, 5000, 7000, 15000, 30000]);
		} catch (err) {
			showNotice(err instanceof api.ApiError ? err.message : 'Could not cancel this track.');
		}
		// "cancel track" leaves with the cancellable state: land on the row itself.
		await keepFocus(rowButton);
	}

	async function handleRetry() {
		try {
			const { breakerHeld } = await queue.retryTrack(track.id, jobId);
			showNotice(
				breakerHeld
					? 'held — global pause is active, will dispatch once it clears'
					: 'queued — dispatching on the next pass'
			);
		} catch (err) {
			showNotice(err instanceof api.ApiError ? err.message : 'Could not retry this track.');
		}
	}

	// v35 (e): probe first, then let the browser download the real URL itself, so a whole
	// FLAC is streamed to disk instead of buffered into a Blob in tab memory. The empty
	// `download` attribute keeps the page in place and takes the filename from the
	// response's Content-Disposition.
	async function handleDownload() {
		try {
			await api.checkTrackFile(track.id);
		} catch (err) {
			showNotice(err instanceof api.ApiError ? err.message : 'Could not download this file.');
			return;
		}
		const anchor = document.createElement('a');
		anchor.href = api.trackFileUrl(track.id);
		anchor.download = '';
		document.body.appendChild(anchor);
		anchor.click();
		anchor.remove();
	}
</script>

<svelte:window onkeydown={hoveredTime !== null ? dismissTimeOnEscape : undefined} />

{#snippet when(iso: string, key: string)}
	<!-- Relative at a glance; the absolute time on hover and on keyboard focus, and pinned
	     open by a click or Enter for reading it alongside the error. -->
	<button
		type="button"
		class="when mono"
		class:pinned={pinnedTimes.has(key)}
		class:dismissed={dismissedTimes.has(key)}
		aria-pressed={pinnedTimes.has(key)}
		onclick={() => {
			dismissedTimes.delete(key);
			toggleIn(pinnedTimes, key);
		}}
		onkeydown={(e) => {
			if (e.key !== 'Escape') return;
			pinnedTimes.delete(key);
			dismissedTimes.add(key);
		}}
		onpointerenter={() => (hoveredTime = key)}
		onpointerleave={() => {
			if (hoveredTime === key) hoveredTime = null;
			dismissedTimes.delete(key);
		}}
		onblur={() => dismissedTimes.delete(key)}
		><time datetime={iso}>{relativeTime(iso, now)}</time><span class="abs"
			><span class="sep">, </span>{formatTimestamp(iso)}</span
		></button
	>
{/snippet}

<li>
	<button
		bind:this={rowButton}
		type="button"
		class="row"
		onclick={toggleExpanded}
		aria-expanded={expanded}
		aria-controls={detailId}
	>
		<span class="cell state {STATE_COND[track.state]} mono"
			>{STATE_LABEL[
				track.state
			]}{#if track.state === 'downloading' && track.progress !== undefined}<span class="pct"
					>&nbsp;{track.progress}%</span
				>{/if}</span
		>
		<span class="cell title" title={track.title ?? undefined}>{track.title ?? 'Unknown title'}</span
		>
		<span class="meta">
			<span class="cell artist" title={track.artists?.join(', ')}
				>{track.artists?.join(', ') ?? '—'}</span
			>
			<span class="cell album" title={track.album ?? undefined}>{track.album ?? '—'}</span>
		</span>
		<span class="chevron" aria-hidden="true"></span>
	</button>

	{#if expanded}
		<div class="detail" id={detailId}>
			<div class="strip">
				<span class="status {STATE_COND[track.state]}">{STATUS_TEXT[track.state]}</span>
				{#if track.state === 'downloading' && track.progress !== undefined}
					<span
						class="progress"
						role="progressbar"
						aria-label="Download progress"
						aria-valuemin={0}
						aria-valuemax={100}
						aria-valuenow={track.progress}
					>
						<span class="progress-fill" style:transform="scaleX({track.progress / 100})"></span>
					</span>
					<span class="fact mono">{track.progress}%</span>
				{/if}
				{#if nextTry}
					<span class="fact"
						><Countdown
							scheduledAt={nextTry.at}
							label="next try in"
							dueLive={false}
							dueText={workerPaused ? 'due' : 'due on the next pass'}
						/></span
					>
					{#if nextTry.heldByBreaker}
						<span class="fact quiet">after the global pause clears</span>
					{/if}
					{#if workerPaused}
						<span class="fact quiet">downloads are paused</span>
					{/if}
				{/if}
				{#if isAdmin && track.state !== 'skipped_duplicate'}
					<!-- One unit: the counts and the path wrap together, never apart. -->
					<span class="facts">
						<span class="fact mono"><span class="key">attempts</span> {track.attempts_made}</span>
						<span class="fact mono"><span class="key">failed</span> {track.failure_count}</span>
						{#if lastPath}
							<span class="fact mono"><span class="key">last path</span> {lastPath}</span>
						{/if}
					</span>
				{/if}
			</div>

			{#if canRetry || canDownload || canCancel}
				<div class="actions" role="group" aria-label="Track actions">
					{#if canRetry}
						<button type="button" class="action" onclick={handleRetry}>retry now</button>
					{/if}
					{#if canDownload}
						<button type="button" class="action" onclick={handleDownload}>download</button>
					{/if}
					{#if canCancel}
						<button type="button" class="action danger" onclick={handleCancel}>cancel track</button>
					{/if}
				</div>
			{/if}
			<p class="notice" role="status">{notice.get(track.id) ?? ''}</p>

			{#if isAdmin}
				<div class="history">
					{#if attemptsError && attemptsLoadedFor !== null}
						<!-- A failed re-read never hides the history already loaded. -->
						<p class="history-status history-error">
							couldn't refresh ({attemptsError}) · showing the last loaded history
						</p>
					{/if}
					{#if attemptsLoading && attemptsLoadedFor === null}
						<p class="history-status">loading attempt history…</p>
					{:else if attemptsError && attemptsLoadedFor === null}
						<p class="history-status history-error">{attemptsError}</p>
					{:else if attempts.length === 0}
						<p class="history-status">no attempts yet</p>
					{:else}
						<p class="history-heading mono">attempt history · newest first</p>
						<ol class="timeline" aria-label="attempt history">
							{#each groups as group (group.key)}
								{@const head = group.attempts[0]}
								{@const run = group.attempts.length}
								{@const message = head.error_message}
								<li class="entry">
									{@render when(head.finished_at, head.id)}
									<div class="entry-body">
										<p class="reading mono">
											{#if run > 1}<span class="times">×{run}</span>{/if}
											<span class="outcome {outcomeCond(head)}"
												>{ATTEMPT_OUTCOME_LABEL[head.outcome]}</span
											>
											{#if head.error_type}<span class="class">{head.error_type}</span>{/if}
											<span class="via"
												>{run > 1 ? summarizeVia(group.attempts) : attemptVia(head)}</span
											>
											{#if run === 1 && head.outcome !== 'held'}
												<span class="dur">{formatDuration(head.duration_seconds)}</span>
											{/if}
										</p>
										{#if message}
											<p
												class="message mono"
												class:clamped={!openMessages.has(group.key)}
												id="msg-{group.key}"
												{@attach measureClamp(group.key)}
											>
												{message}
											</p>
											{#if clampable.get(group.key) || openMessages.has(group.key)}
												<button
													type="button"
													class="inline-toggle"
													aria-expanded={openMessages.has(group.key)}
													aria-controls="msg-{group.key}"
													onclick={() => toggleIn(openMessages, group.key)}
													>{openMessages.has(group.key) ? 'show less' : 'show full message'}</button
												>
											{/if}
										{/if}
										{#if head.warning_message}
											<p class="note">
												<span class="note-tag mono">note</span>
												<span class="note-text mono">{head.warning_message}</span>
											</p>
										{/if}
										{#if run > 1}
											<button
												type="button"
												class="inline-toggle"
												aria-expanded={openRuns.has(group.key)}
												aria-controls="run-{group.key}"
												onclick={() => toggleIn(openRuns, group.key)}
												>{openRuns.has(group.key) ? 'hide the repeats' : `show all ${run}`}</button
											>
											{#if openRuns.has(group.key)}
												<ol class="run" id="run-{group.key}" aria-label="repeated attempts">
													{#each group.attempts as attempt (attempt.id)}
														<li class="run-item mono">
															{@render when(attempt.finished_at, `run-${attempt.id}`)}
															<span class="via">{attemptVia(attempt)}</span>
															{#if attempt.outcome !== 'held'}
																<span class="dur">{formatDuration(attempt.duration_seconds)}</span>
															{/if}
															<span class="quiet">same reading</span>
														</li>
													{/each}
												</ol>
											{/if}
										{/if}
									</div>
								</li>
							{/each}
						</ol>
					{/if}
					{#if lastErrorUnshown && !attemptsLoading}
						<p class="last-error mono"><span class="key">last error</span> {track.last_error}</p>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</li>

<style>
	li {
		border-bottom: 1px solid var(--line);
	}

	li:last-child {
		border-bottom: none;
	}

	/* The shared row grid (app.css "Row grid"): the state column is exactly a job badge's
	   width, so inside a job (indented by one lead column) the state sits under the
	   badge and the title under the job's title. The trailing lead-width column is the
	   disclosure chevron (F22). */
	.row {
		width: 100%;
		display: grid;
		grid-template-columns:
			var(--col-state) minmax(0, 1.5fr) minmax(0, 1fr) minmax(0, 1fr)
			var(--col-lead);
		column-gap: var(--row-gap);
		align-items: baseline;
		padding: var(--space-2) var(--row-pad-x) var(--space-2) 0;
		background: transparent;
		border: none;
		text-align: left;
		cursor: pointer;
		color: inherit;
	}

	/* v42: on the raised faceplate (--bg-1) a --bg-2 fill is only 1.045:1, and any brighter
	   fill would drop the row's dim and fail text under 4.5:1, so hover underlines the title. */
	.row:hover .cell.title {
		text-decoration: underline;
		text-decoration-color: var(--text-muted);
		text-underline-offset: 0.2em;
	}

	/* Artist and album are grid cells of the row on desktop; the wrapper only exists so
	   tablet and phone widths can set them as one muted line under the title. */
	.meta {
		display: contents;
	}

	.cell {
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* An open row shows its whole title, artist and album instead of the ellipsis (F13). */
	.row[aria-expanded='true'] .cell {
		white-space: normal;
		overflow-wrap: anywhere;
	}

	.cell.state {
		padding-left: var(--cell-inset);
		font-size: var(--fs-meta);
		letter-spacing: 0.04em;
	}

	.cell.artist,
	.cell.album {
		color: var(--text-muted);
		font-size: var(--fs-detail);
	}

	.chevron {
		justify-self: center;
		align-self: center;
		width: 0.4rem;
		height: 0.4rem;
		border-right: 1.5px solid var(--text-muted);
		border-bottom: 1.5px solid var(--text-muted);
		transform: translateY(-25%) rotate(45deg);
		transition: transform var(--dur-fast) var(--ease-signal);
	}

	.row[aria-expanded='true'] .chevron {
		transform: translateY(15%) rotate(-135deg);
	}

	/* The detail is the row's own grid, two columns wide: the state column becomes a
	   time gutter for the history, everything else hangs off the title column. */
	.detail {
		display: grid;
		grid-template-columns: var(--col-state) minmax(0, 1fr);
		column-gap: var(--row-gap);
		row-gap: var(--space-3);
		padding: var(--space-1) var(--row-pad-x) var(--space-4) 0;
		font-size: var(--fs-detail);
		color: var(--text-muted);
	}

	.detail > * {
		grid-column: 2;
		margin: 0;
	}

	.strip {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		column-gap: var(--space-4);
		row-gap: var(--space-1);
	}

	.status {
		font-weight: 500;
	}

	.facts {
		display: inline-flex;
		flex-wrap: nowrap;
		column-gap: var(--space-4);
		white-space: nowrap;
	}

	/* Value in primary text, its key in muted: both at full opacity (AA on every panel). */
	.fact {
		min-width: 0;
		font-size: var(--fs-meta);
		color: var(--text-primary);
		overflow-wrap: anywhere;
	}

	.key {
		color: var(--text-muted);
		margin-right: var(--space-1);
	}

	.quiet {
		color: var(--text-muted);
	}

	.progress {
		align-self: center;
		width: 8rem;
		height: 0.375rem;
		border-radius: 3px;
		background: var(--bg-0);
		border: 1px solid var(--line);
		overflow: hidden;
	}

	.progress-fill {
		display: block;
		height: 100%;
		background: var(--signal);
		transform-origin: left;
		transition: transform var(--dur-med) var(--ease-signal);
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
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
	}

	.action:hover,
	.action:focus-visible {
		border-color: var(--waiting);
		color: var(--text-primary);
	}

	/* Destructive, so set apart from the neutral actions and outlined in the fail tone
	   at rest; full fail red only on hover/focus, the moment it's about to be used. */
	.action.danger {
		background: transparent;
		border-color: var(--fail-edge);
	}

	/* Set apart only when it follows a neutral action, so the action area always starts
	   at the title column. */
	.action + .action.danger {
		margin-left: var(--space-4);
	}

	.action.danger:hover,
	.action.danger:focus-visible {
		border-color: var(--fail);
		color: var(--fail);
	}

	.notice {
		color: var(--waiting);
		font-family: var(--font-mono);
		font-size: var(--fs-meta);
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

	/* The history spans both columns: times in the state column's gutter, readings under
	   the title. Diagnostic (v24), so quieter than the strip above it. */
	.history {
		grid-column: 1 / -1;
		display: grid;
		grid-template-columns: subgrid;
		row-gap: var(--space-2);
		padding-top: var(--space-2);
		border-top: 1px solid var(--line);
	}

	.history > * {
		grid-column: 2;
		margin: 0;
	}

	.history-heading {
		font-size: var(--fs-label);
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.history-status {
		font-size: var(--fs-meta);
	}

	.history-error {
		color: var(--fail);
	}

	.timeline {
		grid-column: 1 / -1;
		display: grid;
		grid-template-columns: subgrid;
		row-gap: var(--space-3);
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.entry {
		grid-column: 1 / -1;
		display: grid;
		grid-template-columns: subgrid;
		align-items: baseline;
		border: none;
	}

	.entry > .when {
		grid-column: 1;
		justify-self: start;
		margin-left: var(--cell-inset);
	}

	.entry-body {
		grid-column: 2;
		min-width: 0;
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-1);
	}

	.when {
		position: relative;
		min-height: 1.5rem;
		background: none;
		border: none;
		padding: 0;
		font-size: var(--fs-meta);
		color: var(--text-muted);
		white-space: nowrap;
		cursor: pointer;
	}

	/* The absolute time: visually hidden until the relative one is hovered or focused,
	   but always in the accessibility tree. */
	.when .abs {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
	}

	/* Keeps the button's name "12m ago, 10/14/2026, …" rather than run together; never
	   shown in the tooltip. */
	.when .sep {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
	}

	.when:hover .abs,
	.when:focus-visible .abs,
	.when.pinned .abs {
		/* Visible, or it clips its own hover bridge below. */
		overflow: visible;
		left: 0;
		bottom: calc(100% + var(--space-1));
		z-index: 1;
		width: auto;
		height: auto;
		clip-path: none;
		padding: var(--space-1) var(--space-2);
		background: var(--bg-3);
		border: 1px solid var(--line-bright);
		border-radius: 3px;
		color: var(--text-primary);
	}

	/* Bridges the gap down to the button, so the pointer can move onto the tooltip without
	   losing it (WCAG 1.4.13, hoverable). */
	.when:hover .abs::after {
		content: '';
		position: absolute;
		left: 0;
		right: 0;
		top: 100%;
		height: calc(var(--space-1) + 2px);
	}

	/* Pinned, the absolute time joins the gutter under the relative one instead of
	   floating over the entry above. */
	.when.pinned {
		display: inline-flex;
		flex-direction: column;
		align-items: flex-start;
		text-align: left;
	}

	.when.pinned .abs {
		position: static;
		width: auto;
		height: auto;
		padding: 0;
		border: 0;
		background: none;
		clip-path: none;
		white-space: normal;
		color: var(--text-primary);
	}

	/* Back to the resting clip, so the absolute time stays in the button's name. */
	.when.dismissed .abs {
		width: 1px;
		height: 1px;
		padding: 0;
		border: 0;
		clip-path: inset(50%);
	}

	.reading {
		margin: 0;
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		column-gap: var(--space-3);
		font-size: var(--fs-meta);
	}

	.times {
		color: var(--text-primary);
		font-weight: 600;
	}

	.outcome {
		font-weight: 600;
	}

	.class {
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-primary);
	}

	/* A proxy label (an IPv6 host, a long hostname) has no break opportunity of its own. */
	.via,
	.dur {
		min-width: 0;
		color: var(--text-muted);
		overflow-wrap: anywhere;
	}

	/* The raw error stays exactly as the worker wrote it, selectable and copyable;
	   three lines unless the operator asks for the rest. */
	.message {
		margin: 0;
		max-width: 80ch;
		font-size: var(--fs-meta);
		line-height: 1.5;
		color: var(--text-muted);
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		user-select: text;
	}

	.message.clamped {
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 3;
		line-clamp: 3;
		overflow: hidden;
	}

	/* Text-sized, but a 24px-tall hit area (WCAG 2.5.8) on every inline control. */
	.inline-toggle {
		min-height: 1.5rem;
		background: none;
		border: none;
		padding: 0;
		font-family: var(--font-mono);
		font-size: var(--fs-meta);
		color: var(--text-primary);
		text-decoration: underline;
		text-underline-offset: 2px;
		cursor: pointer;
	}

	/* v41 (F14): a note on an attempt that didn't fail. Neither failure red nor the
	   waiting blue a scheduling note uses -- an outlined "note" tag on neutral text. */
	.note {
		margin: 0;
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		max-width: 80ch;
	}

	.note-tag {
		flex-shrink: 0;
		padding: 0 var(--space-1);
		border: 1px solid var(--line-bright);
		border-radius: 3px;
		font-size: var(--fs-label);
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--text-primary);
	}

	.note-text {
		font-size: var(--fs-meta);
		color: var(--text-muted);
		overflow-wrap: anywhere;
	}

	.run {
		list-style: none;
		margin: 0;
		padding: 0 0 0 var(--space-3);
		border-left: 1px solid var(--line);
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.run-item {
		display: flex;
		flex-wrap: wrap;
		column-gap: var(--space-3);
		font-size: var(--fs-meta);
		border: none;
	}

	.last-error {
		font-size: var(--fs-meta);
		overflow-wrap: anywhere;
	}

	/* Tablet: artist and album fold into one muted line under the title rather than
	   squeezing three text columns (F37, for these rows; v42 owns the page breakpoint). */
	@media (max-width: 960px) {
		.row {
			grid-template-columns: var(--col-state) minmax(0, 1fr) var(--col-lead);
			grid-template-areas:
				'state title chevron'
				'. meta chevron';
			row-gap: 0.125rem;
		}

		.cell.state {
			grid-area: state;
		}

		.cell.title {
			grid-area: title;
		}

		.chevron {
			grid-area: chevron;
		}

		.meta {
			grid-area: meta;
			display: block;
			min-width: 0;
			white-space: nowrap;
			overflow: hidden;
			text-overflow: ellipsis;
			color: var(--text-muted);
			font-size: var(--fs-detail);
		}

		.row[aria-expanded='true'] .meta {
			white-space: normal;
		}

		.meta .cell {
			display: inline;
		}

		.meta .cell.album::before {
			content: ' · ';
		}
	}

	/* Phone: state and chevron share the first line, then the title, then artist · album.
	   The detail drops the gutter column; each attempt's time leads its own reading. */
	/* v42 (F32): a finger needs a 44px target; a mouse keeps the dense row. */
	@media (pointer: coarse) {
		.row,
		.action {
			min-height: 2.75rem;
		}
	}

	@media (max-width: 640px) {
		.row {
			grid-template-columns: minmax(0, 1fr) var(--col-lead);
			grid-template-areas:
				'state chevron'
				'title chevron'
				'meta chevron';
			row-gap: 0.125rem;
		}

		.cell.state {
			padding-left: 0;
		}

		.detail,
		.history,
		.timeline,
		.entry {
			grid-template-columns: minmax(0, 1fr);
		}

		.detail > *,
		.history > *,
		.entry > .when,
		.entry-body {
			grid-column: 1;
		}

		.entry > .when {
			margin-left: 0;
		}

		.action + .action.danger {
			margin-left: 0;
		}

		/* A phone can't fit the unit on one line; it wraps inside itself instead. */
		.facts {
			flex-wrap: wrap;
			white-space: normal;
		}
	}
</style>
