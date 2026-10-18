<script lang="ts">
	import * as m from '$lib/paraglide/messages';
	import { LANGUAGES } from '$lib/i18n/locale.svelte';
	import type { Locale } from '$lib/paraglide/runtime';

	// v46: the language choice on /account, saved to the profile. A `.choice-group` like every
	// few-values choice (DESIGN.md §6). "Automatic" (owner's answer on PR #68) follows the
	// browser, and names the language that gives, in that language's own name. Every language
	// name is marked with its own `lang`, so a screen reader says "Magyar" in Hungarian.
	let {
		preference,
		detected,
		onchoose,
		disabled = false,
		labelledby,
		describedby
	}: {
		/** The saved language, `null` for automatic. */
		preference: Locale | null;
		/** What automatic resolves to: the browser's language. */
		detected: Locale;
		onchoose: (locale: Locale | null) => void;
		disabled?: boolean;
		/** The visible label's id. */
		labelledby: string;
		describedby?: string;
	} = $props();

	// The automatic label with the detected language's name set apart, so the name carries its
	// own `lang` ("automatic (Magyar)").
	const NAME = '\u0000';
	const auto = $derived.by(() => {
		const [before, after = ''] = m.account_language_auto({ language: NAME }).split(NAME);
		const name = LANGUAGES.find((language) => language.code === detected)?.name ?? detected;
		return { before, name, after };
	});
</script>

<div class="choice-group" role="group" aria-labelledby={labelledby} aria-describedby={describedby}>
	<button type="button" aria-pressed={preference === null} {disabled} onclick={() => onchoose(null)}
		>{auto.before}<span lang={detected}>{auto.name}</span>{auto.after}</button
	>
	{#each LANGUAGES as language (language.code)}
		<button
			type="button"
			lang={language.code}
			aria-pressed={preference === language.code}
			{disabled}
			onclick={() => onchoose(language.code)}>{language.name}</button
		>
	{/each}
</div>
