// v65: what a share into the installed app (the manifest's `share_target`, GET `/share`) holds.
//
// A share arrives as up to three query parameters, `title`, `text` and `url`, filled however
// the sharing app chose: Spotify's puts its link in `text` (Android has no separate URL field),
// sometimes after words of its own, and often as a `spotify.link` short link rather than the
// `open.spotify.com` one. The first Spotify link wins, looked for in `url`, then `text`, then
// `title`, each from left to right.
//
// The client only extracts. A full link is read here by the same rules as the server's allowlist
// (backend/app/services/spotify_urls.py's `parse`), so the page can show what it would queue; a
// short link only the server can resolve (`/api/links/resolve`). Either way the page submits
// the canonical link with the allowlist enforced by the server, never the text it was given.

export type SpotifyType = 'track' | 'album' | 'artist' | 'playlist';

export type SharedLink =
	{ kind: 'full'; type: SpotifyType; id: string; url: string } | { kind: 'short'; url: string };

export interface ShareParams {
	title?: string | null;
	text?: string | null;
	url?: string | null;
}

const TYPES: readonly string[] = ['track', 'album', 'artist', 'playlist'];
// Spotify ids are 22 base-62 characters.
const ID_RE = /^[0-9A-Za-z]{22}$/;
// The locale segment Spotify puts before the type for a non-English page (`intl-hu`).
const INTL_RE = /^intl-[a-z]{2,3}(?:-[a-z0-9]{2,8})?$/i;
const SHORT_HOSTS = ['spotify.link', 'spotify.app.link'];
const SHORT_CODE_RE = /^[0-9A-Za-z_-]{1,64}$/;
const START_RE = /https?:\/\//gi;
// What a sentence glues onto a link's end: punctuation, an emoji, a closing bracket.
const GLUED_RE = /[^\p{L}\p{N}/=_\-&%#~+]+$/u;
// A character a link can't start after: one that would make it part of another link (its
// query, `?u=https://…`) or of a word.
const INSIDE_RE = /[\p{L}\p{N}=&%?/._~+#-]/u;

/** A full `open.spotify.com` track/album/artist/playlist link, by the server's rules. */
export function parseSpotifyLink(text: string): SharedLink | null {
	let parsed: URL;
	try {
		parsed = new URL(text);
	} catch {
		return null;
	}
	if (!['http:', 'https:'].includes(parsed.protocol)) return null;
	if (parsed.hostname !== 'open.spotify.com') return null;
	if (parsed.username || parsed.password || parsed.port) return null;
	let segments = parsed.pathname.split('/').filter(Boolean);
	if (segments.length > 0 && INTL_RE.test(segments[0])) segments = segments.slice(1);
	if (segments.length !== 2) return null;
	const [type, id] = segments;
	if (!TYPES.includes(type) || !ID_RE.test(id)) return null;
	return {
		kind: 'full',
		type: type as SpotifyType,
		id,
		url: `https://open.spotify.com/${type}/${id}`
	};
}

/** A `spotify.link` short link (https, a bare code), as the server will ask for it. */
export function parseShortLink(text: string): SharedLink | null {
	let parsed: URL;
	try {
		parsed = new URL(text);
	} catch {
		return null;
	}
	if (parsed.protocol !== 'https:' || !SHORT_HOSTS.includes(parsed.hostname)) return null;
	if (parsed.username || parsed.password || parsed.port) return null;
	const segments = parsed.pathname.split('/').filter(Boolean);
	if (segments.length !== 1 || !SHORT_CODE_RE.test(segments[0])) return null;
	return { kind: 'short', url: `https://${parsed.hostname}/${segments[0]}` };
}

/** The first Spotify link in one field, from left to right. */
function linkInField(text: string): SharedLink | null {
	for (const match of text.matchAll(START_RE)) {
		if (match.index > 0 && INSIDE_RE.test(text[match.index - 1])) continue;
		const token = text
			.slice(match.index)
			.split(/[\s<>"']/, 1)[0]
			.replace(GLUED_RE, '');
		const link = parseSpotifyLink(token) ?? parseShortLink(token);
		if (link) return link;
	}
	return null;
}

/** The Spotify link a share holds: `url` first, then `text`, then `title`; null if none does. */
export function sharedLink(params: ShareParams): SharedLink | null {
	for (const field of [params.url, params.text, params.title]) {
		const link = field ? linkInField(field) : null;
		if (link) return link;
	}
	return null;
}
