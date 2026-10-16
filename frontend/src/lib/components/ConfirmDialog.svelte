<script lang="ts">
	import { beforeNavigate } from '$app/navigation';
	import { pendingConfirm } from '$lib/stores/confirm';

	// v43 (F08): the one confirmation for every destructive action, mounted once in the
	// layout and driven by `confirmAction()`. A native modal <dialog>: the top layer makes
	// the rest of the page inert and keeps Tab inside, Esc arrives as its `cancel` event,
	// and focus starts on the safe button. Focus goes back to whatever opened it.

	let dialog: HTMLDialogElement | undefined = $state();
	let keepButton: HTMLButtonElement | undefined = $state();
	let trigger: HTMLElement | null = null;

	const request = $derived($pendingConfirm);

	$effect(() => {
		if (!request || !dialog || !keepButton) return;
		if (!dialog.open) {
			trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
			dialog.showModal();
		}
		// Also on a request that replaced an open one: the safe choice is always first.
		keepButton.focus();
	});

	function answer(confirmed: boolean) {
		const current = $pendingConfirm;
		if (!current) return;
		pendingConfirm.set(null);
		if (dialog?.open) dialog.close();
		const opener = trigger;
		trigger = null;
		// Before the caller's action runs (it resumes on a later microtask), so an action
		// that removes its own trigger still leaves focus somewhere it can be seen leaving.
		if (opener?.isConnected) opener.focus();
		current.resolve(confirmed);
	}

	function onCancel(event: Event) {
		// Esc: one path for every way out, so focus return and the answer can't diverge.
		event.preventDefault();
		answer(false);
	}

	function onBackdrop(event: MouseEvent) {
		// The inner box fills the dialog, so only a click on the backdrop lands here.
		if (event.target === dialog) answer(false);
	}

	// A navigation (including the layout's redirect when the session ends) never carries a
	// question onto the next page.
	beforeNavigate(() => answer(false));
</script>

<dialog
	bind:this={dialog}
	class="panel confirm"
	role="alertdialog"
	aria-labelledby="confirm-title"
	aria-describedby={request?.subject ? 'confirm-subject confirm-body' : 'confirm-body'}
	oncancel={onCancel}
	onclose={() => answer(false)}
	onclick={onBackdrop}
>
	{#if request}
		<div class="box">
			<h2 id="confirm-title" class="title">{request.title}</h2>
			{#if request.subject}
				<p id="confirm-subject" class="subject mono">{request.subject}</p>
			{/if}
			<p id="confirm-body" class="body">{request.body}</p>
			<div class="actions">
				<button type="button" class="btn" bind:this={keepButton} onclick={() => answer(false)}
					>{request.cancelLabel}</button
				>
				<button type="button" class="btn danger" onclick={() => answer(true)}
					>{request.confirmLabel}</button
				>
			</div>
		</div>
	{/if}
</dialog>

<style>
	.confirm {
		width: min(28rem, calc(100vw - 2 * var(--space-4)));
		max-width: none;
		padding: 0;
		color: var(--text-primary);
	}

	/* A dimmed page, not a blurred one: the dialog is the only thing to read. */
	.confirm::backdrop {
		background: rgba(5, 6, 7, 0.72);
	}

	.confirm[open] {
		animation: confirm-in var(--dur-med) var(--ease-signal);
	}

	@keyframes confirm-in {
		from {
			opacity: 0;
			transform: translateY(0.375rem);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.confirm[open] {
			animation: none;
		}
	}

	.box {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-5);
	}

	.title {
		font-size: var(--fs-lead);
		font-weight: var(--fw-strong);
		line-height: 1.3;
	}

	/* The object is data (a title, an address): mono, wrapping rather than truncating. */
	.subject {
		font-size: var(--fs-detail);
		color: var(--text-primary);
		overflow-wrap: anywhere;
	}

	.body {
		font-size: var(--fs-detail);
		color: var(--text-muted);
		line-height: 1.55;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: var(--space-2);
		margin-top: var(--space-2);
	}
</style>
