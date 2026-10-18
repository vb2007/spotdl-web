<script lang="ts">
	import { LANGUAGES } from '$lib/i18n/locale.svelte';
	import type { Locale } from '$lib/paraglide/runtime';

	// v46: the language choice on /account, saved to the profile. A `.choice-group` like every
	// few-values choice (DESIGN.md §6). Each button is marked with its own `lang`, so a screen
	// reader says "Magyar" in Hungarian.
	let {
		current,
		onchoose,
		disabled = false,
		labelledby,
		describedby
	}: {
		current: Locale;
		onchoose: (locale: Locale) => void;
		disabled?: boolean;
		/** The visible label's id. */
		labelledby: string;
		describedby?: string;
	} = $props();
</script>

<div class="choice-group" role="group" aria-labelledby={labelledby} aria-describedby={describedby}>
	{#each LANGUAGES as language (language.code)}
		<button
			type="button"
			lang={language.code}
			aria-pressed={current === language.code}
			{disabled}
			onclick={() => onchoose(language.code)}>{language.name}</button
		>
	{/each}
</div>
