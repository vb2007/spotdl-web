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
	// Safari doesn't focus a button on click, so activeElement can't name a pointer trigger;
	// the last pressed control (recorded in the capture phase, before its own handler asks)
	// stands in for it.
	let lastPressed: { el: HTMLElement | null; at: number } = { el: null, at: 0 };
	$effect(() => {
		const record = (event: MouseEvent) => {
			lastPressed = {
				el: event.target instanceof Element ? event.target.closest<HTMLElement>('button, a') : null,
				at: performance.now()
			};
		};
		document.addEventListener('click', record, true);
		return () => document.removeEventListener('click', record, true);
	});

	const request = $derived($pendingConfirm);

	$effect(() => {
		// Dismissed from outside (a session reset): close the now-empty dialog.
		if (!request && dialog?.open) {
			closingByAnswer = true;
			dialog.close();
			trigger = null;
			return;
		}
		if (!request || !dialog || !keepButton) return;
		if (!dialog.open) {
			// The control just pressed (a click, or Enter/Space, which also click) is the opener;
			// in Safari focus may still sit elsewhere (an input), so it wins when it's fresh.
			const active = document.activeElement;
			const pressed = performance.now() - lastPressed.at < 1000 ? lastPressed.el : null;
			trigger =
				pressed ?? (active instanceof HTMLElement && active !== document.body ? active : null);
			dialog.showModal();
			openedAt = performance.now();
		}
		// Also on a request that replaced an open one: the safe choice is always first.
		keepButton.focus();
	});

	function answer(confirmed: boolean) {
		const current = $pendingConfirm;
		if (!current) return;
		pendingConfirm.set(null);
		// The `close` event this fires arrives a task later; it must not answer a question
		// asked in between.
		if (dialog?.open) {
			closingByAnswer = true;
			dialog.close();
		}
		const opener = trigger;
		trigger = null;
		// Before the caller's action runs (it resumes on a later microtask), so an action
		// that removes its own trigger still leaves focus somewhere it can be seen leaving.
		// A trigger that left or was disabled meanwhile can't take focus; each caller then
		// places it (keepFocus) once its own state settles.
		if (opener?.isConnected && !(opener as HTMLButtonElement).disabled) opener.focus();
		current.resolve(confirmed);
	}

	// Only a close nobody answered for (none today) answers "no"; the close an answer itself
	// caused is skipped.
	let closingByAnswer = false;
	function onClose() {
		if (closingByAnswer) {
			closingByAnswer = false;
			return;
		}
		answer(false);
	}

	function onCancel(event: Event) {
		// Esc: one path for every way out, so focus return and the answer can't diverge.
		event.preventDefault();
		answer(false);
	}

	// A press that started inside the box (selecting the subject's text, say) and was
	// released over the backdrop also clicks the dialog itself: only a press that began on
	// the backdrop counts.
	let pressedBackdrop = false;
	// The second click of a double-click on the trigger lands on the just-opened backdrop:
	// presses in the first moments after opening don't count as "keep".
	let openedAt = 0;
	function onPointerDown(event: PointerEvent) {
		pressedBackdrop = event.target === dialog && performance.now() - openedAt > 500;
	}

	function onBackdrop(event: MouseEvent) {
		// The inner box fills the dialog, so only a click on the backdrop lands here.
		if (event.target === dialog && pressedBackdrop) answer(false);
		pressedBackdrop = false;
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
	onclose={onClose}
	onpointerdown={onPointerDown}
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
