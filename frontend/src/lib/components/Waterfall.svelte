<script lang="ts">
	import type { LiveTrack } from '$lib/stores/queue';
	import type { LinkState } from '$lib/stores/link';
	import Countdown from '$lib/components/Countdown.svelte';
	import * as m from '$lib/paraglide/messages';
	import { counted, formatClock } from '$lib/i18n/format';

	/** v20: `busy` reflects `GET /api/worker/status`'s global `busy` flag -- since
	 * `worker-dl` runs `--concurrency=1`, an idle-for-me waterfall during someone else's
	 * download is completely normal, not a sign anything is stuck. Distinct from
	 * `tracks.length > 0` (this caller's own active track, which always takes the
	 * amber-signal treatment per DESIGN.md §2's exclusivity rule) -- busy-elsewhere never
	 * uses --signal, only a neutral note, since it isn't live *for this session*.
	 *
	 * v42 (F04, F05): the idle line tells the truth about *why* nothing is receiving.
	 * `breakerUntil` is set only while the breaker is actually holding (the caller drops a
	 * past timestamp), `paused` is the worker's own flag, and `link` is this page's SSE
	 * stream: while it is down, nothing on the panel can be trusted to be current. */
	let {
		tracks,
		busy = false,
		link = 'live',
		breakerUntil = null,
		paused = false,
		isAdmin = false
	}: {
		tracks: LiveTrack[];
		busy?: boolean;
		link?: LinkState;
		breakerUntil?: string | null;
		paused?: boolean;
		isAdmin?: boolean;
	} = $props();

	// A quiet noise floor, not a dead flatline — a real spectrum scope stays alive
	// (low, uneven, still moving) when nothing is transmitting; "no signal" should
	// read as "listening," never as "off."
	const noiseBars = Array.from({ length: 40 }, () => ({
		delay: Math.random() * 2,
		base: 0.1 + Math.random() * 0.3
	}));

	type Idle = 'reconnecting' | 'connecting' | 'paused' | 'holding' | 'busy' | 'clear';

	// Order matters: a lost link outranks everything (the rest may be stale), and a hold or
	// a pause explains an idle receiver better than "busy elsewhere" or "nothing".
	let idle: Idle = $derived(
		link === 'reconnecting'
			? 'reconnecting'
			: link === 'connecting'
				? 'connecting'
				: paused
					? 'paused'
					: breakerUntil
						? 'holding'
						: busy
							? 'busy'
							: 'clear'
	);

	// The floor stops moving while the receiver is deliberately not listening (a hold or a
	// pause) or can't hear (no link): motion only ever means "listening".
	let still = $derived(idle === 'reconnecting' || idle === 'paused' || idle === 'holding');

	// One fixed sentence per state, so a screen reader hears a hold or pause start and end
	// (the admin-only pill is the only other place that says it) and never a countdown tick.
	let heldSentence = $derived(
		idle === 'holding' && breakerUntil
			? m.waterfall_announce_holding({ time: formatClock(breakerUntil) })
			: idle === 'paused'
				? m.waterfall_announce_paused()
				: null
	);
	// The region keeps the hold's sentence while it lasts, then says it ended once: an
	// emptied live region announces nothing. A lost link is the masthead tell's to say.
	let announcement = $state('');
	let wasHeld = false;
	$effect(() => {
		if (heldSentence) {
			announcement = heldSentence;
			wasHeld = true;
		} else if (wasHeld && idle !== 'reconnecting' && idle !== 'connecting') {
			announcement = m.waterfall_announce_resumed();
			wasHeld = false;
		}
	});
</script>

<section
	class="panel waterfall"
	class:live={tracks.length > 0 && link === 'live'}
	class:held={tracks.length === 0 && idle === 'holding'}
	aria-labelledby="waterfall-heading"
>
	<div class="head">
		<h2 id="waterfall-heading" class="label">{m.waterfall_heading()}</h2>
		{#if tracks.length > 0 && link !== 'live'}
			<!-- Lanes without an open stream came from a REST snapshot (a reconnect's or the
			     page's fallback reload) and don't update: never amber, never "receiving". -->
			<span class="label stale"
				>{link === 'reconnecting' ? m.waterfall_stale_lost() : m.waterfall_stale_linking()}</span
			>
		{:else}
			<span class="label count">{m.waterfall_lanes(counted(tracks.length))}</span>
		{/if}
	</div>

	<span class="sr-only" role="status">{announcement}</span>

	{#if tracks.length === 0}
		<div class="idle" class:still>
			<div class="noise-floor" aria-hidden="true">
				{#each noiseBars as bar, i (i)}
					<span class="noise-bar" style:animation-delay="{bar.delay}s" style:--base={bar.base}
					></span>
				{/each}
			</div>
			{#if idle === 'holding' && breakerUntil}
				<!-- The countdown ticks every second, so it stays out of the accessibility tree;
				     the same fact is there once, as a fixed clock time (F07's lesson). -->
				<p class="status cond-waiting">
					<span class="label word">{m.waterfall_holding()}</span>
					<span aria-hidden="true"
						><Countdown
							scheduledAt={breakerUntil}
							label={m.waterfall_resumes_in()}
							dueText={m.waterfall_resuming()}
						/></span
					>
					<span class="sr-only">{m.waterfall_resume_at({ time: formatClock(breakerUntil) })}</span>
				</p>
				<p class="note">{m.waterfall_holding_note()}</p>
			{:else if idle === 'paused'}
				<p class="status"><span class="label word">{m.waterfall_paused()}</span></p>
				<p class="note">
					{isAdmin ? m.waterfall_paused_note_admin() : m.waterfall_paused_note_user()}
				</p>
			{:else if idle === 'reconnecting'}
				<p class="status cond-waiting">
					<span class="label word">{m.waterfall_reconnecting()}</span>
				</p>
				<p class="note">{m.waterfall_reconnecting_note()}</p>
			{:else if idle === 'connecting'}
				<p class="status"><span class="label word">{m.waterfall_connecting()}</span></p>
			{:else if idle === 'busy'}
				<p class="status"><span class="label word">{m.waterfall_busy()}</span></p>
			{:else}
				<p class="status"><span class="label word">{m.waterfall_clear()}</span></p>
			{/if}
		</div>
	{:else}
		<ul class="lanes" class:stale={link !== 'live'}>
			{#each tracks as track (track.id)}
				<li class="lane">
					<div class="meta">
						<span class="title" id="lane-title-{track.id}"
							>{track.title ?? m.waterfall_unknown_title()}</span
						>
						<span class="artist">{track.artists?.join(', ') ?? m.waterfall_unknown_artist()}</span>
					</div>
					<div
						class="meter well"
						role="progressbar"
						aria-labelledby="lane-title-{track.id}"
						aria-valuenow={track.progress}
						aria-valuetext={track.progress === undefined
							? m.waterfall_progress_unknown()
							: undefined}
						aria-valuemin={0}
						aria-valuemax={100}
					>
						<div class="fill" style:transform="scaleX({(track.progress ?? 0) / 100})"></div>
					</div>
					<!-- v47: a lane loaded from REST (a reload, a reconnect) has no reading until the
					     next progress event; it said "0%" for a track that may be 80% in. -->
					<span class="pct mono">{track.progress === undefined ? '—' : `${track.progress}%`}</span>
				</li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.waterfall {
		padding: var(--space-4) var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		/* Hero-marking top edge — neutral while idle, amber only while something is
		   genuinely live. Round-1 review flagged a constant amber border as spending
		   the one committed live-signal color on permanent chrome, diluting its
		   exclusive meaning ("something is live right now"); this restores that.
		   v42: a breaker hold takes the waiting edge, the same neutral -> condition
		   swap; a pause keeps the neutral one (it isn't scheduled). */
		border-top: 2px solid var(--line-bright);
	}

	.waterfall.live {
		border-top-color: var(--signal-dim);
	}

	.waterfall.held {
		border-top-color: var(--waiting-dim);
	}

	.head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--space-3);
	}

	.head .count {
		font-variant-numeric: tabular-nums;
	}

	.head .stale {
		color: var(--waiting);
		text-align: right;
	}

	.idle {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-5) 0 var(--space-4);
		text-align: center;
	}

	.noise-floor {
		display: flex;
		align-items: flex-end;
		gap: 2px;
		width: 100%;
		max-width: 24rem;
		height: 1.5rem;
		margin-bottom: var(--space-2);
		/* `transform-origin: bottom` keeps scaleY's math anchored to each bar's own
		   bottom edge, but very short (often just a few px) scaled elements still show
		   a sub-pixel antialiasing bleed past that edge on some displays -- clipping
		   at the container guarantees nothing ever renders past the true baseline
		   regardless of that rendering-level rounding. */
		overflow: hidden;
	}

	.noise-bar {
		flex: 1;
		height: calc(var(--base, 0.2) * 100%);
		min-height: 2px;
		background: var(--line-bright);
		/* scaleY defaults to growing from the element's own center, so a bar sitting
		   at the container's bottom edge (flex align-items: flex-end) would visibly
		   dip below that edge as it grows -- pinning the origin to the bottom keeps
		   growth reading as "signal rising from the floor," not "wobbling in place." */
		transform-origin: bottom;
		/* Slow and low-amplitude on purpose — round 1 flagged perpetual idle motion
		   as being in tension with the confirmed "left open in a background tab for
		   long stretches" usage scene. Calm enough to sit unattended; still visibly
		   alive on a glance. */
		animation: noise 4.2s ease-in-out infinite;
	}

	/* Held, paused or without a link, the receiver isn't listening: a flat, quieter floor. */
	.idle.still .noise-bar {
		animation: none;
		opacity: 0.35;
		height: 2px;
	}

	@media (prefers-reduced-motion: reduce) {
		.noise-bar {
			animation: none;
		}
	}

	@keyframes noise {
		0%,
		100% {
			transform: scaleY(1);
			opacity: 0.45;
		}
		50% {
			transform: scaleY(1.4);
			opacity: 0.7;
		}
	}

	.status {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		align-items: baseline;
		gap: var(--space-2);
	}

	.status .word {
		color: inherit;
	}

	.status:not(.cond-waiting) .word {
		color: var(--text-dim);
	}

	.note {
		max-width: 52ch;
		color: var(--text-muted);
		font-size: var(--fs-detail);
	}

	.lanes {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	/* Without a link the lanes may be stale: dimmed, and off the amber, which only ever
	   means "receiving right now" (DESIGN.md §2). */
	/* Dimmed by colour, not opacity, so every line keeps its contrast (WCAG 1.4.3). */
	.lanes.stale .title {
		color: var(--text-muted);
	}

	.lanes.stale .artist {
		color: var(--text-dim);
	}

	.lanes.stale .fill {
		background: var(--line-bright);
		box-shadow: none;
	}

	.lanes.stale .fill::after {
		display: none;
	}

	.lanes.stale .pct {
		color: var(--text-muted);
	}

	.lane {
		display: grid;
		/* v47: the title gets the larger share (it was a third, cut at ~280px of 950). */
		grid-template-columns: minmax(0, 2fr) minmax(8rem, 1fr) 3.5rem;
		align-items: center;
		gap: var(--space-4);
	}

	.meta {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.title {
		font-weight: var(--fw-medium);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.artist {
		font-size: var(--fs-detail);
		color: var(--text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.meter {
		height: 0.625rem;
		border-color: var(--line);
		border-radius: 3px;
		overflow: hidden;
	}

	.fill {
		position: relative;
		overflow: hidden;
		width: 100%;
		height: 100%;
		transform-origin: left;
		background: linear-gradient(90deg, var(--signal-dim), var(--signal));
		box-shadow: 0 0 8px 0 var(--signal-glow);
		transition: transform var(--dur-med) var(--ease-signal);
	}

	/* v47 (F33): the shimmer is a sheen moved by transform (compositor only); it animated
	   background-position, which repainted the lane every frame. */
	.fill::after {
		content: '';
		position: absolute;
		inset: 0;
		background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.22), transparent);
		transform: translateX(-100%);
		animation: shimmer 2.4s linear infinite;
	}

	@media (prefers-reduced-motion: reduce) {
		.fill::after {
			animation: none;
			display: none;
		}
	}

	@keyframes shimmer {
		0% {
			transform: translateX(-100%);
		}
		100% {
			transform: translateX(100%);
		}
	}

	.pct {
		text-align: right;
		color: var(--signal);
		font-size: var(--fs-detail);
	}

	/* Phone: the title line gets the full width; meter and percentage share the next. */
	@media (max-width: 40em) {
		.waterfall {
			padding: var(--space-3) var(--space-4);
		}

		.lane {
			grid-template-columns: minmax(0, 1fr) 3rem;
			gap: var(--space-1) var(--space-3);
		}

		.meta {
			grid-column: 1 / -1;
		}
	}
</style>
