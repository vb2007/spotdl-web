<script lang="ts">
	import '../app.css';
	import favicon from '$lib/assets/favicon.svg';
	import { page } from '$app/state';
	import AmbientField from '$lib/components/AmbientField.svelte';
	import { queue } from '$lib/stores/queue';
	import { link as streamLink } from '$lib/stores/link';

	let { children } = $props();

	const { activeTracks } = queue;
	// v40: the field warms only while `/` shows something receiving. Only `/` holds the live
	// stream; leaving it closes the stream but leaves `activeTracks` at its last value, so on
	// any other route the store is stale and must not light the page. v42: the same holds on
	// `/` while its stream is down -- the lanes may be stale, so nothing reads as receiving.
	const live = $derived(
		page.route.id === '/' && $activeTracks.length > 0 && $streamLink === 'live'
	);
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<AmbientField {live} />

{@render children()}
