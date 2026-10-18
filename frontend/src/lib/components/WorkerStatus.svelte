<script lang="ts">
	import { onMount } from 'svelte';
	import * as api from '$lib/api';
	import { worker } from '$lib/stores/worker';
	import { confirmAction, keepFocus } from '$lib/stores/confirm';
	import Countdown from '$lib/components/Countdown.svelte';
	import * as m from '$lib/paraglide/messages';
	import { apiErrorText, errorText } from '$lib/i18n/errors';
	import { formatClock } from '$lib/i18n/format';

	// The admin's worker controls on /settings (v25). Rendered for the admin only (v43,
	// F17); the server-side require_admin gate on these endpoints is the real enforcement.
	// v43 (F30): the state is said in words and each button names its action. No
	// aria-pressed toggle, which read "resume, pressed" while paused.

	const { status } = worker;

	let busy = $state(false);
	let error = $state('');
	let note = $state('');
	// A note answers one press; it leaves after a while rather than outliving the state it
	// described.
	let noteTimer: ReturnType<typeof setTimeout> | undefined;
	$effect(() => {
		if (!note) return;
		clearTimeout(noteTimer);
		noteTimer = setTimeout(() => (note = ''), 8000);
		return () => clearTimeout(noteTimer);
	});
	// The pause/resume button. Its branch swaps on every toggle, and the hold row (with
	// "release now") goes when the hold does, so focus is put back here afterwards.
	let toggleButton: HTMLButtonElement | undefined = $state();
	// Left the page during a pre-action re-read: that answer no longer has a page to act for.
	let gone = false;
	$effect(() => () => {
		gone = true;
	});
	let now = $state(Date.now());

	const POLL_MS = 5000;

	const holdUntil = $derived(
		$status?.breaker_tripped_until != null &&
			new Date($status.breaker_tripped_until).getTime() > now
			? $status.breaker_tripped_until
			: null
	);
	const paused = $derived($status?.paused ?? false);

	function clockTime(iso: string): string {
		return formatClock(iso);
	}

	// One fixed sentence per state for assistive technology: the ticking countdown beside
	// it is aria-hidden, so the live region never re-announces every second (F07's lesson).
	// The live region speaks only once the state changes from what the page opened on, so a
	// visit doesn't announce "Downloads running." every time.
	const stateSentence = $derived(
		$status === null
			? ''
			: [
					paused ? m.worker_sentence_paused() : null,
					holdUntil ? m.worker_sentence_holding({ time: clockTime(holdUntil) }) : null,
					!paused && !holdUntil ? m.worker_sentence_running() : null
				]
					.filter(Boolean)
					.join(' ')
	);
	let firstSentence: string | null = null;
	let stateChanged = $state(false);
	$effect(() => {
		if (!stateSentence) return;
		if (firstSentence === null) firstSentence = stateSentence;
		else if (stateSentence !== firstSentence) stateChanged = true;
	});
	const announcement = $derived(stateChanged ? stateSentence : '');

	async function run(action: () => Promise<void>) {
		busy = true;
		error = '';
		note = '';
		try {
			await action();
		} catch (err) {
			error = errorText(err);
		} finally {
			busy = false;
		}
		await keepFocus(toggleButton);
	}

	// v43 (A4): pausing stops every user's downloads until someone resumes, so it asks.
	async function handlePause() {
		const confirmed = await confirmAction({
			title: m.worker_pause_confirm_title(),
			body: m.worker_pause_confirm_body(),
			confirmLabel: m.worker_pause(),
			cancelLabel: m.worker_pause_confirm_cancel()
		});
		// Kept or Esc: the trigger may have swapped meanwhile (another tab paused).
		if (!confirmed) return keepFocus(toggleButton);
		// The poll is up to 5s old: re-read before deciding. Pausing twice is harmless, so a
		// failed re-read just falls back to the last poll.
		busy = true;
		const fresh = await worker.refresh().catch(() => null);
		busy = false;
		if (gone) return;
		// Paused meanwhile (another tab): nothing left to do, and the button has swapped.
		if (fresh?.paused ?? paused) {
			note = m.worker_note_already_paused();
			await keepFocus(toggleButton);
			return;
		}
		await run(() => worker.pause());
	}

	async function handleResume() {
		await run(() => worker.resume());
	}

	// v43 (A4): releasing early sends downloads straight back into an active rate limit,
	// the one exposure this app exists to avoid.
	async function handleRelease() {
		const until = holdUntil;
		const confirmed = await confirmAction({
			title: m.worker_release_confirm_title(),
			// Whole sentences, joined: each is a message of its own.
			body:
				(paused
					? m.worker_release_confirm_body_paused()
					: m.worker_release_confirm_body_running()) +
				(until ? ` ${m.worker_release_confirm_clears({ time: clockTime(until) })}` : ''),
			confirmLabel: m.worker_release(),
			cancelLabel: m.worker_release_confirm_cancel()
		});
		// Kept or Esc: the hold row (and its button) may have gone meanwhile.
		if (!confirmed) return keepFocus(toggleButton);
		// The question can outlive the hold. Releasing then would only reset the failure streak
		// a fresh run of failures is building, delaying the next hold. The poll is up to 5s
		// old, so re-read first. The release endpoint checks nothing itself, so without a
		// fresh reading nothing is released.
		busy = true;
		let fresh: api.WorkerStatus;
		try {
			fresh = await worker.refresh();
		} catch (err) {
			busy = false;
			error = m.worker_release_check_failed({
				reason: err instanceof api.ApiError ? apiErrorText(err) : m.worker_no_connection()
			});
			await keepFocus(toggleButton);
			return;
		}
		busy = false;
		if (gone) return;
		now = Date.now();
		// Decided on what this read returned, not the store (a poll may have overtaken it).
		const freshHold =
			fresh.breaker_tripped_until !== null &&
			new Date(fresh.breaker_tripped_until).getTime() > Date.now()
				? fresh.breaker_tripped_until
				: null;
		if (!freshHold || freshHold !== until) {
			// Ended, or ended and a new hold began: the question was about the old one.
			note = freshHold ? m.worker_note_new_hold() : m.worker_note_hold_ended();
			await keepFocus(toggleButton);
			return;
		}
		await run(() => worker.release());
	}

	// A failed read is said, never a silent "Reading…" forever (F17's lesson, admin side). The
	// poll keeps trying; the last good reading stays on screen meanwhile.
	let readError = $state('');
	async function poll() {
		try {
			await worker.refresh();
			readError = '';
		} catch (err) {
			readError = errorText(err);
		}
	}

	onMount(() => {
		poll();
		// No dedicated SSE event exists for worker/breaker state (v10 plan) -- a plain
		// poll is the simplest way for a naturally-tripping breaker (5 consecutive
		// AudioProviderErrors, no user action involved) to still surface here without
		// the user having to reload.
		const id = setInterval(() => {
			now = Date.now();
			poll();
		}, POLL_MS);
		return () => clearInterval(id);
	});
</script>

<div class="worker">
	<p class="sr-only" role="status">{announcement}</p>

	{#if $status === null}
		{#if readError}
			<p class="form-error">{m.worker_read_failed({ error: readError })}</p>
		{:else}
			<p class="state cond-idle">{m.worker_reading()}</p>
		{/if}
	{:else}
		<div class="row">
			<div class="state-text">
				{#if paused}
					<p class="state cond-fail">{m.worker_state_paused()}</p>
					<p class="note">{m.worker_state_paused_note()}</p>
				{:else if !holdUntil}
					<p class="state cond-idle">{m.worker_state_running()}</p>
					<p class="note">{m.worker_state_running_note()}</p>
				{/if}
			</div>
			{#if paused}
				<button
					bind:this={toggleButton}
					type="button"
					class="btn"
					disabled={busy}
					onclick={handleResume}>{m.worker_resume()}</button
				>
			{:else}
				<button
					bind:this={toggleButton}
					type="button"
					class="btn"
					disabled={busy}
					onclick={handlePause}>{m.worker_pause()}</button
				>
			{/if}
		</div>

		{#if holdUntil}
			<div class="row hold">
				<div class="state-text">
					<p class="state cond-waiting">
						{m.worker_holding_until({ time: clockTime(holdUntil) })}
						<span aria-hidden="true"
							>· <Countdown
								scheduledAt={holdUntil}
								label={paused ? m.worker_countdown_clears() : m.worker_countdown_resumes()}
								dueLive={false}
								dueText={m.worker_countdown_due()}
							/></span
						>
					</p>
					<p class="note">{m.worker_hold_note()}</p>
				</div>
				<button type="button" class="btn danger" disabled={busy} onclick={handleRelease}
					>{m.worker_release()}</button
				>
			</div>
		{/if}
	{/if}

	{#if $status !== null && readError}
		<p class="note">{m.worker_refresh_failed({ error: readError })}</p>
	{/if}
	<p class="note" role="status">{note}</p>
	<!-- A read failure is said to assistive technology too (the visible lines above are not
	     live regions); fixed text, so a failing poll isn't re-announced every 5s. -->
	<p class="sr-only" role="alert">{readError ? m.worker_read_failed_alert() : ''}</p>
	<p class="form-error" role="alert">{error}</p>
</div>

<style>
	.worker {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--space-3) var(--space-4);
	}

	.hold {
		padding-top: var(--space-3);
		border-top: 1px solid var(--line);
	}

	.state-text {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}

	.state {
		font-family: var(--font-mono);
		font-size: var(--fs-detail);
		font-weight: var(--fw-medium);
	}

	/* Live regions present at rest (so their text is announced) take no room while empty. */
	.worker > .note:empty,
	.worker > .form-error:empty {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
	}

	.note {
		font-size: var(--fs-detail);
		color: var(--text-muted);
	}
</style>
