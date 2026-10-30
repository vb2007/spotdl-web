<!--
THESIS: a share lands as one incoming reading to confirm, not a form: what arrived, what it
tunes to (type and id), one transmit control already under the thumb.
OWN-WORLD: the instrument panel as shipped (DESIGN.md): .panel faceplate, mono readings in
recessed wells, Sans sentences, the five conditions; no amber (nothing is receiving here).
STRUCTURE: masthead; h1; one panel holding the shared words, the readings, then the action
row; the outcome replaces the action row in place, so nothing moves under the finger.
SIGNATURE: the readings block: label over a mono well, like the dial's own readout.
RISK: a short link needs a server round-trip before there is anything to read.
-->
<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { afterNavigate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import * as api from '$lib/api';
	import * as m from '$lib/paraglide/messages';
	import SubpageHeader from '$lib/components/SubpageHeader.svelte';
	import { errorText } from '$lib/i18n/errors';
	import { sharedLink, type SpotifyType } from '$lib/shareTarget';

	let { data } = $props();
	const isAdmin = $derived(data.session?.is_admin ?? false);

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

	let target = $state<Target | null>(link?.kind === 'full' ? link : null);
	let phase = $state<Phase>(link === null ? 'none' : link.kind === 'full' ? 'ready' : 'resolving');
	let problem = $state<(() => string) | null>(null);
	let outcome = $state<(() => string) | null>(null);
	// Only a track already in the library is settled at once; a new or still-queued one is
	// in flight, never mint (DESIGN.md §2).
	let outcomeSettled = $state(false);

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
					? retryButton
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
			outcome =
				job.hint === 'already_queued'
					? m.dashboard_submit_already_queued
					: job.hint === 'in_library'
						? m.share_queued_in_library
						: m.share_queued;
			outcomeSettled = job.hint === 'in_library';
			phase = 'done';
		} catch (err) {
			problem = () => errorText(err, m.share_failed);
			phase = 'ready';
		}
		await focusNext();
	}

	onMount(() => {
		if (link?.kind === 'short') lookUp();
		else focusNext();
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
					<a
						class="btn"
						href={resolve('/')}
						aria-describedby="share-none share-none-hint"
						bind:this={queueLink}>{m.share_open_queue()}</a
					>
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
				<p class="outcome" class:settled={outcomeSettled} id="share-outcome" role="status">
					{outcome?.() ?? ''}
				</p>
				<div class="actions">
					{#if phase === 'resolving'}
						<p class="pending" role="status">{m.share_resolving()}</p>
					{:else if phase === 'resolve-failed'}
						<button type="button" class="btn" bind:this={retryButton} onclick={lookUp}
							>{m.share_retry()}</button
						>
						<a class="quiet-link" href={resolve('/')}>{m.share_not_now()}</a>
					{:else if phase === 'ready' || phase === 'queueing'}
						<button
							type="button"
							class="btn primary"
							disabled={phase === 'queueing'}
							bind:this={queueButton}
							aria-describedby={context ? 'share-context share-reading' : 'share-reading'}
							onclick={queueIt}
							>{phase === 'queueing' ? m.share_queueing() : m.share_queue()}</button
						>
						<a class="quiet-link" href={resolve('/')}>{m.share_not_now()}</a>
					{:else if phase === 'done'}
						<a
							class="btn"
							href={resolve('/')}
							aria-describedby="share-outcome"
							bind:this={queueLink}>{m.share_open_queue()}</a
						>
					{/if}
				</div>
				<p class="form-error" role="alert">{problem?.() ?? ''}</p>
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

	.primary:disabled {
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

	.pending {
		font-size: var(--fs-detail);
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
