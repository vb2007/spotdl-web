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

	it('keeps every part of a spotify: URI', () => {
		expect(linkIn('spotify:album:abc123')).toBe('spotify:album:abc123');
		expect(linkIn('spotify:user:john.doe:playlist:37i9dQZF1DX.')).toBe(
			'spotify:user:john.doe:playlist:37i9dQZF1DX'
		);
	});

	it('prefers a Spotify link over another one before it', () => {
		expect(linkIn(`https://example.com/x then ${ALBUM}`)).toBe(ALBUM);
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
