<script lang="ts">
	// v67 (U9): a translated sentence with an error inside it ("Couldn't read the stats: …"),
	// the error marked lang="en" when it is the server's raw English (errors.ts' textLang), so
	// a screen reader speaks the fragment, and only the fragment, in English (WCAG 3.1.2).
	// `sentence` is the message with the error as its argument; it's rendered with a marker in
	// the error's place and split there, so a translation can put the error anywhere.
	import { textLang } from '$lib/i18n/errors';

	let { sentence, error }: { sentence: (error: string) => string; error: string } = $props();

	const MARK = '⁣';
	const parts = $derived(sentence(MARK).split(MARK));
</script>

{parts[0]}{#if parts.length > 1}<span lang={textLang(error)}>{error}</span>{parts
		.slice(1)
		.join(error)}{/if}
