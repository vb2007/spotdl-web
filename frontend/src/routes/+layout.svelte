<script lang="ts">
	import '../app.css';
	import { tick } from 'svelte';
	import favicon from '$lib/assets/favicon.svg';
	import { afterNavigate, goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import AmbientField from '$lib/components/AmbientField.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import HelpOverlay from '$lib/components/HelpOverlay.svelte';
	import ChordIndicator from '$lib/components/ChordIndicator.svelte';
	import { queue } from '$lib/stores/queue';
	import { link as streamLink } from '$lib/stores/link';
	import {
		cancelChord,
		helpOpen,
		onKeydown,
		registerHandlers,
		shortcutsEnabled
	} from '$lib/keyboard/registry';

	let { children, data } = $props();

	const { activeTracks } = queue;
	// v40: the field warms only while `/` shows something receiving. Only `/` holds the live
	// stream; leaving it closes the stream but leaves `activeTracks` at its last value, so on
	// any other route the store is stale and must not light the page. v42: the same holds on
	// `/` while its stream is down -- the lanes may be stale, so nothing reads as receiving.
	const live = $derived(
		page.route.id === '/' && $activeTracks.length > 0 && $streamLink === 'live'
	);

	const signedIn = $derived(data.session != null);
	const isAdmin = $derived(data.session?.is_admin ?? false);

	// v45: the per-user switch, read from `/api/auth/me` on every route load (so a change on
	// another device arrives with the next navigation or reload). Signed out, it's on.
	$effect(() => {
		shortcutsEnabled.set(data.session?.keyboard_shortcuts ?? true);
	});

	// The keys that work everywhere: the help, and (signed in) the `g` chords. The admin pages
	// are offered to the admin only; a non-admin reaches them only by typing the path (v43).
	$effect(() => {
		const go =
			(path: '/' | '/settings' | '/library' | '/account' | '/stats', admin = false) =>
			() => {
				if (admin && !isAdmin) return false;
				goto(resolve(path));
				return true;
			};
		return registerHandlers({
			help: () => {
				helpOpen.update((open) => !open);
				return true;
			},
			...(signedIn
				? {
						'go-dashboard': go('/'),
						'go-settings': go('/settings', true),
						'go-library': go('/library', true),
						'go-account': go('/account'),
						'go-stats': go('/stats', true)
					}
				: {})
		});
	});

	// v45: a route change moves focus to the new page's h1 (or its main) and announces the
	// page, as a full page load would; the first load leaves focus where the browser put it.
	let announcement = $state('');
	afterNavigate(async ({ from, to, type }) => {
		if (type === 'enter' || !from || !to || from.url.pathname === to.url.pathname) return;
		await tick();
		const heading =
			document.querySelector<HTMLElement>('main h1') ??
			document.querySelector<HTMLElement>('h1') ??
			document.querySelector<HTMLElement>('main');
		if (heading) {
			if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
			heading.focus({ preventScroll: true });
		}
		// Cleared first, so a return to the same title is still announced.
		announcement = '';
		await tick();
		announcement = document.title;
	});

	// The skip link: focus the landmark itself (Tab then continues inside it). The temporary
	// tabindex goes on blur, since a focusable <main> would take focus on every click in it.
	function skip(event: MouseEvent) {
		const main = document.getElementById('main');
		if (!main) return;
		event.preventDefault();
		main.setAttribute('tabindex', '-1');
		main.addEventListener('blur', () => main.removeAttribute('tabindex'), { once: true });
		main.focus();
	}
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<svelte:window onkeydown={onKeydown} onpointerdowncapture={cancelChord} />

<!-- v45: the first focusable element on every page. -->
<a class="skip-link" href="#main" onclick={skip}
	>{page.route.id === '/' ? 'Skip to queue' : 'Skip to content'}</a
>

<AmbientField {live} />

{@render children()}

<!-- v43 (F08): the one confirmation every destructive action asks through. -->
<ConfirmDialog />
<HelpOverlay routeId={page.route.id} {isAdmin} {signedIn} />
<ChordIndicator routeId={page.route.id} {isAdmin} />
<p class="sr-only" aria-live="polite">{announcement}</p>

<style>
	/* Off-screen until focused, then a plate at the top-left corner in the panel's material:
	   the ring does the pointing, the plate makes it legible over the page. */
	.skip-link {
		position: fixed;
		top: var(--space-3);
		left: var(--space-3);
		z-index: 20;
		padding: var(--space-2) var(--space-4);
		background: var(--bg-1);
		border: 1px solid var(--line-control);
		border-radius: 4px;
		font-family: var(--font-mono);
		font-size: var(--fs-meta);
		color: var(--text-primary);
		text-decoration: none;
		transform: translateY(calc(-100% - var(--space-4)));
	}

	.skip-link:focus-visible,
	.skip-link:focus {
		transform: none;
	}
</style>
