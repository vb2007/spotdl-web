<script lang="ts">
	import { untrack } from 'svelte';
	import { SvelteMap, SvelteSet } from 'svelte/reactivity';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import { worker } from '$lib/stores/worker';
	import { link } from '$lib/stores/link';
	import { confirmAction, keepFocus } from '$lib/stores/confirm';
	import { failedRowNotices, rowNotices, showRowNotice } from '$lib/stores/rowNotices';
	import Countdown from '$lib/components/Countdown.svelte';
	import { kbRow, rowItemById } from '$lib/keyboard/lists';
	import { isTypingTarget } from '$lib/keyboard/registry';
	import {
		attemptPath,
		attemptVia,
		formatDuration,
		groupAttempts,
		pathLabel,
		relativeTime,
		summarizeVia
	} from '$lib/attempts';
	import * as m from '$lib/paraglide/messages';
	import { errorText } from '$lib/i18n/errors';
	import { counted, formatDateTime, formatNumber } from '$lib/i18n/format';
	import { trackStateLabel } from '$lib/i18n/labels';
	import type { TrackAttempt, TrackAttemptOutcome, TrackState } from '$lib/api';
	import type { LiveTrack } from '$lib/stores/queue';

	// v54 (U1): `elsewhere`, another user's track in the admin's all/others view: receiving, but
	// not for this viewer, so it reads idle, never amber (DESIGN.md §2).
	// v56 (A2): `jobCancelled`, the track's job was cancelled: a not-found track it left behind
	// can't be retried (the server answers 409 job_cancelled), so it offers no "retry now".
	let {
		track,
		jobId,
		isAdmin,
		elsewhere = false,
		jobCancelled = false
	}: {
		track: LiveTrack;
		jobId: string;
		isAdmin: boolean;
		elsewhere?: boolean;
		jobCancelled?: boolean;
	} = $props();

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

	// v41 (F21): a state reads with the same words the state-filter chips use (v46:
	// `trackStateLabel`, shared with them), and none of them truncates in the state column (F13).

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

	// v47 (F04/F05, DESIGN.md §2): amber is "receiving right now". With `/`'s link down the
	// row's state came from a snapshot that no longer updates, so a downloading row reads
	// idle until the link is back, as the Waterfall's lanes and the ambient field already do.
	let stateCond = $derived(
		track.state === 'downloading' && ($link !== 'live' || elsewhere)
			? 'cond-idle'
			: STATE_COND[track.state]
	);

	// The first thing the expanded view says: what this state means for the listener, in
	// plain words, with the next step where there is one (F24, F25). v46: message functions,
	// called at render time, so a language switch re-renders them.
	const STATUS_TEXT: Record<TrackState, () => string> = {
		pending: m.track_status_pending,
		queued: m.track_status_queued,
		downloading: m.track_status_downloading,
		completed: m.track_status_completed,
		waiting: m.track_status_waiting,
		lookup_failed: m.track_status_lookup_failed,
		skipped_duplicate: m.track_status_skipped_duplicate,
		cancelled: m.track_status_cancelled
	};

	const ATTEMPT_OUTCOME_LABEL: Record<TrackAttemptOutcome, () => string> = {
		completed: m.attempt_outcome_completed,
		failed: m.attempt_outcome_failed,
		cancelled: m.attempt_outcome_cancelled,
		skipped_duplicate: m.attempt_outcome_skipped_duplicate,
		held: m.attempt_outcome_held
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
	// "retry now" only. v56 (A2): the backend refuses its cancel too (track_states.py).
	const RETRYABLE_STATES = new Set<TrackState>(['waiting', 'lookup_failed']);
	// The only two states download_track ever sets `output_path` from (backend/app/tasks/
	// download.py) -- every other state never had a file, so the action simply doesn't
	// render rather than rendering and failing (v27's plan: "nothing for tracks without a
	// file"). A file deleted from disk after the fact still shows the button; that request
	// 404s and surfaces through the same notice as any other action error.
	const DOWNLOADABLE_STATES = new Set<TrackState>(['completed', 'skipped_duplicate']);

	let canRetry = $derived(RETRYABLE_STATES.has(track.state) && !jobCancelled);
	let canDownload = $derived(DOWNLOADABLE_STATES.has(track.state));
	let canCancel = $derived(CANCELLABLE_STATES.has(track.state));
	let rowButton: HTMLButtonElement | undefined = $state();
	// The collapsed row's notice line (see the markup): empty while the detail shows it.
	const collapsedNotice = $derived(expanded ? '' : (rowNotices.get(`track:${track.id}`) ?? ''));

	// v41 (F04, the countdown half): beat dispatches nothing while the breaker holds, so a
	// waiting track's real next try is the later of its own slot and the breaker's clear.
	let nextTry = $derived.by((): { at: string; heldByBreaker: boolean } | null => {
		if (track.state !== 'waiting' || !track.scheduled_at) return null;
		// v56 (A7): both on this browser's clock: the track's slot is the server's timestamp,
		// placed with the server's clock offset, and the breaker's clear comes from the
		// server's remaining time. Whether the hold runs is the server's answer (#63).
		const slot = api.serverToLocal(track.scheduled_at);
		const breakerUntil = $workerStatus?.breaker_active ? $workerStatus.breaker_clears_at : null;
		if (breakerUntil && Date.parse(breakerUntil) > Date.parse(slot)) {
			return { at: breakerUntil, heldByBreaker: true };
		}
		return { at: slot, heldByBreaker: false };
	});
	let workerPaused = $derived($workerStatus?.paused ?? false);

	let groups = $derived(groupAttempts(attempts));
	let lastPath = $derived.by(() => {
		const reached = attempts.filter(
			(a) => a.network_path !== null || a.proxy_id !== null || a.proxy_label !== null
		);
		if (!reached.length) return null;
		// The strip names the family; the proxy's address is in the timeline's own entry.
		return pathLabel(attemptPath(reached[reached.length - 1]));
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
			attemptsError = errorText(err, m.track_history_load_failed);
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
		// v45: this Esc was for the time, not for the keyboard's "close the row" -- unless a
		// dialog is open or a field has focus, whose Esc it must never take.
		// And only while keyboard focus is in this track (or nowhere): focus on another row
		// keeps its own Esc.
		const focusRow = document.activeElement?.closest<HTMLElement>('[data-kb-row]');
		const focusHere =
			document.activeElement === document.body || focusRow?.dataset.kbRow === track.id;
		const elsewhere =
			!focusHere || document.querySelector('dialog[open]') !== null || isTypingTarget(e.target);
		if (!elsewhere && !dismissedTimes.has(hoveredTime)) e.preventDefault();
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

	// The fields `toLocaleString()` shows by default, in the interface's language.
	function formatTimestamp(value: string): string {
		return formatDateTime(value, {
			year: 'numeric',
			month: 'numeric',
			day: 'numeric',
			hour: 'numeric',
			minute: '2-digit',
			second: '2-digit'
		});
	}

	// Per-row transient feedback (e.g. "held behind the global pause"), kept in the rowNotices
	// store (v43) so it outlives a remount and is cleared by queue.reset().
	function showNotice(text: string, failed = false) {
		showRowNotice(`track:${track.id}`, text, failed);
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
	// One question and its server re-read at a time: a second press meanwhile is ignored.
	let handleCancelRunning = false;
	async function handleCancel() {
		if (handleCancelRunning) return;
		handleCancelRunning = true;
		try {
			await handleCancelFlow();
		} finally {
			handleCancelRunning = false;
		}
	}

	async function handleCancelFlow() {
		const session = queue.getResetCount();
		const askedState = track.state;
		const artists = track.artists?.join(', ');
		const confirmed = await confirmAction({
			title: m.track_cancel_title(),
			subject: [track.title ?? m.track_unknown_title(), artists].filter(Boolean).join(' — '),
			body:
				track.state === 'downloading' ? m.track_cancel_body_downloading() : m.track_cancel_body(),
			confirmLabel: m.track_cancel_confirm(),
			cancelLabel: m.track_cancel_keep()
		});
		// This row's own controls, or (remounted by a list reload meanwhile) the list's heading.
		// A row remounted meanwhile (a reload) is found again by id (v45), else the list's heading.
		const landing = () =>
			destroyed ? (rowItemById(track.id) ?? document.getElementById('queue-heading')) : rowButton;
		// Kept or Esc: "cancel track" may have gone meanwhile (the track settled).
		if (!confirmed) return keepFocus(landing());
		// Another identity took over meanwhile: this answer belongs to the previous session.
		if (queue.getResetCount() !== session) return;
		// The server's current state decides, not this row's: the row may be stale (its stream
		// down, or remounted with old props). It also says whether the cancel lands mid-download,
		// which the notices below need. v56 (A3): one read of this track alone, where it used to
		// be up to 1000 of the job's.
		let current: TrackState | null | undefined;
		try {
			const state = (await api.getTrack(track.id)).state;
			current = CANCELLABLE_STATES.has(state) ? state : null;
		} catch {
			current = undefined;
		}
		if (queue.getResetCount() !== session) return;
		if (current === undefined || current === null) {
			// The notice map outlives this row, so a remounted (collapsed) row shows it too.
			showNotice(
				current === undefined
					? m.track_notice_not_cancelled_unchecked()
					: m.track_notice_not_cancelled_settled()
			);
			return keepFocus(landing());
		}
		const wasDownloading = current === 'downloading';
		// The question was worded from this row's state; the server's may have moved on.
		const askedDownloading = askedState === 'downloading';
		const seenAttempts = attempts.length;
		try {
			await queue.cancelTrack(track.id, jobId);
			// Same reason as above: the worker records the cancelled attempt only once its
			// download call returns, seconds later. Re-read a few times, bounded, until the
			// newest attempt is that cancel.
			if (wasDownloading && !destroyed) {
				awaitCancelledAttempt(seenAttempts, [3000, 5000, 7000, 15000, 30000]);
			}
			if (wasDownloading && !askedDownloading && queue.getResetCount() === session) {
				showNotice(m.track_notice_cancelled_while_downloading());
			}
		} catch (err) {
			// A session reset meanwhile: the answer belongs to the previous identity.
			if (queue.getResetCount() === session) {
				// v56 (A2): it settled between the read above and the cancel; the server left it.
				if (err instanceof api.ApiError && err.code === 'track_not_cancellable')
					showNotice(m.track_notice_not_cancelled_settled());
				else showNotice(errorText(err, m.track_notice_cancel_failed), true);
			}
		}
		// "cancel track" leaves with the cancellable state: land on the row itself.
		await keepFocus(landing());
	}

	// v47: shown only to the session that asked (the reset count, as cancel's).
	async function handleRetry() {
		const session = queue.getResetCount();
		try {
			const { breakerHeld } = await queue.retryTrack(track.id, jobId);
			if (queue.getResetCount() !== session) return;
			showNotice(breakerHeld ? m.track_notice_retry_held() : m.track_notice_retry_queued());
		} catch (err) {
			// v56: a second "retry now" in one ladder step (A8), or a track under a cancelled job
			// (A2), is a rule, not a failure.
			const refused =
				err instanceof api.ApiError &&
				(err.code === 'retry_cooldown' || err.code === 'job_cancelled');
			if (queue.getResetCount() === session)
				showNotice(errorText(err, m.track_notice_retry_failed), !refused);
		}
	}

	// v45: `e` (owner's choice): the history stays shown whenever an admin's track is open, as
	// v41 designed; `e` opens the track if it's closed, then shows every collapsed repeat, or
	// hides them all once any is shown.
	function toggleRepeats() {
		if (!expanded || attemptsLoadedFor === null) {
			// The history loads after the row opens: its repeats open when it arrives.
			if (!expanded) toggleExpanded();
			openRepeatsOnLoad = true;
			return;
		}
		const runs = groups.filter((g) => g.attempts.length > 1).map((g) => g.key);
		if (runs.some((key) => openRuns.has(key))) openRuns.clear();
		else for (const key of runs) openRuns.add(key);
	}
	let openRepeatsOnLoad = $state(false);
	$effect(() => {
		if (!openRepeatsOnLoad) return;
		// Closed again, or the history couldn't load: the request lapses.
		if (!expanded || (attemptsError !== null && !attemptsLoading)) {
			openRepeatsOnLoad = false;
			return;
		}
		if (attemptsLoadedFor === null) return;
		openRepeatsOnLoad = false;
		untrack(() => {
			for (const g of groups) if (g.attempts.length > 1) openRuns.add(g.key);
		});
	});

	// v45: the row's keys (`r`, `d`, `x`, `e`), each only where its action is offered.
	const keys = kbRow({
		retry: () => canRetry && (handleRetry(), true),
		download: () => canDownload && (handleDownload(), true),
		cancel: () => canCancel && (handleCancel(), true),
		repeats: () => isAdmin && (toggleRepeats(), true)
	});

	// v35 (e): probe first, then let the browser download the real URL itself, so a whole
	// FLAC is streamed to disk instead of buffered into a Blob in tab memory. The empty
	// `download` attribute keeps the page in place and takes the filename from the
	// response's Content-Disposition.
	async function handleDownload() {
		const session = queue.getResetCount();
		try {
			await api.checkTrackFile(track.id);
		} catch (err) {
			if (queue.getResetCount() === session)
				showNotice(errorText(err, m.track_notice_download_failed), true);
			return;
		}
		if (queue.getResetCount() !== session) return;
		const anchor = document.createElement('a');
		anchor.href = api.trackFileUrl(track.id);
		anchor.download = '';
		document.body.appendChild(anchor);
		anchor.click();
		anchor.remove();
	}
</script>

<!-- Capture phase: it runs before the shortcut registry's own window listener, so an Esc that
     dismisses a hovered time is claimed (v45) before the registry would close the row. -->
<svelte:window onkeydowncapture={hoveredTime !== null ? dismissTimeOnEscape : undefined} />

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
			// v45: dismissing the time uses up this Esc; a second one closes the row.
			if (!dismissedTimes.has(key)) e.preventDefault();
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

<li data-kb-row={track.id} {@attach keys}>
	<button
		bind:this={rowButton}
		type="button"
		class="row"
		data-kb-item
		onclick={toggleExpanded}
		aria-expanded={expanded}
		aria-controls={detailId}
	>
		<span class="cell state {stateCond} mono"
			>{trackStateLabel(
				track.state
			)}{#if track.state === 'downloading' && track.progress !== undefined}<span class="pct"
					>&nbsp;{track.progress}%</span
				>{/if}</span
		>
		<span class="cell title" title={track.title ?? undefined}
			>{track.title ?? m.track_unknown_title()}</span
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
				<span class="status {stateCond}">{STATUS_TEXT[track.state]()}</span>
				{#if track.state === 'downloading' && track.progress !== undefined}
					<span
						class="progress"
						role="progressbar"
						aria-label={m.track_download_progress()}
						aria-valuemin={0}
						aria-valuemax={100}
						aria-valuenow={track.progress}
					>
						<span
							class="progress-fill"
							class:stale={$link !== 'live' || elsewhere}
							style:transform="scaleX({track.progress / 100})"
						></span>
					</span>
					<span class="fact mono">{track.progress}%</span>
				{/if}
				{#if nextTry}
					<span class="fact"
						><Countdown
							scheduledAt={nextTry.at}
							label={m.track_next_try_in()}
							dueText={workerPaused ? m.track_due() : m.track_due_next_pass()}
						/></span
					>
					{#if nextTry.heldByBreaker}
						<span class="fact quiet">{m.track_after_pause_clears()}</span>
					{/if}
					{#if workerPaused}
						<span class="fact quiet">{m.track_downloads_paused()}</span>
					{/if}
				{/if}
				{#if isAdmin && track.state !== 'skipped_duplicate'}
					<!-- One unit: the counts and the path wrap together, never apart. -->
					<span class="facts">
						<span class="fact mono"
							><span class="key">{m.track_fact_attempts()}</span>
							{formatNumber(track.attempts_made)}</span
						>
						<span class="fact mono"
							><span class="key">{m.track_fact_failed()}</span>
							{formatNumber(track.failure_count)}</span
						>
						{#if lastPath}
							<span class="fact mono"
								><span class="key">{m.track_fact_last_path()}</span> {lastPath}</span
							>
						{/if}
					</span>
				{/if}
			</div>

			{#if canRetry || canDownload || canCancel}
				<div class="actions" role="group" aria-label={m.track_actions()}>
					{#if canRetry}
						<button type="button" class="action" onclick={handleRetry}>{m.track_retry_now()}</button
						>
					{/if}
					{#if canDownload}
						<button type="button" class="action" onclick={handleDownload}
							>{m.track_download()}</button
						>
					{/if}
					{#if canCancel}
						<button type="button" class="action danger" onclick={handleCancel}
							>{m.track_cancel_confirm()}</button
						>
					{/if}
				</div>
			{/if}
			<p class="notice" class:failed={failedRowNotices.has(`track:${track.id}`)} role="status">
				{rowNotices.get(`track:${track.id}`) ?? ''}
			</p>

			{#if isAdmin}
				<div class="history">
					{#if attemptsError && attemptsLoadedFor !== null}
						<!-- A failed re-read never hides the history already loaded. -->
						<p class="history-status history-error">
							{m.track_history_refresh_failed({ error: attemptsError })}
						</p>
					{/if}
					{#if attemptsLoading && attemptsLoadedFor === null}
						<p class="history-status">{m.track_history_loading()}</p>
					{:else if attemptsError && attemptsLoadedFor === null}
						<p class="history-status history-error">{attemptsError}</p>
					{:else if attempts.length === 0}
						<p class="history-status">{m.track_history_empty()}</p>
					{:else}
						<p class="history-heading mono">{m.track_history_heading()}</p>
						<ol class="timeline" aria-label={m.track_history_label()}>
							{#each groups as group (group.key)}
								{@const head = group.attempts[0]}
								{@const run = group.attempts.length}
								{@const message = head.error_message}
								<li class="entry">
									{@render when(head.finished_at, head.id)}
									<div class="entry-body">
										<p class="reading mono">
											{#if run > 1}<span class="times">×{formatNumber(run)}</span>{/if}
											<span class="outcome {outcomeCond(head)}"
												>{ATTEMPT_OUTCOME_LABEL[head.outcome]()}</span
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
												lang="en"
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
													>{openMessages.has(group.key)
														? m.track_message_less()
														: m.track_message_full()}</button
												>
											{/if}
										{/if}
										{#if head.warning_message}
											<p class="note">
												<span class="note-tag mono">{m.track_note()}</span>
												<span class="note-text mono" lang="en">{head.warning_message}</span>
											</p>
										{/if}
										{#if run > 1}
											<button
												type="button"
												class="inline-toggle"
												aria-expanded={openRuns.has(group.key)}
												aria-controls="run-{group.key}"
												onclick={() => toggleIn(openRuns, group.key)}
												>{openRuns.has(group.key)
													? m.track_repeats_hide()
													: m.track_repeats_show(counted(run))}</button
											>
											{#if openRuns.has(group.key)}
												<ol class="run" id="run-{group.key}" aria-label={m.track_repeats_label()}>
													{#each group.attempts as attempt (attempt.id)}
														<li class="run-item mono">
															{@render when(attempt.finished_at, `run-${attempt.id}`)}
															<span class="via">{attemptVia(attempt)}</span>
															{#if attempt.outcome !== 'held'}
																<span class="dur">{formatDuration(attempt.duration_seconds)}</span>
															{/if}
															<span class="quiet">{m.track_same_reading()}</span>
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
						<p class="last-error mono">
							<span class="key">{m.track_last_error()}</span>
							<!-- v47 (WCAG 3.1.2): raw worker text stays English (v46), and says so. -->
							<span lang="en">{track.last_error}</span>
						</p>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
	<!-- v43: a collapsed row's own notice (a remount after a list reload collapses it, and the
	     cancel's outcome must still be seen and heard). Always present, so its text is announced;
	     while expanded the notice lives in the detail instead. -->
	<p
		class="notice collapsed"
		class:failed={collapsedNotice !== '' && failedRowNotices.has(`track:${track.id}`)}
		role="status"
	>
		{collapsedNotice}
	</p>
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
	/* v47: only where a pointer hovers; on touch a tapped row kept the underline. */
	@media (hover: hover) {
		.row:hover .cell.title {
			text-decoration: underline;
			text-decoration-color: var(--text-muted);
			text-underline-offset: 0.2em;
		}
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

	/* v47: level with the title's first line, not the middle of a wrapped title. */
	.chevron {
		justify-self: center;
		align-self: start;
		margin-top: calc(0.75lh - 0.2rem);
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
		font-weight: var(--fw-medium);
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

	.progress-fill.stale {
		background: var(--line-bright);
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
		font-family: var(--font-sans);
		font-size: var(--fs-detail);
		font-weight: var(--fw-medium);
		line-height: 1.25;
		color: var(--text-muted);
		cursor: pointer;
	}

	/* v47: the one hover of a neutral control (DESIGN.md §2): --bg-3 under a --text-muted edge,
	   and only where a pointer hovers (on touch, a tapped button used to keep it). Focus is the
	   global ring alone; pressed is the --bg-3 fill. */
	@media (hover: hover) {
		.action:hover {
			background: var(--bg-3);
			border-color: var(--text-muted);
			color: var(--text-primary);
		}
	}

	.action:active {
		background: var(--bg-3);
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

	.action.danger:focus-visible,
	.action.danger:active {
		background: transparent;
		border-color: var(--fail);
		color: var(--fail);
	}

	@media (hover: hover) {
		.action.danger:hover {
			background: transparent;
			border-color: var(--fail);
			color: var(--fail);
		}
	}

	.notice.collapsed {
		padding: 0 var(--row-pad-x) var(--space-2);
	}

	.notice {
		color: var(--waiting);
		font-size: var(--fs-detail);
	}

	/* v47: a failure reads as one ("Couldn't retry: …"), not in the scheduling blue. */
	.notice.failed {
		color: var(--fail);
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

	/* v47: hover reveals only where a pointer hovers. On touch a tap pins it (above); a sticky
	   hover kept it on screen after a second tap had unpinned it. */
	@media (hover: hover) {
		.when:hover .abs {
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
	}

	/* Bridges the gap down to the button, so the pointer can move onto the tooltip without
	   losing it (WCAG 1.4.13, hoverable). */
	@media (hover: hover) {
		.when:hover .abs::after {
			content: '';
			position: absolute;
			left: 0;
			right: 0;
			top: 100%;
			height: calc(var(--space-1) + 2px);
		}
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
		font-weight: var(--fw-strong);
	}

	.outcome {
		font-weight: var(--fw-strong);
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

	/* Text-sized, but a 24px-tall hit area (WCAG 2.5.8) on every inline control; v47 (F32): a
	   finger gets 44px, like every other control on the row. */
	.inline-toggle {
		min-height: 1.5rem;
		background: none;
		border: none;
		padding: 0;
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
	@media (max-width: 60em) {
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

		/* v47: two lines before it is cut, so a several-artist track still shows its album
		   (one line hid "TRON: Legacy Reconfigured" behind four artists). */
		.meta {
			grid-area: meta;
			display: -webkit-box;
			-webkit-box-orient: vertical;
			-webkit-line-clamp: 2;
			line-clamp: 2;
			min-width: 0;
			overflow: hidden;
			color: var(--text-muted);
			font-size: var(--fs-detail);
		}

		.row[aria-expanded='true'] .meta {
			display: block;
			-webkit-line-clamp: unset;
			line-clamp: none;
		}

		/* v47: wrapping inside a cell too, so the two-line clamp (not the cells' nowrap) decides
		   where a long artist list or album is cut, with its ellipsis. */
		.meta .cell {
			display: inline;
			white-space: normal;
			overflow-wrap: anywhere;
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
		.action,
		.inline-toggle,
		.when {
			min-height: 2.75rem;
		}
	}

	@media (max-width: 40em) {
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
	/* v47: in a forced-colors theme (Windows High Contrast) a bar's fills were dropped to empty
	   outlines; a reading keeps its own colours, as /stats' charts already do. */
	@media (forced-colors: active) {
		.progress {
			forced-color-adjust: none;
		}
	}
</style>
