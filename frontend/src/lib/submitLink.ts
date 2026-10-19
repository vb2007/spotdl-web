// v47: what the submit box sends, out of what was pasted. It replaced the browser's own URL
// check (`novalidate`), which spoke the browser's language and turned away a link pasted
// with words or an emoji around it.

// A Spotify link or URI ends at its id (base62), a link plus an optional query: Hungarian
// writes a case ending onto a link with a hyphen ("…/album/<id>-t"), and that is the
// sentence's, not the id's. What comes before the id may be anything a username holds (a
// legacy `/user/<name>/playlist/<id>` or `spotify:user:<name>:playlist:<id>`, a locale's
// `/intl-hu/`). Brackets and parentheses end any link, so a Markdown link counts as the two
// it holds.
const SPOTIFY_RE =
	/https?:\/\/open\.spotify\.com\/(?:[A-Za-z0-9._-]+\/)+[A-Za-z0-9]+(?:\?[A-Za-z0-9=&%_-]*)?|spotify:[a-z]+(?::[^\s:<>"'()[\],]+)*:[A-Za-z0-9]+/i;
const LINK_RE = /https?:\/\/[^\s<>"'()[\],]+/i;
const ANY_LINK_RE =
	/https?:\/\/[^\s<>"'()[\],]+|spotify:[a-z]+(?::[^\s:<>"'()[\],]+)*:[A-Za-z0-9]+/gi;

/** How many links (or `spotify:` URIs) the text holds. */
export function countLinks(text: string): number {
	return (text.match(ANY_LINK_RE) ?? []).length;
}

// One token that is already a link goes as it is: that is what the browser's check accepted,
// and spotdl reads more than a bare link (`<youtube url>|<spotify url>` pins the audio; a
// YouTube playlist id may end in "-"). A lone Spotify link still ends at its id.
const SINGLE_RE = /^(?:https?:\/\/|spotify:)\S+$/i;
// What a sentence glues onto the end of another link: punctuation and emoji, never "-".
const GLUED_RE = /[.,;:!?…"'»”’\p{Extended_Pictographic}\uFE0F]+$/u;

/** The link to send (the form refuses text holding several, so there is one). A single
 * token is sent as it is (a Spotify link cut at its id); out of surrounding words, a Spotify
 * link or URI ends at its id, any other link loses the punctuation or emoji glued on. */
export function linkIn(text: string): string | undefined {
	const trimmed = text.trim();
	const spotify = SPOTIFY_RE.exec(trimmed);
	if (SINGLE_RE.test(trimmed)) {
		return spotify?.index === 0 && !trimmed.includes('|') ? spotify[0] : trimmed;
	}
	if (spotify) return spotify[0];
	return LINK_RE.exec(trimmed)?.[0].replace(GLUED_RE, '');
}
