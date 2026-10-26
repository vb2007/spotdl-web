// The content script over captured open.spotify.com pages (test/fixtures, see its README):
// where icons go, what item each one names, and that re-renders never duplicate them.
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { icons, loadPage, settle } from './support.js';

const ITEM_URL = /^https:\/\/open\.spotify\.com\/(track|album|artist|playlist)\/[A-Za-z0-9]{22}$/;

function census(document) {
	const counts = {};
	for (const button of icons(document)) {
		const key = `${button.dataset.spotdlIcon}:${button.dataset.spotdlType}`;
		counts[key] = (counts[key] ?? 0) + 1;
	}
	return counts;
}

// Counted by hand from each fixture: every tracklist row, the page header, and each album,
// artist and playlist card (search's show, episode, genre and profile cards get none, and
// neither do the artist page's 10 music videos).
const EXPECTED = {
	album: { 'header:album': 1, 'row:track': 18, 'card:album': 10 },
	playlist: { 'header:playlist': 1, 'row:track': 25 },
	artist: { 'header:artist': 1, 'row:track': 5, 'card:album': 20, 'card:playlist': 19, 'card:artist': 10 },
	search: { 'row:track': 4, 'card:album': 10, 'card:artist': 11, 'card:playlist': 20 },
	home: { 'card:album': 30, 'card:artist': 10, 'card:playlist': 14 },
};

describe('icon placement', () => {
	for (const [page, expected] of Object.entries(EXPECTED)) {
		it(`${page}: one icon per target`, () => {
			const { document, errors } = loadPage(page);
			assert.deepEqual(census(document), expected);
			assert.deepEqual(errors, []);
		});
	}

	it('every icon names a canonical item link, never a show, episode, profile or genre', () => {
		for (const page of Object.keys(EXPECTED)) {
			const { document } = loadPage(page);
			for (const button of icons(document)) assert.match(button.dataset.spotdlUrl, ITEM_URL, page);
		}
	});

	it('a row icon sits beside the row’s own “More options” button', () => {
		const { document } = loadPage('album');
		for (const row of document.querySelectorAll('[data-testid="tracklist-row"]')) {
			const button = row.querySelector('[data-spotdl-icon]');
			assert.equal(button.nextElementSibling.getAttribute('data-testid'), 'more-button');
		}
	});

	it('the header icon sits in the action bar, after its “More options”', () => {
		const { document } = loadPage('playlist');
		const button = icons(document, 'header')[0];
		assert.equal(button.parentElement.getAttribute('data-testid'), 'action-bar-row');
		assert.equal(button.previousElementSibling.getAttribute('data-testid'), 'more-button');
	});

	it('icons are real, labelled buttons in the tab order', () => {
		const { document } = loadPage('album');
		for (const button of icons(document)) {
			assert.equal(button.tagName, 'BUTTON');
			assert.equal(button.type, 'button');
			assert.notEqual(button.tabIndex, -1);
			assert.ok(button.getAttribute('aria-label').endsWith('in spotdl'));
		}
	});
});

describe('identity', () => {
	it('a row is its title’s /track/ link', () => {
		const { document } = loadPage('album');
		const first = icons(document, 'row')[0];
		assert.equal(first.dataset.spotdlUrl, 'https://open.spotify.com/track/6OmhkSOpvYBokMKQxpIGx2');
		assert.equal(first.getAttribute('aria-label'), 'Queue the track “Global Warming (feat. Sensato)” in spotdl');
	});

	it('a search row (no internal-track-link) still uses its /track/ link', () => {
		const { document } = loadPage('search');
		assert.equal(icons(document, 'row')[0].dataset.spotdlUrl, 'https://open.spotify.com/track/0DiWol3AO6WpXZgp0goxAV');
	});

	it('a header is the page’s own address', () => {
		for (const [page, url] of [
			['album', 'https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy'],
			['playlist', 'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M'],
			['artist', 'https://open.spotify.com/artist/4tZwfgrHOc3mvqYlEYSvVi'],
		]) {
			assert.equal(icons(loadPage(page).document, 'header')[0].dataset.spotdlUrl, url);
		}
	});

	it('a card is its title link, query string dropped, not its subtitle’s artists', () => {
		const { document } = loadPage('home');
		const card = document.querySelector('[data-encore-id="card"] a[href*="highlight="]').closest('[data-encore-id="card"]');
		const button = card.querySelector('[data-spotdl-icon]');
		const href = card.querySelector('[data-encore-id="cardTitle"]').closest('a').getAttribute('href');
		assert.equal(button.dataset.spotdlUrl, `https://open.spotify.com${href.split('?')[0]}`);
		assert.equal(button.dataset.spotdlType, 'album');
	});

	it('a music video card (its title is no link) gets no icon, never its artist’s', () => {
		const { document } = loadPage('artist');
		const videos = Array.from(document.querySelectorAll('[data-testid="video-card-image"]')).map((img) =>
			img.closest('[data-encore-id="card"]'),
		);
		assert.equal(videos.length, 10);
		for (const card of videos) assert.equal(card.querySelector('[data-spotdl-icon]'), null);
	});

	it('parseItem: intl paths and ?si= normalize, other hosts and types are refused', () => {
		const { window } = loadPage('home');
		const { parseItem } = window.spotdlSelectors;
		assert.equal(parseItem('/intl-hu/album/4aawyAB9vmqN3uQ7FjRGTy?si=abc').url, 'https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy');
		assert.equal(parseItem('https://open.spotify.com/track/0DiWol3AO6WpXZgp0goxAV').type, 'track');
		for (const bad of [
			'/show/4rOoJ6Egrf8K2IrywzwOMk',
			'/episode/4rOoJ6Egrf8K2IrywzwOMk',
			'/user/spotify',
			'/genre/0JQ5DAqbMKFEC4WFtoNRpw',
			'https://evil.example/track/0DiWol3AO6WpXZgp0goxAV',
			'/track/short',
			'',
			null,
			'http://[',
		]) {
			assert.equal(parseItem(bad), null, String(bad));
		}
	});
});

describe('idempotence under re-render', () => {
	it('scanning again changes nothing', () => {
		const { document, inject } = loadPage('artist');
		const before = census(document);
		inject.scan();
		inject.scan();
		assert.deepEqual(census(document), before);
	});

	it('a re-rendered tracklist gets its icons back, one per row', async () => {
		const { window, document } = loadPage('album');
		const list = document.querySelector('[data-testid="track-list"]');
		const fresh = list.cloneNode(true);
		for (const stale of fresh.querySelectorAll('[data-spotdl-icon]')) stale.remove();
		list.replaceWith(fresh);
		await settle(window);
		assert.equal(icons(document, 'row').length, 18);
		for (const row of document.querySelectorAll('[data-testid="tracklist-row"]')) {
			assert.equal(row.querySelectorAll('[data-spotdl-icon]').length, 1);
		}
	});

	it('a subtree copied along with our icon (React reusing markup) keeps only one', async () => {
		const { window, document } = loadPage('album');
		const row = document.querySelector('[data-testid="tracklist-row"]');
		const cell = row.querySelector('[data-spotdl-icon]').parentElement;
		cell.replaceWith(cell.cloneNode(true)); // a dead copy of the icon, with no listeners
		await settle(window);
		assert.equal(row.querySelectorAll('[data-spotdl-icon]').length, 1);
	});

	it('a recycled row now showing another track is retargeted, not duplicated', async () => {
		const { window, document } = loadPage('album');
		const row = document.querySelectorAll('[data-testid="tracklist-row"]')[3];
		row.querySelector('a[data-testid="internal-track-link"]').setAttribute('href', '/track/0DiWol3AO6WpXZgp0goxAV');
		await settle(window);
		const buttons = row.querySelectorAll('[data-spotdl-icon]');
		assert.equal(buttons.length, 1);
		assert.equal(buttons[0].dataset.spotdlUrl, 'https://open.spotify.com/track/0DiWol3AO6WpXZgp0goxAV');
	});

	it('a row whose track link goes away loses its icon', async () => {
		const { window, document } = loadPage('album');
		const row = document.querySelector('[data-testid="tracklist-row"]');
		for (const link of row.querySelectorAll('a[href^="/track/"]')) link.removeAttribute('href');
		await settle(window);
		assert.equal(row.querySelectorAll('[data-spotdl-icon]').length, 0);
	});

	it('navigating within the SPA (album → artist) moves the header icon, never doubles it', async () => {
		const { window, document } = loadPage('album');
		const header = icons(document, 'header')[0];
		assert.equal(header.dataset.spotdlType, 'album');
		// The address changes first; the old album view is still on screen: no header icon.
		window.history.pushState({}, '', '/artist/4tZwfgrHOc3mvqYlEYSvVi');
		window.dispatchEvent(new window.PopStateEvent('popstate'));
		await settle(window);
		assert.equal(icons(document, 'header').length, 0);
		// Then Spotify renders the artist view into the same bar.
		document.querySelector('[data-testid="album-page"]').setAttribute('data-testid', 'artist-page');
		await settle(window);
		const now = icons(document, 'header');
		assert.equal(now.length, 1);
		assert.equal(now[0].dataset.spotdlUrl, 'https://open.spotify.com/artist/4tZwfgrHOc3mvqYlEYSvVi');
	});
});

describe('a selector miss degrades to no icon', () => {
	it('tracklist rows without their data-testid: zero row icons, no error', () => {
		const { document, errors } = loadPage('album', {
			mutate: (doc) => doc.querySelectorAll('[data-testid="tracklist-row"]').forEach((r) => r.removeAttribute('data-testid')),
		});
		assert.equal(icons(document, 'row').length, 0);
		assert.equal(icons(document, 'header').length, 1);
		assert.deepEqual(errors, []);
	});

	it('cards without data-encore-id: zero card icons, no error', () => {
		const { document, errors } = loadPage('home', {
			mutate: (doc) => doc.querySelectorAll('[data-encore-id="card"]').forEach((c) => c.removeAttribute('data-encore-id')),
		});
		assert.equal(icons(document).length, 0);
		assert.deepEqual(errors, []);
	});

	it('no action bar: no header icon, no error', () => {
		const { document, errors } = loadPage('playlist', {
			mutate: (doc) => doc.querySelector('[data-testid="action-bar-row"]').removeAttribute('data-testid'),
		});
		assert.equal(icons(document, 'header').length, 0);
		assert.equal(icons(document, 'row').length, 25);
		assert.deepEqual(errors, []);
	});

	it('every data-testid and data-encore-id gone: zero icons, no error', () => {
		const { document, errors } = loadPage('artist', {
			mutate: (doc) => {
				for (const el of doc.querySelectorAll('[data-testid], [data-encore-id]')) {
					el.removeAttribute('data-testid');
					el.removeAttribute('data-encore-id');
				}
			},
		});
		assert.equal(icons(document).length, 0);
		assert.deepEqual(errors, []);
	});

	it('rows without a “More options” button still get an icon, in the last cell', () => {
		const { document, errors } = loadPage('album', {
			mutate: (doc) => doc.querySelectorAll('[data-testid="more-button"]').forEach((b) => b.remove()),
		});
		assert.equal(icons(document, 'row').length, 18);
		assert.deepEqual(errors, []);
	});
});

describe('submitting and the cascade menu', () => {
	const key = (window, target, init) =>
		target.dispatchEvent(new window.KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init }));

	it('a click sends the item’s link, and the answer becomes the icon’s state and a toast', async () => {
		const { window, document, messages } = loadPage('album');
		const button = icons(document, 'row')[0];
		button.click();
		await settle(window, 20);
		assert.deepEqual({ ...messages[0] }, {
			type: 'submit',
			url: 'https://open.spotify.com/track/6OmhkSOpvYBokMKQxpIGx2',
			cascade: null,
			title: 'Global Warming (feat. Sensato)',
			itemType: 'track',
		});
		assert.equal(button.dataset.state, 'queued');
		assert.equal(document.querySelector('.spotdl-ext-toast').textContent, 'Queued in spotdl');
	});

	it('the click never reaches Spotify’s row (no select, no play)', () => {
		const { window, document } = loadPage('album');
		const button = icons(document, 'row')[0];
		const row = button.closest('[data-testid="tracklist-row"]');
		const reached = [];
		for (const type of ['click', 'mousedown', 'dblclick', 'keydown']) row.addEventListener(type, () => reached.push(type));
		button.click();
		button.dispatchEvent(new window.MouseEvent('mousedown', { bubbles: true }));
		button.dispatchEvent(new window.MouseEvent('dblclick', { bubbles: true }));
		key(window, button, { key: 'Enter' });
		assert.deepEqual(reached, []);
	});

	it('Shift+F10 opens the track menu; arrows move, Enter queues the whole album', async () => {
		const { window, document, messages } = loadPage('album');
		const button = icons(document, 'row')[0];
		button.focus();
		key(window, button, { key: 'F10', shiftKey: true });
		const menu = document.querySelector('.spotdl-ext-menu[role="menu"]');
		const items = Array.from(menu.querySelectorAll('[role="menuitem"]')).map((i) => i.textContent);
		assert.deepEqual(items, ['This track', 'Whole album', 'Whole artist']);
		assert.equal(document.activeElement.textContent, 'This track');
		key(window, document.activeElement, { key: 'ArrowDown' });
		assert.equal(document.activeElement.textContent, 'Whole album');
		key(window, document.activeElement, { key: 'Enter' });
		await settle(window, 20);
		assert.equal(document.querySelector('.spotdl-ext-menu'), null);
		assert.equal(document.activeElement, button);
		assert.equal(messages[0].cascade, 'album');
		assert.equal(document.querySelector('.spotdl-ext-toast').textContent, 'The whole album is queued in spotdl');
	});

	it('the Menu key opens it too; Esc closes it and focus returns to the icon', () => {
		const { window, document } = loadPage('album');
		const button = icons(document, 'card')[0];
		button.focus();
		key(window, button, { key: 'ContextMenu' });
		const items = Array.from(document.querySelectorAll('.spotdl-ext-menu [role="menuitem"]')).map((i) => i.textContent);
		assert.deepEqual(items, ['This album', 'Whole artist']);
		key(window, document.activeElement, { key: 'ArrowUp' });
		assert.equal(document.activeElement.textContent, 'Whole artist');
		assert.equal(button.getAttribute('aria-haspopup'), 'menu');
		assert.equal(button.getAttribute('aria-expanded'), 'true');
		key(window, document.activeElement, { key: 'Escape' });
		assert.equal(document.querySelector('.spotdl-ext-menu'), null);
		assert.equal(document.activeElement, button);
		assert.equal(button.getAttribute('aria-expanded'), 'false');
	});

	it('a right-click opens it; artists and playlists offer just “Download”', () => {
		const { window, document } = loadPage('artist');
		const button = icons(document, 'header')[0];
		button.dispatchEvent(new window.MouseEvent('contextmenu', { bubbles: true, cancelable: true, button: 2 }));
		const items = Array.from(document.querySelectorAll('.spotdl-ext-menu [role="menuitem"]')).map((i) => i.textContent);
		assert.deepEqual(items, ['Download']);
	});

	it('no menu under AltGr (Ctrl+Alt) or with other modifiers', () => {
		const { window, document } = loadPage('album');
		const button = icons(document, 'row')[0];
		const { isMenuKey } = window.spotdlInject;
		const ev = (init) => new window.KeyboardEvent('keydown', init);
		assert.equal(isMenuKey(ev({ key: 'F10', shiftKey: true })), true);
		assert.equal(isMenuKey(ev({ key: 'ContextMenu' })), true);
		assert.equal(isMenuKey(ev({ key: 'F10', shiftKey: true, ctrlKey: true, altKey: true })), false);
		assert.equal(isMenuKey(ev({ key: 'ContextMenu', ctrlKey: true, altKey: true })), false);
		assert.equal(isMenuKey(ev({ key: 'F10' })), false);
		assert.equal(isMenuKey(ev({ key: 'F10', shiftKey: true, metaKey: true })), false);
		key(window, button, { key: 'F10', shiftKey: true, ctrlKey: true, altKey: true });
		assert.equal(document.querySelector('.spotdl-ext-menu'), null);
	});

	it('several artists: the app’s candidates become a submenu, and the pick is queued', async () => {
		const candidates = [
			{ name: 'Pitbull', url: 'https://open.spotify.com/artist/0TnOYISbd1XYRBk9myaseg' },
			{ name: 'Sensato', url: 'https://open.spotify.com/artist/7iJrDbKM5fEkGdm5kpjFzS' },
		];
		const { window, document, messages } = loadPage('album', {
			sendMessage: (m) => (m.cascade === 'artist' ? { outcome: 'ambiguous', candidates } : { outcome: 'queued' }),
		});
		const button = icons(document, 'row')[0];
		button.focus();
		key(window, button, { key: 'F10', shiftKey: true });
		key(window, document.activeElement, { key: 'End' });
		assert.equal(document.activeElement.textContent, 'Whole artist');
		key(window, document.activeElement, { key: 'Enter' });
		await settle(window, 20);
		const menu = document.querySelector('.spotdl-ext-menu');
		assert.equal(menu.getAttribute('aria-label'), 'Which artist?');
		assert.deepEqual(
			Array.from(menu.querySelectorAll('[role="menuitem"]')).map((i) => i.textContent),
			['Pitbull', 'Sensato'],
		);
		key(window, document.activeElement, { key: 'ArrowDown' });
		key(window, document.activeElement, { key: 'Enter' });
		await settle(window, 20);
		assert.deepEqual({ ...messages[1] }, {
			type: 'submit',
			url: 'https://open.spotify.com/artist/7iJrDbKM5fEkGdm5kpjFzS',
			cascade: null,
			title: 'Sensato',
			itemType: 'artist',
		});
		assert.equal(document.querySelector('.spotdl-ext-toast').textContent, 'Sensato is queued in spotdl');
	});

	it('a candidate that isn’t an artist link is never offered', async () => {
		const { window, document } = loadPage('album', {
			sendMessage: () => ({
				outcome: 'ambiguous',
				candidates: [
					{ name: 'Fine', url: 'https://open.spotify.com/artist/0TnOYISbd1XYRBk9myaseg' },
					{ name: 'Elsewhere', url: 'https://evil.example/artist/0TnOYISbd1XYRBk9myaseg' },
					{ name: 'A track', url: 'https://open.spotify.com/track/0DiWol3AO6WpXZgp0goxAV' },
				],
			}),
		});
		const button = icons(document, 'row')[0];
		button.dispatchEvent(new window.MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
		document.querySelectorAll('.spotdl-ext-menu [role="menuitem"]')[2].click();
		await settle(window, 20);
		assert.deepEqual(
			Array.from(document.querySelectorAll('.spotdl-ext-menu [role="menuitem"]')).map((i) => i.textContent),
			['Fine'],
		);
	});

	const TOASTS = [
		[{ outcome: 'already_queued' }, 'Already in your queue: it\'s still downloading', 'already_queued'],
		[{ outcome: 'in_library' }, 'Already in the library: nothing to download', 'in_library'],
		[{ outcome: 'error', code: 'rate_limited', retryAfter: 42 }, 'Too many submissions. Try again in 42 s', 'error'],
		[{ outcome: 'error', code: 'unreachable', origin: 'https://spotdl.example' }, 'Can\'t reach spotdl at https://spotdl.example', 'error'],
		[{ outcome: 'error', code: 'login_required' }, 'Log in to spotdl in this browser, or add an API key', 'error'],
		[{ outcome: 'error', code: 'url_not_spotify' }, 'spotdl only takes Spotify track, album, artist and playlist links', 'error'],
		[{ outcome: 'error', code: 'something_new' }, 'Couldn\'t queue it (something_new)', 'error'],
	];
	for (const [answer, text, state] of TOASTS) {
		it(`answer ${answer.code ?? answer.outcome} → “${text}”`, async () => {
			const { window, document } = loadPage('album', { sendMessage: () => answer });
			const button = icons(document, 'header')[0];
			button.click();
			await settle(window, 20);
			assert.equal(document.querySelector('.spotdl-ext-toast').textContent, text);
			assert.equal(button.dataset.state, state);
		});
	}

	it('a queued tick survives its row being re-rendered', async () => {
		const { window, document } = loadPage('album');
		icons(document, 'row')[0].click();
		await settle(window, 20);
		const list = document.querySelector('[data-testid="track-list"]');
		const fresh = list.cloneNode(true);
		for (const stale of fresh.querySelectorAll('[data-spotdl-icon]')) stale.remove();
		list.replaceWith(fresh);
		await settle(window);
		assert.equal(icons(document, 'row')[0].dataset.state, 'queued');
		assert.equal(icons(document, 'row')[1].dataset.state, 'idle');
	});
});
