<script lang="ts">
	import { resolve } from '$app/paths';

	// v43: the masthead of /settings, /library and /account, in the same terms as `/`'s
	// (the wordmark left, the page links right). The page's own h1 opens its <main>
	// (`.page-title`, app.css), so every piece of content sits inside a landmark. The admin pages
	// are linked for the admin only: a non-admin reaches them only by typing the path
	// (owner's decision), and then gets AdminOnlyNotice.
	let {
		current,
		isAdmin
	}: { current: 'settings' | 'library' | 'stats' | 'account'; isAdmin: boolean } = $props();
</script>

<header class="masthead">
	<span class="wordmark mono" aria-hidden="true">SPOTDL // WEB</span>
	<nav class="pages" aria-label="Pages">
		<a class="nav-link mono" href={resolve('/')}>queue</a>
		{#if isAdmin}
			<a
				class="nav-link mono"
				href={resolve('/library')}
				aria-current={current === 'library' ? 'page' : undefined}>library</a
			>
			<a
				class="nav-link mono"
				href={resolve('/settings')}
				aria-current={current === 'settings' ? 'page' : undefined}>settings</a
			>
			<a
				class="nav-link mono"
				href={resolve('/stats')}
				aria-current={current === 'stats' ? 'page' : undefined}>stats</a
			>
		{/if}
		<a
			class="nav-link mono"
			href={resolve('/account')}
			aria-current={current === 'account' ? 'page' : undefined}>account</a
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

	.nav-link:hover,
	.nav-link:focus-visible {
		color: var(--text-primary);
		text-decoration-color: currentColor;
	}

	/* The page you're on: primary text and no underline, a place rather than a link. */
	.nav-link[aria-current='page'] {
		color: var(--text-primary);
		text-decoration: none;
	}

	@media (pointer: coarse) {
		.nav-link {
			display: inline-flex;
			align-items: center;
			min-height: 2.75rem;
		}
	}
</style>
