<script lang="ts">
	import { bindingsFor, chordLabel } from '$lib/keyboard/bindings';
	import { chordPending } from '$lib/keyboard/registry';
	import * as m from '$lib/paraglide/messages';

	// v45: while `g` waits for its second key (about 1.5s), say so, and say where each key goes,
	// so a half-remembered chord is finished by reading rather than guessing. Filtered like the
	// help overlay: a non-admin never sees the admin pages offered.
	let { routeId, isAdmin }: { routeId: string | null; isAdmin: boolean } = $props();

	const targets = $derived(
		bindingsFor(routeId, isAdmin).filter(
			(b) => b.prefix !== undefined && b.prefix === $chordPending
		)
	);
</script>

<!-- Always present, so its text is announced when it appears. -->
<div class="chord" class:shown={$chordPending !== null} role="status">
	{#if $chordPending !== null}
		<kbd>{$chordPending}</kbd>
		<span class="then">{m.kbd_then()}</span>
		<span class="targets">
			{#each targets as target (target.id)}
				<span class="target"><kbd>{chordLabel(target.keys[0])}</kbd> {target.label()}</span>
			{/each}
		</span>
	{/if}
</div>

<style>
	/* A readout docked to the bottom edge, in the panel's material; it appears without moving
	   anything and never takes a click (it only reports). */
	.chord {
		position: fixed;
		left: 50%;
		bottom: var(--space-4);
		z-index: 10;
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: var(--space-2);
		max-width: calc(100vw - 2 * var(--space-4));
		padding: var(--space-2) var(--space-4);
		background: var(--bg-1);
		border: 1px solid var(--line-control);
		border-radius: 6px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
		font-size: var(--fs-detail);
		color: var(--text-primary);
		pointer-events: none;
		transform: translate(-50%, 0.5rem);
		opacity: 0;
		transition:
			opacity var(--dur-fast) var(--ease-signal),
			transform var(--dur-fast) var(--ease-signal);
	}

	.chord.shown {
		opacity: 1;
		transform: translate(-50%, 0);
	}

	.targets {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-3);
	}

	.target {
		white-space: nowrap;
	}

	.then {
		color: var(--text-muted);
	}
</style>
