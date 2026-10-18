<script lang="ts">
	// v46: a message that needs inline markup keeps it in the sentence ("<kbd>j</kbd> and
	// <kbd>k</kbd> move between rows"), so a translation can move the keys where its grammar
	// wants them. Only the tags below become elements; everything else stays text (never
	// {@html}), so a message can't inject markup.
	let { text }: { text: string } = $props();

	type Segment = { tag: 'kbd' | 'strong' | 'em' | null; text: string };

	const segments = $derived.by(() => {
		const out: Segment[] = [];
		const pattern = /<(kbd|strong|em)>(.*?)<\/\1>/g;
		let last = 0;
		for (const match of text.matchAll(pattern)) {
			if (match.index > last) out.push({ tag: null, text: text.slice(last, match.index) });
			out.push({ tag: match[1] as Segment['tag'], text: match[2] });
			last = match.index + match[0].length;
		}
		if (last < text.length) out.push({ tag: null, text: text.slice(last) });
		return out;
	});
</script>

{#each segments as segment, i (i)}{#if segment.tag === 'kbd'}<kbd>{segment.text}</kbd
		>{:else if segment.tag === 'strong'}<strong>{segment.text}</strong
		>{:else if segment.tag === 'em'}<em>{segment.text}</em>{:else}{segment.text}{/if}{/each}
