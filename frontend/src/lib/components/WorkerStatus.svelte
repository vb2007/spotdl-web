<script lang="ts">
	import { onMount } from 'svelte';
	import * as api from '$lib/api';
	import { worker } from '$lib/stores/worker';
	import { confirmAction, keepFocus } from '$lib/stores/confirm';
	import Countdown from '$lib/components/Countdown.svelte';

	// The admin's worker controls on /settings (v25). Rendered for the admin only (v43,
	// F17); the server-side require_admin gate on these endpoints is the real enforcement.
	// v43 (F30): the state is said in words and each button names its action. No
	// aria-pressed toggle, which read "resume, pressed" while paused.

	const { status } = worker;

	let busy = $state(false);
	let error = $state('');
	let note = $state('');
	// The pause/resume button. Its branch swaps on every toggle, and the hold row (with
	// "release now") goes when the hold does, so focus is put back here afterwards.
	let toggleButton: HTMLButtonElement | undefined = $state();
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
		return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}

	// One fixed sentence per state for assistive technology: the ticking countdown beside
	// it is aria-hidden, so the live region never re-announces every second (F07's lesson).
	const announcement = $derived(
		$status === null
			? ''
			: [
					paused ? 'Downloads paused.' : null,
					holdUntil ? `Holding after repeated rate limits until ${clockTime(holdUntil)}.` : null,
					!paused && !holdUntil ? 'Downloads running.' : null
				]
					.filter(Boolean)
					.join(' ')
	);

	async function run(action: () => Promise<void>) {
		busy = true;
		error = '';
		note = '';
		try {
			await action();
		} catch (err) {
			error = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
		} finally {
			busy = false;
		}
		await keepFocus(toggleButton);
	}

	// v43 (A4): pausing stops every user's downloads until someone resumes, so it asks.
	async function handlePause() {
		const confirmed = await confirmAction({
			title: 'Pause all downloads?',
			body:
				'Nothing new starts, for any user, until you resume. A download already running ' +
				'finishes; tracks that come due meanwhile are held and tried again later.',
			confirmLabel: 'pause downloads',
			cancelLabel: 'keep running'
		});
		if (!confirmed) return;
		// The poll is up to 5s old: re-read before deciding. Pausing twice is harmless, so a
		// failed re-read just falls back to the last poll.
		await worker.refresh().catch(() => {});
		// Paused meanwhile (another tab): nothing left to do, and the button has swapped.
		if (paused) {
			note = 'Downloads were already paused.';
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
			title: 'Release the hold now?',
			body:
				(paused
					? 'The hold ends now. Downloads stay paused until you resume them, and then start ' +
						'while YouTube may still be rate-limiting this server.'
					: 'Tracks that are due start again on the next pass, while YouTube may still be ' +
						'rate-limiting this server, which is what the hold protects against.') +
				(until ? ` It clears on its own at ${clockTime(until)}.` : ''),
			confirmLabel: 'release now',
			cancelLabel: 'keep holding'
		});
		if (!confirmed) return;
		// The question can outlive the hold. Releasing then would only reset the failure streak
		// a fresh run of rate limits is building, delaying the next hold. The poll is up to 5s
		// old, so re-read first. The release endpoint checks nothing itself, so without a
		// fresh reading nothing is released.
		try {
			await worker.refresh();
		} catch (err) {
			error = `Couldn't check the hold first (${err instanceof api.ApiError ? err.message : 'no connection'}); nothing was released.`;
			await keepFocus(toggleButton);
			return;
		}
		now = Date.now();
		if (!holdUntil || holdUntil !== until) {
			// Ended, or ended and a new hold began: the question was about the old one.
			note = holdUntil
				? 'A new hold began while you were deciding; nothing was released.'
				: 'The hold had already ended; nothing was released.';
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
			readError = err instanceof api.ApiError ? err.message : 'Could not reach the server.';
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
			<p class="form-error">
				Couldn't read the worker: {readError}. Trying again every few seconds.
			</p>
		{:else}
			<p class="state cond-idle">Reading the worker…</p>
		{/if}
	{:else}
		<div class="row">
			<div class="state-text">
				{#if paused}
					<p class="state cond-fail">Downloads paused</p>
					<p class="note">Nothing new starts, for anyone, until you resume.</p>
				{:else if !holdUntil}
					<p class="state cond-idle">Downloads running</p>
					<p class="note">Tracks start as they come due, one at a time.</p>
				{/if}
			</div>
			{#if paused}
				<button
					bind:this={toggleButton}
					type="button"
					class="btn"
					disabled={busy}
					onclick={handleResume}>resume downloads</button
				>
			{:else}
				<button
					bind:this={toggleButton}
					type="button"
					class="btn"
					disabled={busy}
					onclick={handlePause}>pause downloads</button
				>
			{/if}
		</div>

		{#if holdUntil}
			<div class="row hold">
				<div class="state-text">
					<p class="state cond-waiting">
						Holding until {clockTime(holdUntil)}
						<span aria-hidden="true"
							>· <Countdown
								scheduledAt={holdUntil}
								label="resumes in"
								dueLive={false}
								dueText="resuming…"
							/></span
						>
					</p>
					<p class="note">
						A deliberate pause after repeated rate limits. Waiting tracks keep their place.
					</p>
				</div>
				<button type="button" class="btn danger" disabled={busy} onclick={handleRelease}
					>release now</button
				>
			</div>
		{/if}
	{/if}

	{#if $status !== null && readError}
		<p class="note">Couldn't refresh ({readError}); showing the last reading.</p>
	{/if}
	<p class="note" role="status">{note}</p>
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

	.note {
		font-size: var(--fs-detail);
		color: var(--text-muted);
	}
</style>
