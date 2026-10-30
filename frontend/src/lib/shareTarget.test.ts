import { describe, expect, it } from 'vitest';
import { parseShortLink, parseSpotifyLink, sharedLink, type ShareParams } from './shareTarget';

const ID = '4uLU6hMCjMI75M1A2tKUQC';
const TRACK = `https://open.spotify.com/track/${ID}`;
// A real short link (it answered a 307 to this playlist on 2026-10-30).
const SHORT = 'https://spotify.link/6tpneu0iVIb';

const full = (type: string, id = ID) => ({
	kind: 'full',
	type,
	id,
	url: `https://open.spotify.com/${type}/${id}`
});
const short = (url = SHORT) => ({ kind: 'short', url });

describe('v65 share target: Spotify share formats', () => {
	// What each share puts where. Android has no URL field in a share, so Chrome hands the
	// app's text over as `text` (and its subject as `title`); a desktop share (Chrome on
	// Windows, the Web Share API) can fill `url`. The rows marked "reported" follow Spotify
	// Community reports and haven't been captured from a real share yet (the PR says so).
	const table: [string, ShareParams, object | null][] = [
		[
			'Android, Copy link form: the bare link with ?si= in text',
			{ text: `${TRACK}?si=a1B2c3D4e5F6g7H8` },
			full('track')
		],
		['Android, short link form in text (reported default)', { text: SHORT }, short()],
		[
			'Android, song and artist as title, the link in text',
			{ title: 'Never Gonna Give You Up · Rick Astley', text: `${TRACK}?si=x` },
			full('track')
		],
		[
			'a sentence before the link in text (reported)',
			{ text: `Check out this song on Spotify! ${TRACK}?si=x` },
			full('track')
		],
		[
			'a sentence before a short link in text (reported)',
			{ text: `Listen to Never Gonna Give You Up by Rick Astley on Spotify ${SHORT}` },
			short()
		],
		['desktop share: url field', { title: 'Spotify', url: `${TRACK}?si=x` }, full('track')],
		[
			'a Hungarian page link (intl-hu) for an album',
			{ text: `https://open.spotify.com/intl-hu/album/${ID}?si=x` },
			full('album')
		],
		[
			'a playlist',
			{ text: `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=1` },
			full('playlist', '37i9dQZF1DXcBWIGoYBM5M')
		],
		[
			'an artist',
			{ text: `https://open.spotify.com/artist/0gxyHStUsqpMadRV0Di1Qt` },
			full('artist', '0gxyHStUsqpMadRV0Di1Qt')
		],
		[
			'the link only in title',
			{ title: `${TRACK}?si=x`, text: 'shared from Spotify' },
			full('track')
		],
		[
			'url beats text',
			{ url: `https://open.spotify.com/album/${ID}`, text: `${TRACK}` },
			full('album')
		],
		[
			'text beats title',
			{ title: `https://open.spotify.com/album/${ID}`, text: TRACK },
			full('track')
		],
		['a link glued into a sentence', { text: `Hallgasd meg (${TRACK}?si=x)!` }, full('track')],
		['a Hungarian case ending glued on', { text: `Hallgasd meg a ${TRACK}-t!` }, full('track')],
		[
			'a non-Spotify link first, then Spotify',
			{ text: `https://example.com/x ${TRACK}` },
			full('track')
		],
		['no link at all', { title: 'Never Gonna Give You Up', text: 'Rick Astley' }, null],
		['nothing shared', {}, null],
		['a podcast episode', { text: `https://open.spotify.com/episode/${ID}` }, null],
		['a spotify: URI', { text: `spotify:track:${ID}` }, null],
		['a look-alike host', { text: `https://open.spotify.com.evil.example/track/${ID}` }, null],
		[
			"a Spotify link inside another link's query",
			{ text: `https://evil.example/?u=https://open.spotify.com/track/${ID}` },
			null
		],
		['a Spotify link with a port', { text: `https://open.spotify.com:8443/track/${ID}` }, null],
		[
			'a Spotify link with the default port',
			{ text: `https://open.spotify.com:443/track/${ID}` },
			null
		],
		['a Spotify link with a user', { text: `https://u:p@open.spotify.com/track/${ID}` }, null],
		['a short id', { text: 'https://open.spotify.com/track/short' }, null],
		['a short link over http', { text: 'http://spotify.link/6tpneu0iVIb' }, null],
		['a short link look-alike', { text: 'https://spotify.link.evil.example/6tpneu0iVIb' }, null]
	];

	it.each(table)('%s', (_name, params, expected) => {
		expect(sharedLink(params)).toEqual(expected);
	});
});

describe('v65 share target: the server allowlist rules, mirrored', () => {
	it('drops the query, the fragment and the locale segment', () => {
		expect(parseSpotifyLink(`https://OPEN.spotify.com/intl-pt/track/${ID}/?si=x#t=1`)).toEqual(
			full('track')
		);
		expect(parseSpotifyLink(`http://open.spotify.com/intl-zh-hant/playlist/${ID}`)).toEqual(
			full('playlist')
		);
	});

	it('refuses what the server refuses', () => {
		for (const text of [
			`https://open.spotify.com/user/someone/playlist/${ID}`,
			`https://open.spotify.com/intl-hu/intl-de/track/${ID}`,
			`https://open.spotify.com/track/${ID}/extra`,
			`https://open.spotify.com/Track/${ID}`,
			`ftp://open.spotify.com/track/${ID}`,
			'not a link'
		]) {
			expect(parseSpotifyLink(text), text).toBeNull();
		}
	});

	it('keeps a short link to its code', () => {
		expect(parseShortLink('https://spotify.link/6tpneu0iVIb?x=1')).toEqual(short());
		expect(parseShortLink('https://spotify.app.link/6tpneu0iVIb')).toEqual(
			short('https://spotify.app.link/6tpneu0iVIb')
		);
		expect(parseShortLink('https://spotify.link/a/b')).toBeNull();
	});
});
