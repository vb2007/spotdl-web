<script lang="ts">
	import { beforeNavigate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import {
		GROUP_TITLE,
		HU_PHYSICAL,
		bindingsFor,
		chordLabel,
		type Binding,
		type BindingGroup
	} from '$lib/keyboard/bindings';
	import { helpOpen, shortcutsEnabled } from '$lib/keyboard/registry';
	import { focusList, focusRowEl, listOf, rowAt, rowId } from '$lib/keyboard/lists';
	import * as m from '$lib/paraglide/messages';
	import RichText from '$lib/components/RichText.svelte';

	// v45: the shortcut map, generated from the binding table (never a second list), filtered
	// to this route and the viewer's role. A native modal <dialog>, like the confirmation: the
	// rest of the page is inert, Tab stays inside, Esc is its `cancel`, and focus goes back to
	// whatever had it when it opened.
	let {
		routeId,
		isAdmin,
		signedIn
	}: { routeId: string | null; isAdmin: boolean; signedIn: boolean } = $props();

	let dialog: HTMLDialogElement | undefined = $state();
	let closeButton: HTMLButtonElement | undefined = $state();
	let opener: HTMLElement | null = null;
	// The opener's row and list, by id: a reload while the overlay is open remounts the rows,
	// and focus must come back to the same row rather than fall to <body>.
	let openerRow: string | null = null;
	let openerList: string | null = null;

	const GROUPS: BindingGroup[] = ['global', 'go', 'list', 'queue'];
	const groups = $derived(
		GROUPS.map((group) => ({
			group,
			bindings: bindingsFor(routeId, isAdmin, signedIn).filter((b) => b.group === group)
		})).filter((g) => g.bindings.length > 0)
	);

	$effect(() => {
		if (!dialog) return;
		if ($helpOpen && !dialog.open) {
			const active = document.activeElement;
			opener = active instanceof HTMLElement && active !== document.body ? active : null;
			const row = rowAt(opener);
			openerRow = row ? rowId(row) : null;
			openerList = row ? (listOf(row)?.dataset.kbList ?? null) : null;
			dialog.showModal();
			closeButton?.focus();
		} else if (!$helpOpen && dialog.open) {
			dialog.close();
		}
	});

	function onClose() {
		helpOpen.set(false);
		const back = opener;
		const row = openerRow;
		const list = openerList;
		opener = openerRow = openerList = null;
		// `close` arrives a task after the dialog closed: a key pressed meanwhile (`?` then `/`)
		// may already have put focus somewhere, and that wins.
		const active = document.activeElement;
		if (active && active !== document.body && !dialog?.contains(active)) return;
		// The opener may no longer take focus (the skip link's main drops its tabindex on blur):
		// only a focus that landed ends the search.
		if (back?.isConnected) {
			back.focus();
			if (document.activeElement === back) return;
		}
		if (row && focusRowEl(document.querySelector<HTMLElement>(`[data-kb-row="${row}"]`))) return;
		if (list && focusList(list)) return;
		// The opener went for good: the page's heading, never <body>.
		// i18n-ignore: a selector
		const heading = document.querySelector<HTMLElement>('main h1, h1');
		if (heading && !heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
		heading?.focus();
	}

	function onCancel(event: Event) {
		event.preventDefault();
		helpOpen.set(false);
	}

	let pressedBackdrop = false;
	function onPointerDown(event: PointerEvent) {
		pressedBackdrop = event.target === dialog;
	}
	function onBackdrop(event: MouseEvent) {
		if (event.target === dialog && pressedBackdrop) helpOpen.set(false);
		pressedBackdrop = false;
	}

	beforeNavigate(() => helpOpen.set(false));

	// The "off" note's link sits inside its sentence, wherever the language puts it: the
	// message is split at a placeholder rather than built from fragments.
	const LINK = '\uE000';
	const offNote = $derived(m.help_off({ account: LINK }).split(LINK));

	/** A key with its Hungarian combination, for the symbols that need one. */
	function hint(binding: Binding, i: number): string | undefined {
		return HU_PHYSICAL[binding.keys[i].key];
	}
</script>

<dialog
	bind:this={dialog}
	class="panel help"
	aria-labelledby="help-title"
	aria-describedby="help-layout"
	data-kb-help
	oncancel={onCancel}
	onclose={onClose}
	onpointerdown={onPointerDown}
	onclick={onBackdrop}
>
	<!-- Always rendered (a closed dialog shows nothing), so "close" exists to take focus the
	     moment it opens. -->
	<div class="box">
		<header class="head">
			<h2 id="help-title" class="title">{m.help_title()}</h2>
			<button
				type="button"
				class="btn small"
				bind:this={closeButton}
				onclick={() => helpOpen.set(false)}>{m.help_close()}</button
			>
		</header>
		<p id="help-layout" class="note"><RichText text={m.help_layout_note()} /></p>
		{#if !$shortcutsEnabled && signedIn}
			<p class="note off" role="status">
				{offNote[0]}<a href={resolve('/account')}>{m.help_off_link()}</a>{offNote[1] ?? ''}
			</p>
		{/if}

		<div class="groups">
			{#each groups as { group, bindings } (group)}
				<section class="group" aria-labelledby="help-group-{group}">
					<h3 id="help-group-{group}" class="label">{GROUP_TITLE[group]()}</h3>
					<dl class="list">
						{#each bindings as binding (binding.id)}
							<div class="entry" data-binding={binding.id}>
								<dt class="keys">
									{#if binding.prefix}
										<kbd>{binding.prefix}</kbd><span class="then">{m.kbd_then()}</span>
									{/if}
									{#each binding.keys as chord, i (i)}
										{#if i > 0}<span class="or">{m.kbd_or()}</span>{/if}
										<kbd>{chordLabel(chord)}</kbd>
										{#if hint(binding, i)}
											<span class="hu mono">({hint(binding, i)})</span>
										{/if}
									{/each}
								</dt>
								<dd class="what">{binding.label()}</dd>
							</div>
						{/each}
					</dl>
				</section>
			{/each}
		</div>
	</div>
</dialog>

<style>
	.help {
		width: min(52rem, calc(100vw - 2 * var(--space-4)));
		max-width: none;
		max-height: min(46rem, calc(100dvh - 2 * var(--space-4)));
		padding: 0;
		color: var(--text-primary);
		overflow: auto;
		overscroll-behavior: contain;
	}

	/* The confirmation's backdrop: a dimmed page, the map the only thing to read. */
	.help::backdrop {
		background: rgba(5, 6, 7, 0.72);
	}

	.help[open] {
		animation: help-in var(--dur-med) var(--ease-signal);
	}

	@keyframes help-in {
		from {
			opacity: 0;
			transform: translateY(0.375rem);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.help[open] {
			animation: none;
		}
	}

	.box {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-5);
	}

	.head {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-3);
	}

	.title {
		font-size: var(--fs-lead);
		font-weight: var(--fw-strong);
		line-height: 1.3;
	}

	.note {
		max-width: 68ch;
		font-size: var(--fs-detail);
		color: var(--text-muted);
		line-height: 1.55;
	}

	/* Off is the waiting blue: a state the user chose, not a fault. */
	.note.off {
		color: var(--waiting);
	}

	/* Two columns of groups where there's room; a phone reads them one after another. */
	.groups {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-5) var(--space-6);
		margin-top: var(--space-2);
	}

	.group {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-width: 0;
	}

	.list {
		display: flex;
		flex-direction: column;
		margin: 0;
	}

	/* Keys left in a fixed track, what they do right, one hairline between entries: the
	   job list's rhythm at a reading size. */
	.entry {
		display: grid;
		grid-template-columns: minmax(8.5rem, auto) minmax(0, 1fr);
		gap: var(--space-3);
		align-items: baseline;
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--line);
	}

	.entry:last-child {
		border-bottom: none;
	}

	.keys {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-1);
	}

	/* The global keycap, a size up for the map's own reading distance. */
	kbd {
		min-width: 1.5rem;
		padding: 0.0625rem var(--space-2);
	}

	.then,
	.or {
		font-size: var(--fs-meta);
		color: var(--text-muted);
	}

	.hu {
		font-size: var(--fs-meta);
		color: var(--text-muted);
		white-space: nowrap;
	}

	.what {
		margin: 0;
		font-size: var(--fs-detail);
		line-height: 1.45;
	}

	@media (max-width: 760px) {
		.groups {
			grid-template-columns: minmax(0, 1fr);
		}
	}

	@media (max-width: 640px) {
		.box {
			padding: var(--space-4);
		}

		/* Keys over their meaning: a narrow column would wrap both into ragged stacks. */
		.entry {
			grid-template-columns: minmax(0, 1fr);
			gap: var(--space-1);
		}
	}
</style>
