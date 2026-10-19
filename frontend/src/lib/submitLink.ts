// v47: what the submit box sends, out of what was pasted. It replaced the browser's own URL
// check (`novalidate`), which spoke the browser's language and turned away a link pasted
// with words or an emoji around it.

// A Spotify link ends at its id (base62) plus an optional query: Hungarian writes a case
// ending onto a link with a hyphen ("…/album/<id>-t"), and that is the sentence's, not the
// id's. A `spotify:` URI (which the browser's check accepted) keeps every part, legacy
// `spotify:user:<name>:playlist:<id>` included. Brackets and parentheses end any link, so a
// Markdown link counts as the two it holds.
const SPOTIFY_RE =
	/https?:\/\/open\.spotify\.com\/(?:[a-z-]+\/)+[A-Za-z0-9]+(?:\?[A-Za-z0-9=&%_-]*)?|spotify:[a-z]+(?::[^\s:<>"'()[\],]+)+/i;
const LINK_RE = /https?:\/\/[^\s<>"'()[\],]+/i;
const ANY_LINK_RE = /https?:\/\/[^\s<>"'()[\],]+|spotify:[a-z]+(?::[^\s:<>"'()[\],]+)+/gi;

/** How many links (or `spotify:` URIs) the text holds. */
export function countLinks(text: string): number {
	return (text.match(ANY_LINK_RE) ?? []).length;
}

/** The link to send: a Spotify link or URI wherever it is, else the first http(s) link,
 * minus whatever the sentence glued onto its end ("…/album/abc.", an emoji, "…"). */
export function linkIn(text: string): string | undefined {
	const found = SPOTIFY_RE.exec(text)?.[0] ?? LINK_RE.exec(text)?.[0];
	return found?.replace(/[^A-Za-z0-9/=_]+$/u, '');
}
