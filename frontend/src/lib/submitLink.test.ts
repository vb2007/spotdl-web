import { describe, expect, it } from 'vitest';
import { countLinks, linkIn } from './submitLink';

const ID = '4aawyAB9vmqN3uQ7FjRGTy';
const ALBUM = `https://open.spotify.com/album/${ID}`;

describe('v47 submit link', () => {
	it('takes the link out of words around it', () => {
		expect(linkIn(`listen to this: ${ALBUM}`)).toBe(ALBUM);
		expect(linkIn(`🎵${ALBUM}🔥`)).toBe(ALBUM);
	});

	it('drops what the sentence glued on, a Hungarian case ending included', () => {
		expect(linkIn(`${ALBUM}.`)).toBe(ALBUM);
		expect(linkIn(`(${ALBUM})`)).toBe(ALBUM);
		expect(linkIn(`${ALBUM}…`)).toBe(ALBUM);
		expect(linkIn(`Hallgasd meg a ${ALBUM}-t!`)).toBe(ALBUM);
		expect(linkIn(`a ${ALBUM}-ban van`)).toBe(ALBUM);
	});

	it('keeps a query and a locale segment', () => {
		const shared = `https://open.spotify.com/intl-hu/album/${ID}?si=Ab12_x`;
		expect(linkIn(`${shared}.`)).toBe(shared);
	});

	it('keeps a legacy user playlist link whole', () => {
		const legacy = 'https://open.spotify.com/user/john.doe_1/playlist/37i9dQZF1DX0XUsuxWHRQd';
		expect(linkIn(`${legacy}.`)).toBe(legacy);
	});

	it('keeps every part of a spotify: URI', () => {
		expect(linkIn('spotify:album:abc123')).toBe('spotify:album:abc123');
		expect(linkIn('spotify:user:john.doe:playlist:37i9dQZF1DX.')).toBe(
			'spotify:user:john.doe:playlist:37i9dQZF1DX'
		);
	});

	it('drops a case ending from a spotify: URI too', () => {
		expect(linkIn(`Hallgasd meg: spotify:album:${ID}-t!`)).toBe(`spotify:album:${ID}`);
	});

	it('takes any other link out of words without its punctuation, keeping a final "-"', () => {
		expect(linkIn('see https://example.com/x-y-z.')).toBe('https://example.com/x-y-z');
		expect(linkIn('nézd: https://www.youtube.com/playlist?list=PLabc-')).toBe(
			'https://www.youtube.com/playlist?list=PLabc-'
		);
	});

	it('sends a single token as it is: a manual match, a YouTube playlist', () => {
		const pinned = `https://www.youtube.com/watch?v=dQw4w9WgXcQ|https://open.spotify.com/track/${ID}`;
		expect(countLinks(pinned)).toBe(1);
		expect(linkIn(pinned)).toBe(pinned);
		expect(linkIn('https://www.youtube.com/playlist?list=PLabc-')).toBe(
			'https://www.youtube.com/playlist?list=PLabc-'
		);
	});

	it('counts the links, a Markdown link as the two it holds', () => {
		expect(countLinks(ALBUM)).toBe(1);
		expect(countLinks(`${ALBUM} ${ALBUM}`)).toBe(2);
		expect(countLinks(`${ALBUM},${ALBUM}`)).toBe(2);
		expect(countLinks(`[${ALBUM}](${ALBUM})`)).toBe(2);
		expect(countLinks('not a link')).toBe(0);
	});

	it('finds nothing in text without a link', () => {
		expect(linkIn('hello')).toBeUndefined();
	});
});
