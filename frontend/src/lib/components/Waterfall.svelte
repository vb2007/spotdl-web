<script lang="ts" module>
	/** This page's SSE stream: not yet open, open, or dropped and retrying (v42, F05). */
	export type LinkState = 'connecting' | 'live' | 'reconnecting';
</script>

<script lang="ts">
	import type { LiveTrack } from '$lib/stores/queue';
	import Countdown from '$lib/components/Countdown.svelte';

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

	function clockTime(iso: string): string {
		return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}
</script>

<section
	class="panel waterfall"
	class:live={tracks.length > 0}
	class:held={tracks.length === 0 && (idle === 'holding' || idle === 'paused')}
	aria-labelledby="waterfall-heading"
>
	<div class="head">
		<h2 id="waterfall-heading" class="label">Active signal</h2>
		{#if tracks.length > 0 && link === 'reconnecting'}
			<span class="label stale">link lost — progress may be stale</span>
		{:else}
			<span class="label count">{tracks.length} lane{tracks.length === 1 ? '' : 's'}</span>
		{/if}
	</div>

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
					<span class="label word">holding</span>
					<span aria-hidden="true"
						><Countdown
							scheduledAt={breakerUntil}
							label="resumes in"
							dueLive={false}
							dueText="resuming…"
						/></span
					>
					<span class="sr-only">downloads resume at {clockTime(breakerUntil)}</span>
				</p>
				<p class="note">
					A deliberate pause after repeated rate limits. Waiting tracks keep their place.
				</p>
			{:else if idle === 'paused'}
				<p class="status"><span class="label word">receiver paused</span></p>
				<p class="note">
					{isAdmin
						? 'Nothing is dispatched until you resume it in settings.'
						: 'Downloads resume when the receiver is switched back on.'}
				</p>
			{:else if idle === 'reconnecting'}
				<p class="status cond-waiting"><span class="label word">link lost — reconnecting</span></p>
				<p class="note">This page catches up by itself once the link is back.</p>
			{:else if idle === 'connecting'}
				<p class="status"><span class="label word">tuning in…</span></p>
			{:else if idle === 'busy'}
				<p class="status"><span class="label word">no signal here — worker busy elsewhere</span></p>
			{:else}
				<p class="status"><span class="label word">no signal — nothing downloading</span></p>
			{/if}
		</div>
	{:else}
		<ul class="lanes" class:stale={link === 'reconnecting'}>
			{#each tracks as track (track.id)}
				<li class="lane">
					<div class="meta">
						<span class="title" id="lane-title-{track.id}">{track.title ?? 'Unknown title'}</span>
						<span class="artist">{track.artists?.join(', ') ?? 'Unknown artist'}</span>
					</div>
					<div
						class="meter well"
						role="progressbar"
						aria-labelledby="lane-title-{track.id}"
						aria-valuenow={track.progress ?? 0}
						aria-valuemin={0}
						aria-valuemax={100}
					>
						<div class="fill" style:transform="scaleX({(track.progress ?? 0) / 100})"></div>
					</div>
					<span class="pct mono">{track.progress ?? 0}%</span>
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
		   v42: a deliberate hold (breaker or pause) takes the waiting edge, the same
		   neutral -> condition swap. */
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

	.lanes.stale {
		opacity: 0.6;
	}

	.lane {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(0, 2fr) 3.5rem;
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
		width: 100%;
		height: 100%;
		transform-origin: left;
		background: linear-gradient(90deg, var(--signal-dim), var(--signal));
		box-shadow: 0 0 8px 0 var(--signal-glow);
		transition: transform var(--dur-med) var(--ease-signal);
		background-size: 200% 100%;
		animation: shimmer 2.4s linear infinite;
	}

	@media (prefers-reduced-motion: reduce) {
		.fill {
			animation: none;
		}
	}

	@keyframes shimmer {
		0% {
			background-position: 200% 0;
		}
		100% {
			background-position: -200% 0;
		}
	}

	.pct {
		text-align: right;
		color: var(--signal);
		font-size: var(--fs-detail);
	}

	/* Phone: the title line gets the full width; meter and percentage share the next. */
	@media (max-width: 640px) {
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
