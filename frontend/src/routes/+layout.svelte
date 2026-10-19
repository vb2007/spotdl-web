<script lang="ts">
	// v47 (F33): the two families are served from this app (Fontsource, OFL), not Google Fonts:
	// that stylesheet blocked first paint (444 of 788 ms cold) and sent every visit to a third
	// party. Each weight's file declares its subsets by unicode-range, so a page downloads only
	// the ones its text uses (latin, plus latin-ext for Hungarian's ő and ű).
	import '@fontsource/ibm-plex-sans/400.css';
	import '@fontsource/ibm-plex-sans/500.css';
	import '@fontsource/ibm-plex-sans/600.css';
	import '@fontsource/ibm-plex-mono/400.css';
	import '@fontsource/ibm-plex-mono/500.css';
	import '@fontsource/ibm-plex-mono/600.css';
	import '../app.css';
	import { tick } from 'svelte';
	import favicon from '$lib/assets/favicon.svg';
	import { afterNavigate, goto, invalidateAll } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import AmbientField from '$lib/components/AmbientField.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import HelpOverlay from '$lib/components/HelpOverlay.svelte';
	import ChordIndicator from '$lib/components/ChordIndicator.svelte';
	import { queue } from '$lib/stores/queue';
	import { onUnauthorized } from '$lib/api';
	import * as m from '$lib/paraglide/messages';
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

	// v45: the per-user switch, as `/api/auth/me` has it, applied when a session starts (the
	// first load, a sign-in, another identity); signed out, it's on. Within one session the
	// tab's own value is the truth (`/account` sets it on save): a later route load may carry
	// a `/me` preloaded on hover before that save. Another device's change arrives on reload.
	let appliedFor: string | null | undefined;
	$effect(() => {
		const email = data.session?.email ?? null;
		if (email === appliedFor) return;
		appliedFor = email;
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

	// v47: a 401 anywhere means the session ended (expired, revoked, signed out in another
	// tab). Back to /login, which says why, instead of a page of "Not authenticated" errors
	// with retries that can only fail. The store is cleared once the page is gone: reset
	// while `/` is still mounted, its stream and poll would read the reset as an identity
	// change and reload the tab.
	let ending = false;
	$effect(() =>
		onUnauthorized(async () => {
			if (ending || page.url.pathname === resolve('/login')) return;
			ending = true;
			try {
				await goto(resolve('/login'), { state: { sessionEnded: true } });
				queue.reset();
			} finally {
				ending = false;
			}
		})
	);

	// v47: the session check itself couldn't get an answer (a 5xx or a network failure: the
	// api restarting, a deploy). That says nothing about the session, so the page waits and
	// asks again, backing off to 30s, rather than sending a signed-in user to /login.
	let retryDelayMs = 2000;
	let retrying = $state(false);
	async function retrySession() {
		retrying = true;
		try {
			await invalidateAll();
		} finally {
			retrying = false;
		}
	}
	$effect(() => {
		if (!data.unreachable) {
			retryDelayMs = 2000;
			return;
		}
		const timer = setTimeout(retrySession, retryDelayMs);
		retryDelayMs = Math.min(retryDelayMs * 2, 30_000);
		return () => clearTimeout(timer);
	});

	// v45: a route change moves focus to the new page's h1 (or its main), as a full page load
	// would; the first load leaves focus where the browser put it. The page title is announced
	// by SvelteKit's own route announcer (`#svelte-announcer`), so no second live region here.
	afterNavigate(async ({ from, to, type }) => {
		if (type === 'enter' || !from || !to || from.url.pathname === to.url.pathname) return;
		await tick();
		const heading =
			// i18n-ignore: a selector
			document.querySelector<HTMLElement>('main h1') ??
			document.querySelector<HTMLElement>('h1') ??
			document.querySelector<HTMLElement>('main');
		if (heading) {
			if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
			heading.focus({ preventScroll: true });
		}
	});

	// The skip link: focus the landmark itself (Tab then continues inside it). The temporary
	// tabindex goes on blur, since a focusable <main> would take focus on every click in it.
	function skip(event: MouseEvent) {
		// v47: on `/` "Skip to queue" means the queue: its heading (already focusable), past the
		// submit form, the incoming submissions and the Waterfall (it landed 13 stops short).
		const heading = page.route.id === '/' ? document.getElementById('queue-heading') : null;
		if (heading) {
			event.preventDefault();
			heading.focus();
			return;
		}
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
	<!-- v47: the unreachable screen's own tab title (no page renders to give one). -->
	{#if data.unreachable}<title>{m.layout_unreachable_title()}</title>{/if}
</svelte:head>

<svelte:window onkeydown={onKeydown} onpointerdowncapture={cancelChord} />

<!-- v45: the first focusable element on every page. -->
<a class="skip-link" href="#main" onclick={skip}
	>{page.route.id === '/' ? m.layout_skip_to_queue() : m.layout_skip_to_content()}</a
>

<AmbientField {live} />

{#if data.unreachable}
	<main id="main" class="unreachable">
		<!-- i18n-ignore: the wordmark is a name, the same in every language. -->
		<span class="label">SPOTDL // WEB</span>
		<h1 class="page-title">{m.layout_unreachable_title()}</h1>
		<p>{m.layout_unreachable_body()}</p>
		<button type="button" class="btn" onclick={retrySession} disabled={retrying}
			>{m.layout_unreachable_retry()}</button
		>
	</main>
{:else}
	{@render children()}
{/if}

<!-- v43 (F08): the one confirmation every destructive action asks through. -->
<ConfirmDialog />
<HelpOverlay routeId={page.route.id} {isAdmin} {signedIn} />
<ChordIndicator routeId={page.route.id} {isAdmin} />

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
		font-size: var(--fs-detail);
		font-weight: var(--fw-medium);
		color: var(--text-primary);
		text-decoration: none;
		transform: translateY(calc(-100% - var(--space-4)));
	}

	.unreachable {
		max-width: 32rem;
		margin: 0 auto;
		padding: var(--space-8) var(--space-4);
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-3);
	}

	.unreachable p {
		color: var(--text-muted);
	}

	.unreachable .btn {
		margin-top: var(--space-2);
	}

	.skip-link:focus-visible,
	.skip-link:focus {
		transform: none;
	}
</style>
