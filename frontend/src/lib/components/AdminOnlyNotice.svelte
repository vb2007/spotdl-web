<script lang="ts">
	import { resolve } from '$app/paths';
	import * as m from '$lib/paraglide/messages';

	// v43 (F17): what a non-admin sees on an admin page reached by typing its path. It makes
	// no admin request (the page renders it instead of its sections), so nothing spins and
	// nothing claims a state it couldn't read. The backend's require_admin stays the real gate.
	// v46: `page` picks the whole sentence (one message per page, so a translation never glues
	// a subject to a reason): settings and library change shared setup, stats only reads but
	// counts every user's downloads together.
	let { page }: { page: 'settings' | 'library' | 'stats' } = $props();

	const body = $derived(
		page === 'settings'
			? m.adminonly_body_settings()
			: page === 'library'
				? m.adminonly_body_library()
				: m.adminonly_body_stats()
	);

	// The account link sits inside the sentence (`<a>…</a>` in the message), where the
	// translation's grammar puts it.
	const parts = $derived.by(() => {
		const match = /^(.*?)<a>(.*?)<\/a>(.*)$/s.exec(body);
		return match
			? { before: match[1], link: match[2], after: match[3] }
			: { before: body, link: '', after: '' };
	});
</script>

<section class="panel notice" aria-labelledby="admin-only-heading">
	<h2 id="admin-only-heading" class="heading">{m.adminonly_heading()}</h2>
	<p class="body">
		{parts.before}{#if parts.link}<a href={resolve('/account')}>{parts.link}</a>{/if}{parts.after}
	</p>
</section>

<style>
	.notice {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-5);
		max-width: 40rem;
	}

	.heading {
		font-size: var(--fs-lead);
		font-weight: var(--fw-medium);
	}

	.body {
		color: var(--text-muted);
		max-width: 60ch;
	}

	/* v47: a phone's panel inset, as every other plate has. */
	@media (max-width: 40em) {
		.notice {
			padding: var(--space-4);
		}
	}
</style>
