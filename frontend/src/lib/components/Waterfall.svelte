<script lang="ts">
	import type { LiveTrack } from '$lib/stores/queue';

	let { tracks }: { tracks: LiveTrack[] } = $props();

	// A quiet noise floor, not a dead flatline — a real spectrum scope stays alive
	// (low, uneven, still moving) when nothing is transmitting; "no signal" should
	// read as "listening," never as "off."
	const noiseBars = Array.from({ length: 40 }, () => ({
		delay: Math.random() * 2,
		base: 0.1 + Math.random() * 0.3
	}));
</script>

<section class="panel waterfall" class:live={tracks.length > 0} aria-label="Active downloads">
	<div class="head">
		<span class="label">Active signal</span>
		<span class="label dim mono">{tracks.length} lane{tracks.length === 1 ? '' : 's'}</span>
	</div>

	{#if tracks.length === 0}
		<div class="idle">
			<div class="noise-floor" aria-hidden="true">
				{#each noiseBars as bar, i (i)}
					<span class="noise-bar" style:animation-delay="{bar.delay}s" style:--base={bar.base}
					></span>
				{/each}
			</div>
			<span class="label dim">no signal — queue idle</span>
		</div>
	{:else}
		<ul class="lanes">
			{#each tracks as track (track.id)}
				<li class="lane">
					<div class="meta">
						<span class="title">{track.title ?? 'Unknown title'}</span>
						<span class="artist">{track.artists?.join(', ') ?? 'Unknown artist'}</span>
					</div>
					<div
						class="meter"
						role="progressbar"
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
		   exclusive meaning ("something is live right now"); this restores that. */
		border-top: 2px solid var(--line-bright);
	}

	.waterfall.live {
		border-top-color: var(--signal-dim);
	}

	.head {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
	}

	.idle {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-6) 0;
	}

	.noise-floor {
		display: flex;
		align-items: flex-end;
		gap: 2px;
		width: 100%;
		max-width: 24rem;
		height: 1.5rem;
	}

	.noise-bar {
		flex: 1;
		height: calc(var(--base, 0.2) * 100%);
		min-height: 2px;
		background: var(--line-bright);
		/* Slow and low-amplitude on purpose — round 1 flagged perpetual idle motion
		   as being in tension with the confirmed "left open in a background tab for
		   long stretches" usage scene. Calm enough to sit unattended; still visibly
		   alive on a glance. */
		animation: noise 4.2s ease-in-out infinite;
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

	.lanes {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
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
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.artist {
		font-size: 0.8125rem;
		color: var(--text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.meter {
		height: 0.625rem;
		background: var(--bg-0);
		border: 1px solid var(--line);
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
		font-size: 0.8125rem;
	}
</style>
