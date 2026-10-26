// The in-page half of the extension: a download icon on every item selectors.js recognizes,
// its cascade menu, and a small toast reporting what the app answered.
//
// Spotify is a React SPA that re-renders constantly (and recycles tracklist rows as you
// scroll), so a debounced MutationObserver re-runs `scan()`, which is idempotent: a host
// element gets at most one icon, and an icon whose host now shows another item is retargeted,
// not duplicated. A selector miss, or any surprise in the markup, means no icon, never an error
// on the page.
//
// The content script never talks to the app itself (the page's CORS would apply): every
// submission is a message to the background script, which owns all network I/O.
// A classic script, sharing the content script's global with selectors.js.
'use strict';

globalThis.spotdlInject = (() => {
	const HOST_ATTR = 'data-spotdl-host';
	const ICON_ATTR = 'data-spotdl-icon';
	const SCAN_DELAY_MS = 120;
	const TOAST_MS = 4500;
	// How long a cascade's or an error's state stays on the icon before it goes back to idle.
	const TRANSIENT_MS = 3000;
	const SVG_NS = 'http://www.w3.org/2000/svg';

	// The icon's glyph: an arrow landing on a three-bar spectrum (the app's scope). The
	// states swap in their own glyphs.
	const GLYPHS = {
		idle: ['M8 1.25v6.69', 'M5.25 5.5 8 8.25l2.75-2.75', 'M3 14.75v-2', 'M8 14.75v-3.5', 'M13 14.75v-2'],
		sending: ['M8 2.25a5.75 5.75 0 1 1-5.75 5.75'],
		done: ['M2.75 8.5 6.25 12l7-7.5'],
		// A circled "!": a recognisable shape at 16px, not a bare speck.
		error: ['M8 1.75a6.25 6.25 0 1 1 0 12.5a6.25 6.25 0 0 1 0-12.5', 'M8 4.75v4', 'M8 11.1v.15'],
	};
	const STATE_GLYPH = {
		idle: 'idle',
		sending: 'sending',
		queued: 'done',
		already_queued: 'done',
		in_library: 'done',
		error: 'error',
	};

	// Toast text per outcome (and per cascade, for a success). Keys are in _locales.
	const SUCCESS_KEYS = { queued: 'toastQueued', already_queued: 'toastAlreadyQueued', in_library: 'toastInLibrary' };
	const CASCADE_SUCCESS_KEYS = { album: 'toastQueuedAlbum', artist: 'toastQueuedArtist' };
	const ERROR_KEYS = {
		login_required: 'errorLoginRequired',
		key_invalid: 'errorKeyInvalid',
		permission_missing: 'toastPermissionMissing',
		unreachable: 'toastUnreachable',
		rate_limited: 'errorRateLimited',
		url_not_spotify: 'errorUrlNotSpotify',
		cascade_not_found: 'errorCascadeNotFound',
		cascade_unavailable: 'errorCascadeUnavailable',
		cascade_invalid: 'errorCascadeInvalid',
		queue_unavailable: 'errorQueueUnavailable',
		not_an_app: 'toastNotAnApp',
	};

	let doc = null;
	let win = null;
	let api = null; // { sendMessage, getMessage }
	let selectors = null;
	let observer = null;
	let scanTimer = null;
	// Per host element: its icon and the item it was built for.
	const hosts = new WeakMap();
	// Items queued from this tab (by canonical URL), so a re-rendered row keeps its tick.
	const itemStates = new Map();
	let menu = null; // { el, button }
	// Each menu entry's action (kept here, not on the element, which the page can see).
	const choosers = new WeakMap();
	// Only the user's own input acts: a page script's synthetic click or key on an icon or
	// a menu entry (isTrusted false) must never queue anything in their account. Tests,
	// which can only dispatch synthetic events, opt in through start().
	let acceptSynthetic = false;
	const trusted = (event) => event.isTrusted || acceptSynthetic;
	let toast = null; // { el, timer }

	const t = (key, subs) => {
		try {
			return api.getMessage(key, subs) || key;
		} catch {
			return key;
		}
	};

	function svg(paths) {
		const el = doc.createElementNS(SVG_NS, 'svg');
		el.setAttribute('viewBox', '0 0 16 16');
		el.setAttribute('aria-hidden', 'true');
		el.setAttribute('focusable', 'false');
		for (const d of paths) {
			const path = doc.createElementNS(SVG_NS, 'path');
			path.setAttribute('d', d);
			el.append(path);
		}
		return el;
	}

	// ---- icons ------------------------------------------------------------------------------

	function label(item) {
		const type = item.type;
		const key = `icon${type[0].toUpperCase()}${type.slice(1)}`;
		return item.title ? t(`${key}Named`, [item.title]) : t(key);
	}

	function applyItem(button, item) {
		button.dataset.spotdlUrl = item.url;
		button.dataset.spotdlType = item.type;
		const text = label(item);
		button.setAttribute('aria-label', text);
		button.title = `${text}\n${t('iconHint')}`;
		button.setAttribute('aria-description', t('iconHint'));
	}

	function setState(button, state) {
		button.dataset.state = state;
		button.replaceChildren(svg(GLYPHS[STATE_GLYPH[state] ?? 'idle']));
		button.setAttribute('aria-busy', state === 'sending' ? 'true' : 'false');
	}

	function createIcon(kind, item) {
		const button = doc.createElement('button');
		button.type = 'button';
		button.className = `spotdl-ext-btn spotdl-ext-btn--${kind}`;
		button.setAttribute(ICON_ATTR, kind);
		button.setAttribute('aria-haspopup', 'menu');
		button.setAttribute('aria-expanded', 'false');
		applyItem(button, item);
		setState(button, itemStates.get(item.url) ?? 'idle');
		// Spotify's rows and cards act on clicks, double-clicks and keys that bubble up to them
		// (select, play, navigate): none of ours may reach them.
		for (const type of ['pointerdown', 'mousedown', 'mouseup', 'dblclick', 'keyup', 'keypress']) {
			button.addEventListener(type, (event) => event.stopPropagation());
		}
		button.addEventListener('click', (event) => {
			event.preventDefault();
			event.stopPropagation();
			if (trusted(event)) submit(button, null);
		});
		button.addEventListener('contextmenu', (event) => {
			event.preventDefault();
			event.stopPropagation();
			if (trusted(event)) openMenu(button);
		});
		button.addEventListener('keydown', (event) => {
			event.stopPropagation();
			if (!trusted(event)) return;
			if (event.key === 'Escape' && menu && menu.button === button) {
				event.preventDefault();
				closeMenu(true);
				return;
			}
			if (isMenuKey(event)) {
				event.preventDefault();
				openMenu(button);
			}
		});
		return button;
	}

	// The Menu key, or Shift+F10: never with Ctrl/Alt/Meta, and never under AltGr (which
	// Windows reports as Ctrl+Alt).
	function isMenuKey(event) {
		if (event.ctrlKey || event.altKey || event.metaKey) return false;
		if (typeof event.getModifierState === 'function' && event.getModifierState('AltGraph')) return false;
		if (event.key === 'ContextMenu') return !event.shiftKey;
		return event.key === 'F10' && event.shiftKey;
	}

	function iconOf(host) {
		const entry = hosts.get(host);
		if (entry && entry.button.isConnected && entry.button.closest(`[${HOST_ATTR}]`) === host) return entry.button;
		return null;
	}

	function removeIcon(host) {
		const button = iconOf(host);
		if (button) {
			if (menu && menu.button === button) closeMenu(false);
			button.remove();
		}
		hosts.delete(host);
		host.removeAttribute(HOST_ATTR);
	}

	function ensureIcon(host, target, item) {
		// Strays: icons React copied along with a recycled subtree, or left behind when it
		// replaced the node we held.
		const own = iconOf(host);
		for (const stray of host.querySelectorAll(`[${ICON_ATTR}]`)) {
			if (stray !== own && stray.closest(`[${HOST_ATTR}]`) === host) stray.remove();
		}
		const placement = target.mount(host);
		if (!placement || !host.contains(placement.parent)) {
			if (own) removeIcon(host);
			return;
		}
		host.setAttribute(HOST_ATTR, target.kind);
		if (own) {
			if (own.dataset.spotdlUrl !== item.url) {
				// A recycled row now showing another track.
				if (menu && menu.button === own) closeMenu(false);
				applyItem(own, item);
				setState(own, itemStates.get(item.url) ?? 'idle');
			} else if (hosts.get(host)?.item.title !== item.title) {
				// Same item, new title text (a header whose page re-rendered after the address
				// changed): the label follows.
				applyItem(own, item);
			}
			hosts.set(host, { button: own, item });
			return;
		}
		const button = createIcon(target.kind, item);
		if (target.kind === 'card' && win.getComputedStyle(host).position === 'static') {
			host.style.position = 'relative';
		}
		placement.parent.insertBefore(button, placement.before ?? null);
		hosts.set(host, { button, item });
	}

	/** One idempotent pass over the page. Never throws. */
	function scan() {
		if (!doc || !selectors) return;
		for (const target of selectors.targets) {
			let found;
			try {
				found = Array.from(target.find(doc));
			} catch {
				continue;
			}
			for (const host of found) {
				try {
					const item = target.identify(host, win.location);
					if (item) ensureIcon(host, target, item);
					else if (hosts.has(host) || host.hasAttribute(HOST_ATTR)) removeIcon(host);
				} catch {
					// A shape we didn't expect: this element simply gets no icon.
				}
			}
		}
	}

	function scheduleScan() {
		if (scanTimer !== null) return;
		scanTimer = win.setTimeout(() => {
			scanTimer = null;
			scan();
		}, SCAN_DELAY_MS);
	}

	// ---- submitting ---------------------------------------------------------------------------

	function hostItem(button) {
		const host = button.closest(`[${HOST_ATTR}]`);
		const entry = host ? hosts.get(host) : null;
		return entry && entry.button === button ? entry.item : null;
	}

	async function submit(button, cascade, override) {
		if (button.dataset.state === 'sending') return;
		const item = hostItem(button);
		if (!item) return;
		const url = override ? override.url : item.url;
		setState(button, 'sending');
		let answer;
		try {
			answer = await api.sendMessage({
				type: 'submit',
				url,
				cascade,
				// For the popup's history only; never sent to the app.
				title: override ? override.name : item.title,
				itemType: override ? 'artist' : item.type,
			});
		} catch {
			answer = { outcome: 'error', code: 'extension_error' };
		}
		answer = answer ?? { outcome: 'error', code: 'extension_error' };
		// The row may have been recycled for another item while the request ran.
		const stillOurs = button.isConnected && button.dataset.spotdlUrl === item.url;

		if (answer.outcome === 'ambiguous') {
			const candidates = artistChoices(answer.candidates);
			setState(button, 'idle');
			// The row was recycled meanwhile, or no candidate is usable: nothing to ask.
			if (stillOurs && candidates.length > 0) openMenu(button, candidates);
			else if (stillOurs) showToast(button, t('errorGeneric', ['cascade_ambiguous']), 'error');
			return;
		}
		const success = answer.outcome in SUCCESS_KEYS;
		const direct = !cascade && !override;
		if (success && direct) itemStates.set(item.url, answer.outcome);
		if (stillOurs) {
			setState(button, success ? answer.outcome : 'error');
			if (!success || !direct) {
				win.setTimeout(() => {
					if (button.dataset.spotdlUrl === item.url && button.dataset.state !== 'sending') {
						setState(button, itemStates.get(item.url) ?? 'idle');
					}
				}, TRANSIENT_MS);
			}
		}
		showToast(stillOurs ? button : null, message(answer, cascade, override), success ? 'ok' : 'error');
	}

	function message(answer, cascade, override) {
		if (answer.outcome in SUCCESS_KEYS) {
			if (answer.outcome === 'queued' && override) return t('toastQueuedNamed', [override.name]);
			if (answer.outcome === 'queued' && cascade) return t(CASCADE_SUCCESS_KEYS[cascade]);
			return t(SUCCESS_KEYS[answer.outcome]);
		}
		// No app address in the page's DOM: Spotify's scripts can read the toast.
		const key = ERROR_KEYS[answer.code];
		if (answer.code === 'rate_limited') return t('errorRateLimited', [String(answer.retryAfter ?? 60)]);
		if (key) return t(key);
		return t('errorGeneric', [answer.code ?? String(answer.status ?? '?')]);
	}

	// ---- the cascade menu --------------------------------------------------------------------

	function menuChoices(item) {
		if (item.type === 'track') {
			return [
				{ text: t('menuThisTrack'), cascade: null },
				{ text: t('menuWholeAlbum'), cascade: 'album' },
				{ text: t('menuWholeArtist'), cascade: 'artist' },
			];
		}
		if (item.type === 'album') {
			return [
				{ text: t('menuThisAlbum'), cascade: null },
				{ text: t('menuWholeArtist'), cascade: 'artist' },
			];
		}
		return [{ text: t('menuDownload'), cascade: null }];
	}

	// The 409's candidates, reduced to real artist links.
	function artistChoices(candidates) {
		return (Array.isArray(candidates) ? candidates : [])
			.filter((c) => c && typeof c.name === 'string' && selectors.parseItem(c.url)?.type === 'artist')
			.map((c) => ({ text: c.name, override: { url: selectors.parseItem(c.url).url, name: c.name } }));
	}

	function openMenu(button, candidates) {
		const item = hostItem(button);
		if (!item) return;
		if (menu && menu.button === button && !candidates) return; // a Menu key's own contextmenu event
		closeMenu(false);

		const el = doc.createElement('div');
		el.className = 'spotdl-ext-menu';
		el.setAttribute('role', 'menu');
		el.setAttribute('aria-label', candidates ? t('menuChooseArtist') : t('menuLabel'));
		const heading = doc.createElement('div');
		heading.className = 'spotdl-ext-menu-heading';
		heading.setAttribute('aria-hidden', 'true');
		heading.append(svg(GLYPHS.idle), doc.createTextNode(candidates ? t('menuChooseArtist') : t('menuLabel')));
		el.append(heading);

		const choices = candidates ?? menuChoices(item);
		for (const choice of choices) {
			const entry = doc.createElement('button');
			entry.type = 'button';
			entry.className = 'spotdl-ext-menu-item';
			entry.setAttribute('role', 'menuitem');
			entry.tabIndex = -1;
			entry.textContent = choice.text;
			choosers.set(entry, () => {
				closeMenu(true);
				submit(button, choice.cascade ?? null, choice.override);
			});
			entry.addEventListener('click', (event) => {
				event.preventDefault();
				event.stopPropagation();
				if (trusted(event)) choosers.get(entry)?.();
			});
			el.append(entry);
		}
		el.addEventListener('keydown', onMenuKey);
		for (const type of ['pointerdown', 'mousedown', 'mouseup', 'click', 'contextmenu', 'keyup', 'keypress']) {
			el.addEventListener(type, (event) => {
				event.stopPropagation();
				if (type === 'contextmenu') event.preventDefault();
			});
		}
		el.addEventListener('focusout', (event) => {
			if (menu && menu.el === el && !el.contains(event.relatedTarget) && event.relatedTarget !== null) {
				closeMenu(false);
			}
		});
		doc.body.append(el);
		menu = { el, button };
		// The opener stays visible and pressed while its menu is open (the menu lives in
		// <body>, so the row's own :hover/:focus-within no longer shows it).
		button.setAttribute('aria-expanded', 'true');
		placeNear(el, button);
		items()[0]?.focus();
	}

	function items() {
		return menu ? Array.from(menu.el.querySelectorAll('[role="menuitem"]')) : [];
	}

	function onMenuKey(event) {
		event.stopPropagation();
		if (!trusted(event)) return undefined;
		const list = items();
		const at = list.indexOf(doc.activeElement);
		const move = (index) => {
			event.preventDefault();
			list[(index + list.length) % list.length]?.focus();
		};
		switch (event.key) {
			case 'ArrowDown':
				return move(at + 1);
			case 'ArrowUp':
				return move(at - 1);
			case 'Home':
				return move(0);
			case 'End':
				return move(list.length - 1);
			case 'Escape':
			case 'Tab':
				event.preventDefault();
				return closeMenu(true);
			case 'Enter':
			case ' ':
				event.preventDefault();
				if (at >= 0) choosers.get(list[at])?.();
				return undefined;
			default:
				return undefined;
		}
	}

	function closeMenu(refocus) {
		if (!menu) return;
		const { el, button } = menu;
		menu = null;
		button.setAttribute('aria-expanded', 'false');
		el.remove();
		if (refocus && button.isConnected) button.focus();
	}

	// Fixed-position, below the icon (above it when there's no room), inside the viewport.
	function placeNear(el, anchor) {
		const rect = anchor.getBoundingClientRect();
		const width = el.offsetWidth || 220;
		const height = el.offsetHeight || 0;
		const margin = 8;
		let left = Math.min(rect.left, win.innerWidth - width - margin);
		left = Math.max(margin, left);
		let top = rect.bottom + 4;
		if (height && top + height > win.innerHeight - margin) top = Math.max(margin, rect.top - height - 4);
		el.style.left = `${Math.round(left)}px`;
		el.style.top = `${Math.round(top)}px`;
	}

	// ---- the toast ----------------------------------------------------------------------------

	function showToast(anchor, text, tone) {
		hideToast();
		const el = doc.createElement('div');
		el.className = `spotdl-ext-toast spotdl-ext-toast--${tone}`;
		el.setAttribute('role', tone === 'error' ? 'alert' : 'status');
		const glyph = svg(GLYPHS[tone === 'ok' ? 'done' : 'error']);
		const span = doc.createElement('span');
		span.textContent = text;
		el.append(glyph, span);
		doc.body.append(el);
		if (anchor && anchor.isConnected) {
			const rect = anchor.getBoundingClientRect();
			const width = el.offsetWidth || 280;
			const left = Math.max(8, Math.min(rect.left + rect.width / 2 - width / 2, win.innerWidth - width - 8));
			const above = rect.top - (el.offsetHeight || 36) - 8;
			el.style.left = `${Math.round(left)}px`;
			el.style.top = `${Math.round(above > 8 ? above : rect.bottom + 8)}px`;
		} else {
			el.classList.add('spotdl-ext-toast--docked');
		}
		const timer = win.setTimeout(hideToast, TOAST_MS);
		toast = { el, timer };
	}

	function hideToast() {
		if (!toast) return;
		win.clearTimeout(toast.timer);
		toast.el.remove();
		toast = null;
	}

	// ---- lifecycle ----------------------------------------------------------------------------

	function onOutsidePointer(event) {
		if (menu && !menu.el.contains(event.target) && event.target !== menu.button) closeMenu(false);
	}

	// A scroll or resize moves the menu with its icon (Spotify scrolls its own views on its
	// own, mid-render); it closes only once the icon is gone or out of sight.
	function onViewportChange(event) {
		if (!menu || (event.target instanceof win.Node && menu.el.contains(event.target))) return;
		const rect = menu.button.getBoundingClientRect();
		const visible = menu.button.isConnected && rect.bottom > 0 && rect.top < win.innerHeight;
		if (visible) placeNear(menu.el, menu.button);
		else closeMenu(false);
	}

	/**
	 * Starts watching `window`'s document. `browserApi` is `{sendMessage, getMessage}`
	 * (runtime.sendMessage and i18n.getMessage in the extension; stubs in tests).
	 * `options.acceptSyntheticEvents` is for the tests only.
	 */
	function start(window, browserApi, selectorSet, options = {}) {
		acceptSynthetic = options.acceptSyntheticEvents === true;
		win = window;
		doc = window.document;
		api = browserApi;
		selectors = selectorSet;
		scan();
		observer = new win.MutationObserver(scheduleScan);
		observer.observe(doc.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['href'] });
		win.addEventListener('popstate', scheduleScan);
		doc.addEventListener('pointerdown', onOutsidePointer, true);
		doc.addEventListener('scroll', onViewportChange, true);
		win.addEventListener('resize', onViewportChange);
		win.addEventListener('blur', () => closeMenu(false));
	}

	function stop() {
		if (observer) observer.disconnect();
		observer = null;
		if (scanTimer !== null) win.clearTimeout(scanTimer);
		scanTimer = null;
		closeMenu(false);
		hideToast();
	}

	return { start, stop, scan, isMenuKey };
})();
