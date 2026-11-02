import { beforeNavigate, goto } from '$app/navigation';
import { onMount } from 'svelte';
import { confirmAction } from '$lib/stores/confirm';
import { leavingSession } from '$lib/session';
import * as m from '$lib/paraglide/messages';

/** v67: a page's own question for what it guards (an uncopied API key isn't an "unsaved change"),
 * or `null` for the generic one. */
export interface LeaveQuestion {
	title: string;
	body: string;
	confirmLabel: string;
	cancelLabel: string;
}

/** v62 (F6): asks before a page with unsaved edits is left. Call it during a page's component
 * init with what "unsaved" means there, told whether the page is unloading (/settings: a
 * section differs from what was loaded; /account: see its own note).
 *
 * - An in-app navigation (a link, Back/Forward, a `g` chord, any `goto`) is held and asked
 *   about through the one `ConfirmDialog`, keyboard-complete like every other question. "keep
 *   editing" stays; "discard changes" goes where the navigation was going.
 * - Closing the tab, reloading or leaving the site gets the browser's own question
 *   (`beforeunload`; SvelteKit's `cancel()` of an unloading navigation asks the same).
 * - Leaving because the session ended or changed (another tab's sign-out, a 401) is never
 *   held: nothing typed here can be saved by this session any more. */
export function guardUnsavedEdits(
	isDirty: (unloading: boolean) => boolean,
	question?: () => LeaveQuestion | null
): void {
	// Set once "discard changes" was chosen, so the re-sent navigation goes through.
	let discarding = false;

	beforeNavigate((navigation) => {
		if (discarding || leavingSession() || !isDirty(navigation.willUnload)) return;
		if (navigation.willUnload) {
			navigation.cancel();
			return;
		}
		const to = navigation.to?.url;
		if (!to) return;
		// The same page (a `g` chord for the page already open, a query or hash change): it
		// stays mounted with its edits, so there is nothing to ask about (live review).
		if (to.pathname === navigation.from?.url?.pathname) return;
		const { type, delta } = navigation;
		navigation.cancel();
		// After this navigation's other callbacks: ConfirmDialog's answers any open question "no"
		// on every navigation, this cancelled one included.
		queueMicrotask(async () => {
			const discard = await confirmAction(
				question?.() ?? {
					title: m.unsaved_title(),
					body: m.unsaved_body(),
					confirmLabel: m.unsaved_discard(),
					cancelLabel: m.unsaved_keep()
				}
			);
			if (!discard) return;
			discarding = true;
			// Back/Forward: history.go returns before its navigation runs, so this stays set (the
			// page is gone once it lands).
			if (type === 'popstate' && delta) {
				history.go(delta);
				return;
			}
			try {
				// eslint-disable-next-line svelte/no-navigation-without-resolve -- `to` is the URL SvelteKit was already navigating to, resolved.
				await goto(to.pathname + to.search + to.hash);
			} finally {
				discarding = false;
			}
		});
	});

	onMount(() => {
		const onBeforeUnload = (event: BeforeUnloadEvent) => {
			if (discarding || leavingSession() || !isDirty(true)) return;
			event.preventDefault();
			// Older browsers ask only when a return value is set.
			event.returnValue = '';
		};
		window.addEventListener('beforeunload', onBeforeUnload);
		return () => window.removeEventListener('beforeunload', onBeforeUnload);
	});
}
