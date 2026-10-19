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

/** The link to send (the form refuses text holding several, so there is one): read as a
 * Spotify link or URI where it is one, else as any http(s) link, minus whatever the sentence
 * glued onto its end ("…/album/abc.", an emoji, "…"). */
export function linkIn(text: string): string | undefined {
	const found = SPOTIFY_RE.exec(text)?.[0] ?? LINK_RE.exec(text)?.[0];
	return found?.replace(/[^A-Za-z0-9/=_]+$/u, '');
}
