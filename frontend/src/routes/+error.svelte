<!--
	v62 (F5): the app's own error page. An unknown address (a mistyped link, an old bookmark) or a
	route that failed to load lands here, inside the app, instead of the browser's or nginx's
	plain 404. Under adapter-static there's no server to render it: nginx answers an unknown path
	with the SPA shell (404.html, `error_page`), whose router finds no route and renders this.
	The way home is a plain link, first in the tab order after the masthead, and `g d` works too.
-->
<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import SubpageHeader from '$lib/components/SubpageHeader.svelte';
	import * as m from '$lib/paraglide/messages';

	const notFound = $derived(page.status === 404);
	const isAdmin = $derived(page.data.session?.is_admin ?? false);
</script>

<svelte:head>
	<title>{notFound ? m.error_not_found_title() : m.error_title()}</title>
</svelte:head>

<div class="stage">
	<SubpageHeader {isAdmin} />

	<main id="main" class="main">
		<section class="panel notice" aria-labelledby="error-heading">
			<h1 id="error-heading" class="page-title">
				{notFound ? m.error_not_found_heading() : m.error_heading()}
			</h1>
			{#if notFound}
				<p>{m.error_not_found_body()}</p>
				<!-- i18n-ignore: the address as typed, a reading, not prose. -->
				<p class="address mono">{page.url.pathname}</p>
			{:else}
				<p>{m.error_body()}</p>
				<p class="address mono">{m.error_status({ status: String(page.status) })}</p>
			{/if}
			<p class="actions">
				<a class="btn" href={resolve('/')}>{m.error_home()}</a>
			</p>
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
		margin-top: var(--space-2);
		max-width: 44rem;
	}

	.notice {
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.notice p {
		max-width: 68ch;
		color: var(--text-muted);
	}

	/* The address is what was asked for: a reading, full strength, broken anywhere so a long
	   one never widens the page. */
	.notice .address {
		color: var(--text-primary);
		font-size: var(--fs-detail);
		overflow-wrap: anywhere;
	}

	.actions {
		margin-top: var(--space-2);
	}

	/* A link dressed as the page's one action: a .btn, not underlined text. */
	.actions .btn {
		display: inline-flex;
		text-decoration: none;
	}

	@media (max-width: 40em) {
		.stage {
			padding: var(--space-4);
		}

		.notice {
			padding: var(--space-4);
		}
	}
</style>
