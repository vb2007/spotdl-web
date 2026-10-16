<script lang="ts">
	import { resolve } from '$app/paths';

	// v43 (F17): what a non-admin sees on an admin page reached by typing its path. It makes
	// no admin request (the page renders it instead of its sections), so nothing spins and
	// nothing claims a state it couldn't read. The backend's require_admin stays the real gate.
	let { what }: { what: string } = $props();
</script>

<section class="panel notice" aria-labelledby="admin-only-heading">
	<h2 id="admin-only-heading" class="heading">Only the admin can use this page</h2>
	<p class="body">
		{what} is shared by everyone on this server, so only the admin can change it. Your own preferences
		are on your <a href={resolve('/account')}>account page</a>.
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
</style>
