<script lang="ts">
	import { worker } from '$lib/stores/worker';
	import Countdown from '$lib/components/Countdown.svelte';

	// v25: the dashboard-visible half of what used to be the full WorkerStatus panel --
	// read-only (pause/resume and breaker-release live on /settings, admin-only).
	// v42 (v39 outcome 3): operator detail, so the page renders it for the admin only; a
	// non-admin learns about a hold from the Waterfall's own plain status line instead.
	// The 5s poll moved to the page, which every user needs (the Waterfall and TrackRow's
	// breaker-aware countdown read the same store).
	const { status } = worker;

	let breakerUntil = $derived(
		$status?.breaker_tripped_until != null &&
			new Date($status.breaker_tripped_until).getTime() > Date.now()
			? $status.breaker_tripped_until
			: null
	);
	let paused = $derived($status?.paused ?? false);

	function clockTime(iso: string): string {
		return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}

	// v42 (F07): the live region holds one fixed sentence per state, so it speaks when the
	// state changes, never on the countdown's per-second tick.
	// A pause outranks a hold, as on the Waterfall: nothing dispatches until a human
	// resumes, even after the breaker clears, so it is the binding explanation.
	let announcement = $derived(
		paused
			? 'Worker: paused'
			: breakerUntil
				? `Worker: breaker holding until ${clockTime(breakerUntil)}`
				: 'Worker: ready'
	);
</script>

<div class="pill mono">
	<span class="sr-only" role="status">{announcement}</span>
	<!-- v42 (F06): a tripped breaker is expected and self-healing, so it reads in the
	     waiting blue, never the terminal red. A pause stays red: it holds until a human
	     resumes it. -->
	{#if paused}
		<span class="cond-fail" aria-hidden="true">receiver paused</span>
	{:else if breakerUntil}
		<span class="cond-waiting" aria-hidden="true">breaker holding</span>
		<span aria-hidden="true"
			><Countdown
				scheduledAt={breakerUntil}
				label="clears in"
				dueLive={false}
				dueText="clearing…"
			/></span
		>
	{:else}
		<span class="cond-idle" aria-hidden="true">worker ready</span>
	{/if}
</div>

<style>
	/* Quiet by default (--text-muted via .cond-idle) -- amber is reserved for something
	   genuinely live right now (DESIGN.md §2), and "not paused, breaker clear" is not
	   that. */
	.pill {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: var(--space-2);
		font-size: var(--fs-meta);
	}
</style>
