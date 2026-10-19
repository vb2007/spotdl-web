// v47: what the submit box sends, out of what was pasted. It replaced the browser's own URL
// check (`novalidate`), which spoke the browser's language and turned away a link pasted
// with words or an emoji around it.
//
// The link is the whitespace-free token it sits in, from where the link starts: spotdl reads
// more than a bare link (`<youtube url>|<spotify url>` pins the audio, so a `|` pair is one
// link), and a token is what the browser's check took whole. Off its end goes whatever a
// sentence glues on: punctuation, an emoji (with its modifiers, a flag, a keycap). A Spotify
// link or URI ends at its id (base62) plus a link's optional query, since Hungarian writes a
// case ending onto a link with a hyphen ("…/album/<id>-t").

const START_RE = /https?:\/\/|spotify:/gi;
const SPOTIFY_RE =
	/^(?:https?:\/\/open\.spotify\.com\/(?:[A-Za-z0-9._-]+\/)+[A-Za-z0-9]+(?:\?[A-Za-z0-9=&%_-]*)?|spotify:[a-z]+(?::[^\s:<>"'()[\],|]+)*:[A-Za-z0-9]+)/i;
// Anything but a letter, a digit or a character a link ends in.
const GLUED_RE = /[^\p{L}\p{N}/=_\-&%#~+]+$/u;

/** How many links the text holds: each start counts, except the second half of a `|` pair. */
export function countLinks(text: string): number {
	let count = 0;
	for (const match of text.matchAll(START_RE)) {
		if (text[(match.index ?? 0) - 1] !== '|') count += 1;
	}
	return count;
}

/** The link to send (the form refuses text holding several, so there is one). */
export function linkIn(text: string): string | undefined {
	const start = text.search(START_RE);
	if (start === -1) return undefined;
	const token = text.slice(start).split(/\s/, 1)[0];
	if (!token.includes('|')) {
		const spotify = SPOTIFY_RE.exec(token);
		if (spotify) return spotify[0];
	}
	return token.replace(GLUED_RE, '') || undefined;
}
