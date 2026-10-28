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
	import * as api from '$lib/api';
	import * as m from '$lib/paraglide/messages';
	import { link as streamLink } from '$lib/stores/link';
	import { onSessionMessage, setLeavingSession } from '$lib/session';
	import {
		cancelChord,
		helpOpen,
		onKeydown,
		registerHandlers,
		shortcutsEnabled
	} from '$lib/keyboard/registry';

	let { children, data } = $props();

	const { viewerReceiving } = queue;
	// v40: the field warms only while `/` shows something receiving. Only `/` holds the live
	// stream; leaving it closes the stream but leaves `activeTracks` at its last value, so on
	// any other route the store is stale and must not light the page. v42: the same holds on
	// `/` while its stream is down -- the lanes may be stale, so nothing reads as receiving.
	// v54 (U1): and only the viewer's own downloads, in every view (DESIGN.md §2).
	const live = $derived(
		page.route.id === '/' && !data.unreachable && $viewerReceiving && $streamLink === 'live'
	);

	const signedIn = $derived(data.session != null);
	const isAdmin = $derived(data.session?.is_admin ?? false);

	// v45: the per-user switch, as `/api/auth/me` has it, applied when a session starts (the
	// first load, a sign-in, another identity); signed out, it's on. Within one session the
	// tab's own value is the truth (`/account` sets it on save): a later route load may carry
	// a `/me` preloaded on hover before that save. Another device's change arrives on reload.
	let appliedFor: string | null | undefined;
	$effect(() => {
		// v47: unreachable says nothing about who is signed in; keep the switch as it is.
		if (data.unreachable) return;
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
		api.onUnauthorized(async () => {
			if (ending || page.url.pathname === resolve('/login')) return;
			ending = true;
			try {
				// v47: a 401 can be stale (a request sent before a sign-in in another tab, or
				// answered after this tab's own sign-out began): only a session /me no longer
				// knows has ended. Anything but a 401 here can't tell, so the 401 stands.
				try {
					const now = await api.me();
					// Alive, but someone else's (the shared cookie changed under this tab): the
					// page is built for the previous identity, so start over as v42 does.
					if (now.email !== data.session?.email) window.location.reload();
					return;
				} catch {
					// A 401 confirms it; any other failure can't tell, and the request's 401 stands.
				}
				if (api.isSigningOut() || page.url.pathname === resolve('/login')) return;
				// v62 (F6): a page's unsaved-edits guard lets this through: nothing can be saved now.
				setLeavingSession(true);
				try {
					await goto(resolve('/login'), { state: { sessionEnded: true } });
				} finally {
					setLeavingSession(false);
				}
				queue.reset();
			} finally {
				ending = false;
			}
		})
	);

	// v62 (F9): another tab signed out, or signed someone in. The cookie is shared, so this tab
	// is signed out (or someone else) too, and it follows at once rather than on its next
	// request (the v47 401 handler above and the layout's own load stay as the fallback).
	// Navigate before resetting, as the 401 handler does: reset under a mounted `/`, its
	// stream and poll would read it as an identity change and reload the tab first.
	$effect(() =>
		onSessionMessage(async (message) => {
			const mine = data.session?.email ?? null;
			if (message.type === 'logout') {
				if (mine === null || page.url.pathname === resolve('/login')) return;
				setLeavingSession(true);
				try {
					await goto(resolve('/login'), { state: { sessionEnded: true } });
				} finally {
					setLeavingSession(false);
				}
				queue.reset();
				return;
			}
			if (message.email === mine) return;
			// Someone else holds the session now (or this tab was signed out): start over as
			// them, as v42 does for an identity change found on a stream reconnect.
			setLeavingSession(true);
			queue.reset();
			window.location.reload();
		})
	);

	// v47: the session check itself couldn't get an answer (a 5xx or a network failure: the
	// api restarting, a deploy). That says nothing about the session, so the page waits and
	// asks again, backing off to 30s, rather than sending a signed-in user to /login.
	// The first ask is almost at once: the screen can come from a hover preload taken during a
	// blip that is already over (SvelteKit reuses it on the click). Each ask has 15s: an api
	// that hangs rather than refuses (a deploy's half-started container) would otherwise hold
	// every later ask behind one request for as long as the proxy allows.
	const ASK_LIMIT_MS = 15_000;
	const sleep = (ms: number) => new Promise<void>((done) => setTimeout(done, ms));
	let retrying = $state(false);
	async function askAgain(): Promise<void> {
		if (retrying) return;
		retrying = true;
		try {
			await Promise.race([invalidateAll(), sleep(ASK_LIMIT_MS)]);
		} finally {
			retrying = false;
		}
	}

	// When the screen goes (the server answered), focus that was on it (the button) has nowhere
	// to be, and an invalidation is no navigation, so afterNavigate won't place it: the page's
	// h1 takes it. Only then: an automatic ask with focus elsewhere leaves it alone.
	async function askAndKeepFocus() {
		// i18n-ignore: a selector
		const onScreen = document.activeElement?.closest('main.unreachable') != null;
		await askAgain();
		await tick();
		if (!onScreen) return;
		if (document.activeElement === document.body || document.activeElement === null) {
			const heading =
				// i18n-ignore: a selector
				document.querySelector<HTMLElement>('main h1') ??
				document.querySelector<HTMLElement>('h1') ??
				document.querySelector<HTMLElement>('main');
			if (heading) {
				if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
				heading.focus();
			}
		}
	}

	// The button's own ask. Only a press dims the button: the automatic asks would make it
	// flash "unavailable" every few seconds while pressing it stays harmless.
	let pressing = $state(false);
	async function retrySession() {
		if (pressing) return;
		pressing = true;
		try {
			await askAndKeepFocus();
		} finally {
			pressing = false;
		}
	}

	// One loop per outage, keyed to the flag flipping (not to every new `data` object):
	// 300ms, then 2s doubling to 30s, until the screen goes.
	const isUnreachable = $derived(data.unreachable === true);
	$effect(() => {
		if (!isUnreachable) return;
		let cancelled = false;
		(async () => {
			let delay = 300;
			while (!cancelled) {
				await sleep(delay);
				if (cancelled) return;
				await askAndKeepFocus();
				delay = Math.min(Math.max(delay * 2, 2000), 30_000);
			}
		})();
		return () => {
			cancelled = true;
		};
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
		const heading =
			page.route.id === '/' && !data.unreachable ? document.getElementById('queue-heading') : null;
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
	>{page.route.id === '/' && !data.unreachable
		? m.layout_skip_to_queue()
		: m.layout_skip_to_content()}</a
>

<AmbientField {live} />

{#if data.unreachable}
	<main id="main" class="unreachable">
		<!-- i18n-ignore: the wordmark is a name, the same in every language. -->
		<span class="label" aria-hidden="true">SPOTDL // WEB</span>
		<h1 class="page-title">{m.layout_unreachable_title()}</h1>
		<p>{m.layout_unreachable_body()}</p>
		<!-- aria-disabled, not disabled: the automatic retries would otherwise pull focus off it
		     every few seconds (a focused button that is disabled drops focus to <body>). -->
		<button type="button" class="btn" onclick={retrySession} aria-disabled={pressing}
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
