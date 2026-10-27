// Every assumption about open.spotify.com's DOM lives in this file (master v5: "selectors are
// isolated in one selectors.js"). Spotify re-renders and reshuffles its markup constantly, so
// each target leans on `data-testid` / `data-encore-id` / ARIA attributes, never on its hashed
// class names, and every lookup answers `null` when something isn't there: a selector that
// stops matching costs an icon, never a thrown error.
//
// An item's identity is always a /track/, /album/, /artist/ or /playlist/ link in or near the
// element (or the page's own address, for a page header), never its text. Text is read only
// to label the icon for a screen reader and to title the popup's history.
//
// A classic script (content scripts can't be modules): it publishes `spotdlSelectors` on the
// content script's global, which inject.js reads.
'use strict';

globalThis.spotdlSelectors = (() => {
	const ORIGIN = 'https://open.spotify.com';
	const ITEM_TYPES = ['track', 'album', 'artist', 'playlist'];
	// `/intl-hu/album/<id>` and `/album/<id>` are the same album. Spotify ids are 22 base-62
	// characters.
	const ITEM_PATH = /^\/(?:intl-[a-z]{2}(?:-[a-z]{2,4})?\/)?(track|album|artist|playlist)\/([A-Za-z0-9]{22})\/?$/i;

	/** `{type, id, url}` for a Spotify item link (relative or absolute), else `null`. */
	function parseItem(href) {
		if (typeof href !== 'string' || href === '') return null;
		let url;
		try {
			url = new URL(href, ORIGIN);
		} catch {
			return null;
		}
		if (url.origin !== ORIGIN) return null;
		const match = ITEM_PATH.exec(url.pathname);
		if (!match) return null;
		const type = match[1].toLowerCase();
		const id = match[2];
		return { type, id, url: `${ORIGIN}/${type}/${id}` };
	}

	function linkItem(link) {
		return link ? parseItem(link.getAttribute('href')) : null;
	}

	function text(el) {
		const value = el ? (el.textContent ?? '').replace(/\s+/g, ' ').trim() : '';
		return value === '' ? null : value.slice(0, 200);
	}

	// The first link in `root` that names an item of one of `types`.
	function firstItemLink(root, selector, types) {
		for (const link of root.querySelectorAll(selector)) {
			const item = linkItem(link);
			if (item && types.includes(item.type)) return { link, item };
		}
		return null;
	}

	// Tracklist rows: album and playlist pages, an artist's top tracks, search's songs.
	const trackRow = {
		kind: 'row',
		find: (root) => root.querySelectorAll('[data-testid="tracklist-row"]'),
		identify(row) {
			// The title link: the album and playlist pages mark it, search's rows don't.
			const found =
				firstItemLink(row, 'a[data-testid="internal-track-link"]', ['track']) ??
				firstItemLink(row, 'a[href]', ['track']);
			return found ? { ...found.item, title: text(found.link) } : null;
		},
		// Beside the row's own "More options" button, in the trailing cell.
		mount(row) {
			const more = row.querySelector('[data-testid="more-button"]');
			if (more && more.parentElement) return { parent: more.parentElement, before: more };
			const cells = row.querySelectorAll('[role="gridcell"]');
			const last = cells.length > 0 ? cells[cells.length - 1] : null;
			return last ? { parent: last, before: null } : null;
		},
	};

	// The page header's action bar (play, shuffle, save, more), on album, artist and playlist
	// pages. Its item is the page itself.
	const PAGE_TESTIDS = { album: 'album-page', artist: 'artist-page', playlist: 'playlist-page' };
	const pageHeader = {
		kind: 'header',
		find: (root) => root.querySelectorAll('[data-testid="action-bar-row"]'),
		identify(bar, location) {
			const item = parseItem(location.pathname);
			if (!item || !(item.type in PAGE_TESTIDS)) return null;
			// The bar must belong to that page's own view (not a stale one mid-navigation).
			const page = bar.closest(`[data-testid="${PAGE_TESTIDS[item.type]}"]`);
			if (!page) return null;
			const title = page.querySelector('[data-testid="entityTitle"]');
			return { ...item, title: text(title) };
		},
		mount(bar) {
			const more = Array.from(bar.children).find((child) => child.matches('[data-testid="more-button"]'));
			if (more) return { parent: bar, before: more.nextSibling };
			const actions = bar.querySelector('[data-testid="action-bar-row-actions"]');
			return actions ? { parent: actions, before: null } : null;
		},
	};

	// Cards in shelves and search: albums, artists, playlists (a show, episode, profile or genre
	// card has no item link of those types, so it gets no icon), plus search's top result.
	const card = {
		kind: 'card',
		find: (root) => root.querySelectorAll('[data-encore-id="card"], [data-testid="top-result-card"]'),
		identify(el) {
			if (el.matches('[data-testid="top-result-card"]')) {
				// Search's top result marks no title: its first item link is its own.
				const found = firstItemLink(el, 'a[href]', ITEM_TYPES);
				return found ? { ...found.item, title: text(found.link) } : null;
			}
			// Only the title's own link. A card whose title isn't a link (a music video) has
			// only its subtitle's artist links, and those name someone else.
			const title = el.querySelector('[data-encore-id="cardTitle"]');
			const item = linkItem(title ? title.closest('a[href]') : null);
			return item ? { ...item, title: text(title) } : null;
		},
		// Pinned to the card's corner by the stylesheet; the card is its positioning parent.
		mount: (el) => ({ parent: el, before: null }),
	};

	return { ORIGIN, parseItem, targets: [trackRow, pageHeader, card] };
})();
