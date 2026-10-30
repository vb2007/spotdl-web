<script lang="ts">
	import { resolve } from '$app/paths';
	import * as m from '$lib/paraglide/messages';

	// v43: the masthead of /settings, /library and /account, in the same terms as `/`'s
	// (the wordmark left, the page links right). The page's own h1 opens its <main>
	// (`.page-title`, app.css), so every piece of content sits inside a landmark. The admin pages
	// are linked for the admin only: a non-admin reaches them only by typing the path
	// (owner's decision), and then gets AdminOnlyNotice.
	let {
		current,
		isAdmin
	}: {
		// v62: none on the error page (+error.svelte), which is none of these.
		current?: 'settings' | 'library' | 'stats' | 'account';
		isAdmin: boolean;
	} = $props();
</script>

<header class="masthead">
	<!-- i18n-ignore: the wordmark is a name, the same in every language. -->
	<span class="wordmark mono" aria-hidden="true">SPOTDL // WEB</span>
	<nav class="pages" aria-label={m.nav_pages()}>
		<a class="nav-link" href={resolve('/')}>{m.nav_queue()}</a>
		{#if isAdmin}
			<a
				class="nav-link"
				href={resolve('/library')}
				aria-current={current === 'library' ? 'page' : undefined}>{m.nav_library()}</a
			>
			<a
				class="nav-link"
				href={resolve('/settings')}
				aria-current={current === 'settings' ? 'page' : undefined}>{m.nav_settings()}</a
			>
		{/if}
		<!-- v66: /stats is everyone's now (their own downloads; the admin also everyone's). -->
		<a
			class="nav-link"
			href={resolve('/stats')}
			aria-current={current === 'stats' ? 'page' : undefined}>{m.nav_stats()}</a
		>
		<a
			class="nav-link"
			href={resolve('/account')}
			aria-current={current === 'account' ? 'page' : undefined}>{m.nav_account()}</a
		>
	</nav>
</header>

<style>
	.masthead {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-5);
	}

	.wordmark {
		font-size: var(--fs-lead);
		font-weight: var(--fw-strong);
		letter-spacing: 0.14em;
		line-height: 1.2;
		color: var(--text-primary);
	}

	.pages {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-4);
		font-size: var(--fs-detail);
	}

	/* `/`'s nav link: marked by its underline, never by amber (F10). */
	.nav-link {
		color: var(--text-muted);
		text-decoration: underline;
		text-decoration-color: var(--line-control);
		text-underline-offset: 0.3em;
	}

	.nav-link:focus-visible {
		color: var(--text-primary);
		text-decoration-color: currentColor;
	}

	@media (hover: hover) {
		.nav-link:hover {
			color: var(--text-primary);
			text-decoration-color: currentColor;
		}
	}

	/* The page you're on: primary text and no underline, a place rather than a link. */
	.nav-link[aria-current='page'] {
		color: var(--text-primary);
		text-decoration: none;
	}

	/* v47: a phone's admin masthead wrapped its six links onto a third row in Hungarian. */
	@media (max-width: 40em) {
		.pages {
			column-gap: var(--space-3);
		}
	}

	@media (pointer: coarse) {
		.nav-link {
			display: inline-flex;
			align-items: center;
			justify-content: center;
			min-height: 2.75rem;
			min-width: 2.75rem;
		}
	}
</style>
