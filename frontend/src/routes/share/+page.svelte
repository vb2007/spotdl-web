<!--
THESIS: a share lands as one incoming reading to confirm, not a form: what arrived, what it
tunes to (type and id), one transmit control already under the thumb.
OWN-WORLD: the instrument panel as shipped (DESIGN.md): .panel faceplate, mono readouts printed
on it (never in a .well), Sans sentences, the five conditions; no amber (nothing receives here).
STRUCTURE: masthead; h1; one panel holding the shared words, the readouts, then the action
row; the outcome reads above the row, which then holds the next step where the thumb was.
SIGNATURE: the readouts: label over a mono value, like the dial's own readout.
RISK: a short link needs a server round-trip before there is anything to read.
-->
<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { afterNavigate, replaceState } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import * as api from '$lib/api';
	import * as m from '$lib/paraglide/messages';
	import SubpageHeader from '$lib/components/SubpageHeader.svelte';
	import { errorText } from '$lib/i18n/errors';
	import { sharedLink, type SpotifyType } from '$lib/shareTarget';

	let { data } = $props();
	const isAdmin = $derived(data.session?.is_admin ?? false);
	// No page shows one job, so "open the queue" opens the viewer's own jobs, where the new one
	// is: an admin's dashboard may have been left in another view (all, others).
	const ownQueue = resolve('/') + '?view=mine';

	// v65: read once, as it arrived. The share target is a GET, so the share is the query.
	const params = page.url.searchParams;
	const shared = {
		title: params.get('title'),
		text: params.get('text'),
		url: params.get('url')
	};
	const link = sharedLink(shared);

	// The shared words without the link (Spotify's "Song · Artist", usually): the context that
	// says which song this is. Spotify's own metadata, so shown as sent, untranslated.
	const LINK_RE = /https?:\/\/\S+/gi;
	const context =
		[shared.title, shared.text]
			.map((field) => (field ?? '').replace(LINK_RE, '').replace(/\s+/g, ' ').trim())
			// One field often repeats the other (title "Song", text "Song · Artist"): keep the fuller.
			.filter(
				(field, i, all) =>
					field !== '' &&
					!all.some((other, j) => j !== i && other.includes(field) && (other !== field || j < i))
			)
			.join(' — ') || null;
	// With no link found, what did arrive, so the person can see why.
	const received =
		[shared.url, shared.text, shared.title]
			.map((field) => (field ?? '').trim())
			.filter(Boolean)
			.join(' ') || null;

	type Target = { type: SpotifyType; id: string; url: string };
	type Phase = 'none' | 'resolving' | 'resolve-failed' | 'ready' | 'queueing' | 'done';

	// Queued already from this history entry: the outcome again, never a second armed "queue it"
	// one stray Enter away from a duplicate job (review round 5). In the entry's state for a Back,
	// and in sessionStorage under the entry's index for a reload or a tab the phone discarded
	// (SvelteKit's first load starts the entry's state empty; review round 6).
	const entryIndex = (history.state as Record<string, unknown> | null)?.['sveltekit:history'];
	// i18n-ignore: a storage key
	const storageKey = `spotdl:share-queued:${String(entryIndex)}:${window.location.search}`;
	function storedQueued(): App.PageState['shareQueued'] | null {
		try {
			const raw = sessionStorage.getItem(storageKey);
			return raw ? JSON.parse(raw) : null;
		} catch {
			return null;
		}
	}
	const queuedBefore = page.state.shareQueued ?? storedQueued();
	const outcomeFor = (hint: api.CreateJobHint | undefined) =>
		hint === 'already_queued'
			? m.share_already_queued
			: hint === 'in_library'
				? m.share_queued_in_library
				: m.share_queued;

	let target = $state<Target | null>(queuedBefore ?? (link?.kind === 'full' ? link : null));
	let phase = $state<Phase>(
		queuedBefore ? 'done' : link === null ? 'none' : link.kind === 'full' ? 'ready' : 'resolving'
	);
	let problem = $state<(() => string) | null>(null);
	// A look-up that can pass on a second try (the host down, busy or throttling, the network);
	// a link that leads nowhere (422) fails the same way every time, so it gets no retry.
	let retryable = $state(false);
	let outcome = $state<(() => string) | null>(queuedBefore ? outcomeFor(queuedBefore.hint) : null);
	// Only a track already in the library is settled at once; a new or still-queued one is
	// in flight, never mint (DESIGN.md §2).
	let outcomeSettled = $state(queuedBefore?.hint === 'in_library');

	let queueButton: HTMLButtonElement | undefined = $state();
	let retryButton: HTMLButtonElement | undefined = $state();
	let queueLink: HTMLAnchorElement | undefined = $state();

	const TYPE_LABEL: Record<SpotifyType, () => string> = {
		track: m.share_type_track,
		album: m.share_type_album,
		artist: m.share_type_artist,
		playlist: m.share_type_playlist
	};

	// Focus goes where the next press is: "Queue it" once there is something to queue, "try
	// again" after a failed look-up, the queue link once it's done (or nothing was found).
	async function focusNext(): Promise<void> {
		await tick();
		const next =
			phase === 'ready'
				? queueButton
				: phase === 'resolve-failed'
					? (retryButton ?? queueLink)
					: phase === 'done' || phase === 'none'
						? queueLink
						: undefined;
		next?.focus();
	}

	async function lookUp(): Promise<void> {
		if (link?.kind !== 'short') return;
		phase = 'resolving';
		problem = null;
		try {
			target = await api.resolveLink(link.url);
			phase = 'ready';
		} catch (err) {
			problem = () => errorText(err, m.share_resolve_failed);
			retryable = !(err instanceof api.ApiError && err.status === 422);
			phase = 'resolve-failed';
		}
		await focusNext();
	}

	async function queueIt(): Promise<void> {
		if (target === null || phase !== 'ready') return;
		phase = 'queueing';
		problem = null;
		try {
			// Only the canonical link, with the allowlist enforced by the server (`share`).
			const job = await api.createJob(target.url, 'share');
			outcome = outcomeFor(job.hint);
			outcomeSettled = job.hint === 'in_library';
			phase = 'done';
			queued = { ...target, hint: job.hint ?? null };
		} catch (err) {
			problem = () => errorText(err, m.share_failed);
			phase = 'ready';
		}
		// Recorded only while this page is still the one shown (a slow create answered after
		// "not now" must not mark the dashboard's entry), and outside the try: a history write
		// failing says nothing about the job, which exists.
		if (queued && !left) remember(queued);
		await focusNext();
	}

	let queued: App.PageState['shareQueued'] | null = null;
	let left = false;
	function remember(entry: NonNullable<App.PageState['shareQueued']>): void {
		try {
			sessionStorage.setItem(storageKey, JSON.stringify(entry));
		} catch {
			// Storage full or off: the history state below still covers a Back.
		}
		try {
			replaceState('', { ...page.state, shareQueued: entry });
		} catch {
			// The browser refused a history write (rate limit): the outcome is on screen anyway.
		}
	}

	onMount(() => {
		if (link?.kind === 'short' && !queuedBefore) lookUp();
		else focusNext();
		return () => (left = true);
	});

	// Arriving from the login round-trip is a navigation, and the layout then puts focus on the
	// page's h1 (after a tick): take it back for the action, after the layout's turn.
	afterNavigate(async ({ type }) => {
		if (type === 'enter') return;
		await tick();
		await tick();
		await focusNext();
	});
</script>

<svelte:head>
	<title>{m.share_title()}</title>
</svelte:head>

<div class="stage">
	<SubpageHeader {isAdmin} />

	<main id="main" class="main">
		<h1 class="page-title">{m.share_heading()}</h1>

		<section class="panel incoming">
			{#if phase === 'none'}
				<p class="sentence" id="share-none">{m.share_none()}</p>
				<p class="hint" id="share-none-hint">{m.share_none_hint()}</p>
				{#if received}
					<div class="reading">
						<span class="label">{m.share_received()}</span>
						<p class="mono value received">{received}</p>
					</div>
				{/if}
				<div class="actions">
					<!-- eslint-disable svelte/no-navigation-without-resolve -- resolve('/') plus ?view=mine, which resolve() can't type (as v54's ?view= writes) -->
					<!-- The page's one next step, focused from the first paint (see "queue it" below). -->
					<!-- svelte-ignore a11y_autofocus -->
					<a
						class="btn"
						href={ownQueue}
						autofocus
						aria-describedby="share-none share-none-hint"
						bind:this={queueLink}>{m.share_open_queue()}</a
					>
					<!-- eslint-enable svelte/no-navigation-without-resolve -->
				</div>
			{:else}
				{#if context}
					<p class="context" id="share-context">{context}</p>
				{/if}
				<dl class="readings" id="share-reading">
					{#if target}
						<div class="reading">
							<dt class="label">{m.share_type()}</dt>
							<dd class="mono value">{TYPE_LABEL[target.type]()}</dd>
						</div>
						<div class="reading">
							<dt class="label">{m.share_id()}</dt>
							<dd class="mono value">{target.id}</dd>
						</div>
					{:else if link?.kind === 'short'}
						<div class="reading">
							<dt class="label">{m.share_short_link()}</dt>
							<dd class="mono value">{link.url}</dd>
						</div>
					{/if}
				</dl>

				<!-- The outcome, once there is one, reads at the shared words' register, then the action
				     row: the next step where the thumb was. The live region is there from the start. -->
				<!-- One status region for the whole visit, its text changing (a region inserted together
				     with its text often goes unannounced): the look-up while it runs, then the outcome. -->
				<p
					class="outcome"
					class:settled={outcomeSettled}
					class:pending={phase === 'resolving'}
					id="share-outcome"
					role="status"
				>
					{phase === 'resolving' ? m.share_resolving() : (outcome?.() ?? '')}
				</p>
				<div class="actions">
					{#if phase === 'resolve-failed' && retryable}
						<button type="button" class="btn" bind:this={retryButton} onclick={lookUp}
							>{m.share_retry()}</button
						>
						<a class="quiet-link" href={resolve('/')}>{m.share_not_now()}</a>
					{:else if phase === 'resolve-failed'}
						<!-- eslint-disable svelte/no-navigation-without-resolve -- resolve('/') plus ?view=mine, as below -->
						<a class="btn" href={ownQueue} aria-describedby="share-problem" bind:this={queueLink}
							>{m.share_open_queue()}</a
						>
						<!-- eslint-enable svelte/no-navigation-without-resolve -->
					{:else if phase === 'ready' || phase === 'queueing'}
						<!-- The plan's "queue it focused": a share opens /share as a full page load, and
						     SvelteKit's first-load focus reset moves focus to <body> after onMount unless
						     an element is marked autofocus (live review). -->
						<!-- svelte-ignore a11y_autofocus -->
						<button
							type="button"
							class="btn primary"
							autofocus
							aria-disabled={phase === 'queueing' ? 'true' : undefined}
							bind:this={queueButton}
							aria-describedby={context ? 'share-context share-reading' : 'share-reading'}
							onclick={queueIt}
							>{phase === 'queueing' ? m.share_queueing() : m.share_queue()}</button
						>
						<a class="quiet-link" href={resolve('/')}>{m.share_not_now()}</a>
					{:else if phase === 'done'}
						<!-- eslint-disable svelte/no-navigation-without-resolve -- resolve('/') plus ?view=mine, as above -->
						<a class="btn" href={ownQueue} aria-describedby="share-outcome" bind:this={queueLink}
							>{m.share_open_queue()}</a
						>
						<!-- eslint-enable svelte/no-navigation-without-resolve -->
					{/if}
				</div>
				<p class="form-error" id="share-problem" role="alert">{problem?.() ?? ''}</p>
			{/if}
		</section>
	</main>
</div>

<style>
	.stage {
		max-width: 64rem;
		margin: 0 auto;
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.main {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		margin-top: var(--space-2);
		max-width: 32rem;
	}

	.incoming {
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	/* Spotify's own words about what was shared: the line that says which song this is. */
	.context {
		font-size: var(--fs-lead);
		font-weight: var(--fw-medium);
		color: var(--text-primary);
		overflow-wrap: anywhere;
	}

	.sentence {
		font-size: var(--fs-lead);
		font-weight: var(--fw-medium);
	}

	.hint {
		font-size: var(--fs-detail);
		color: var(--text-muted);
		max-width: 68ch;
	}

	/* The readout row: the type's short word, then the id; side by side at every width. */
	.readings {
		display: grid;
		grid-template-columns: minmax(min-content, 1fr) minmax(0, 2.5fr);
		gap: var(--space-3) var(--space-4);
		margin: 0;
	}

	/* A short link alone (before it's resolved) takes the whole row. */
	.reading:only-child {
		grid-column: 1 / -1;
	}

	.reading {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}

	/* A readout, not a field: the value printed under its label on the faceplate, with no
	   control edge or recess to read as something to tap and edit. */
	.value {
		margin: 0;
		font-size: var(--fs-body);
		color: var(--text-primary);
		overflow-wrap: anywhere;
	}

	.received {
		font-size: var(--fs-detail);
		color: var(--text-muted);
		max-height: 6.5em;
		overflow: auto;
	}

	.actions {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-3) var(--space-5);
		min-height: 2.75rem;
	}

	/* The page's one action, a size up (as /login's connect): what the share came here to do. */
	.primary {
		padding: var(--space-3) var(--space-5);
		font-size: var(--fs-body);
	}

	/* A link dressed as the page's one action: a .btn, not underlined text (as +error.svelte). */
	.actions .btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		text-decoration: none;
	}

	/* aria-disabled, not disabled, while queueing: a disabled button drops its focus to <body>,
	   and a slow create left a keyboard user starting over from the top (live review, round 2).
	   queueIt's phase guard makes a second press a no-op. */
	.primary[aria-disabled='true'] {
		cursor: progress;
	}

	.quiet-link {
		font-size: var(--fs-detail);
		color: var(--text-muted);
	}

	.quiet-link:hover,
	.quiet-link:focus-visible {
		color: var(--text-primary);
	}

	/* The look-up in progress: a quiet line, not news. */
	.outcome.pending {
		font-size: var(--fs-detail);
		font-weight: var(--fw-regular);
		color: var(--text-muted);
	}

	/* What happened is the news the person stayed for: the shared words' register. */
	.outcome {
		font-size: var(--fs-lead);
		font-weight: var(--fw-medium);
		color: var(--text-primary);
	}

	.outcome.settled {
		color: var(--settled);
	}

	/* An empty live region leaves the flow (DESIGN.md: never display: none). */
	.outcome:empty {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
	}

	@media (max-width: 40em) {
		.stage {
			padding: var(--space-4);
		}

		/* On a phone the action takes the row's width: the thumb's target. */
		.primary,
		.actions > .btn {
			flex: 1 1 100%;
			text-align: center;
		}
	}
</style>
