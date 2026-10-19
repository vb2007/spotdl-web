import { tick } from 'svelte';
import { writable } from 'svelte/store';

/** v43 (F08): what a destructive action asks before it runs. Named action on both the
 * question and the button, never "OK" / "Yes" (impeccable `clarify`). */
export interface ConfirmRequest {
	/** The question, naming the action: "Cancel this job?" */
	title: string;
	/** The object acted on, shown as data (a job title, a proxy address). Optional. */
	subject?: string;
	/** v47: the subject is an address (a link, a proxy, a folder), set in mono. A song or job
	 * title is content, and content is never in the instrument face (DESIGN.md §3). */
	subjectIsAddress?: boolean;
	/** One or two sentences: what happens, and whether it can be undone. */
	body: string;
	/** The destructive button, naming the action: "cancel job". */
	confirmLabel: string;
	/** The safe button, which takes focus first: "keep job". */
	cancelLabel: string;
}

interface Pending extends ConfirmRequest {
	resolve: (confirmed: boolean) => void;
}

/** The one open request, rendered by `ConfirmDialog.svelte` (mounted once in the layout). */
export const pendingConfirm = writable<Pending | null>(null);

/** Asks, and resolves `true` only on the destructive button. Esc, the safe button, a
 * backdrop click and a navigation all resolve `false`. A second request while one is open
 * answers the first `false`: only one question is ever on screen. */
export function confirmAction(request: ConfirmRequest): Promise<boolean> {
	return new Promise((resolve) => {
		pendingConfirm.update((current) => {
			current?.resolve(false);
			return { ...request, resolve };
		});
	});
}

/** Answers an open question "no" and closes it: on a session reset (another identity), where
 * no navigation happens for ConfirmDialog's beforeNavigate to catch. */
export function dismissConfirm(): void {
	pendingConfirm.update((current) => {
		current?.resolve(false);
		return null;
	});
}

/** v43: after a confirmed action re-renders, put focus somewhere sensible when the action
 * removed (or disabled) what had it: a cancelled job's cancel button, a swapped pause/resume
 * button, a removed proxy row. Only when focus has actually fallen to `<body>`; focus the
 * user moved elsewhere in the meantime is left alone. */
export async function keepFocus(fallback: HTMLElement | null | undefined): Promise<void> {
	await tick();
	const active = document.activeElement;
	if ((active === null || active === document.body) && fallback?.isConnected) fallback.focus();
}
