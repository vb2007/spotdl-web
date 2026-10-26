<script lang="ts">
	import { worker } from '$lib/stores/worker';
	import Countdown from '$lib/components/Countdown.svelte';
	import * as m from '$lib/paraglide/messages';
	import { formatClock } from '$lib/i18n/format';

	// v25: the dashboard-visible half of what used to be the full WorkerStatus panel --
	// read-only (pause/resume and breaker-release live on /settings, admin-only).
	// v42 (v39 outcome 3): operator detail, so the page renders it for the admin only; a
	// non-admin learns about a hold from the Waterfall's own plain status line instead.
	// The 5s poll moved to the page, which every user needs (the Waterfall and TrackRow's
	// breaker-aware countdown read the same store).
	const { status } = worker;

	// v56 (A7): the server says whether the hold runs and for how long; the countdown runs on
	// this browser's clock from that (api.ts's `breaker_clears_at`), so a skewed clock no
	// longer shows a wrong time, or no hold at all.
	let breakerUntil = $derived($status?.breaker_active ? $status.breaker_clears_at : null);
	let paused = $derived($status?.paused ?? false);

	// v42 (F07): the live region holds one fixed sentence per state, so it speaks when the
	// state changes, never on the countdown's per-second tick.
	// A pause outranks a hold, as on the Waterfall: nothing dispatches until a human
	// resumes, even after the breaker clears, so it is the binding explanation.
	let announcement = $derived(
		paused
			? m.pill_announce_paused()
			: breakerUntil
				? m.pill_announce_holding({ time: formatClock(breakerUntil) })
				: m.pill_announce_ready()
	);
</script>

<!-- Nothing until the first poll lands: "worker ready" on no data would be a guess. -->
{#if $status}
	<div class="pill mono">
		<span class="sr-only" role="status">{announcement}</span>
		<!-- v42 (F06): a tripped breaker is expected and self-healing, so it reads in the
	     waiting blue, never the terminal red. A pause stays red: it holds until a human
	     resumes it. -->
		{#if paused}
			<span class="cond-fail" aria-hidden="true">{m.pill_paused()}</span>
		{:else if breakerUntil}
			<span class="cond-waiting" aria-hidden="true">{m.pill_holding()}</span>
			<span aria-hidden="true"
				><Countdown
					scheduledAt={breakerUntil}
					label={m.pill_clears_in()}
					dueText={m.pill_clearing()}
				/></span
			>
		{:else}
			<span class="cond-idle" aria-hidden="true">{m.pill_ready()}</span>
		{/if}
	</div>
{/if}

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
