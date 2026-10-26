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
		server_error: 'errorServer',
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
	// Items with a request in flight (by canonical URL): a row re-rendered meanwhile shows
	// "sending", can't send twice, and gets the answer.
	const inflight = new Set();
	let menu = null; // { el, button }
	// Each menu entry's action (kept here, not on the element, which the page can see).
	const choosers = new WeakMap();
	// Only the user's own input acts: a page script's synthetic click or key on an icon or
	// a menu entry (isTrusted false) must never queue anything in their account. Tests,
	// which can only dispatch synthetic events, opt in through start().
	let acceptSynthetic = false;
	// Tests only: also accept a click with no press before it (jsdom's `.click()`).
	let skipPressRule = false;
	const trusted = (event) => event.isTrusted || acceptSynthetic;
	// The last trusted press anywhere on the page (pointerdown, or mousedown: a screen
	// reader's "press" action sends mousedown/mouseup/click with no pointer event), and whose
	// menu was open when it began. A click on an icon or a menu entry counts only when that
	// press landed inside it: every real click starts with its own press, so a page can't
	// forward one from elsewhere (an invisible <label for> over the page), and nothing about
	// it goes stale or depends on how long the press was held.
	let lastPress = null; // { target, menuOwner }
	// The icon the last trusted Enter/Space keydown landed on. A keyboard click (detail 0)
	// counts only on that icon: a page script moving focus onto an icon while the user types
	// in its own field would otherwise turn the user's Enter into a submission.
	let lastKeyIcon = null;

	function onAnyPress(event) {
		if (!trusted(event) || event.button !== 0) return;
		// The icon or entry pressed, not the glyph node under the pointer: a state change
		// replaces the glyph mid-press, and a detached node is inside nothing.
		const raw = event.target;
		const target = (raw instanceof win.Element && raw.closest(`[${ICON_ATTR}], .spotdl-ext-menu-item`)) || raw;
		const menuOwner = menu ? menu.button : null;
		// pointerdown then mousedown of one press: the same press, unless the menu changed.
		if (event.type === 'mousedown' && lastPress && lastPress.target === target && lastPress.menuOwner === menuOwner) return;
		lastPress = { target, menuOwner };
	}

	// Takes the last press if it landed inside `el`, and clears it either way.
	function takePress(el) {
		const press = lastPress && el.contains(lastPress.target) ? lastPress : null;
		lastPress = null;
		return press;
	}
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
		applyItem(button, item);
		setState(button, shownState(item.url));
		// Spotify's rows and cards act on clicks and double-clicks that bubble up to them
		// (select, play, navigate): none of ours may reach them.
		for (const type of ['mouseup', 'dblclick']) {
			button.addEventListener(type, (event) => event.stopPropagation());
		}
		for (const type of ['pointerdown', 'mousedown']) {
			button.addEventListener(type, (event) => event.stopPropagation());
		}
		// A click counts from the keyboard (`detail` 0, on the focused button) or after a
		// press inside this button (onAnyPress).
		button.addEventListener('click', (event) => {
			event.preventDefault();
			event.stopPropagation();
			if (!trusted(event)) return;
			const fromKeyboard = event.detail === 0 && doc.activeElement === button && lastKeyIcon === button;
			if (event.detail === 0) lastKeyIcon = null;
			const press = fromKeyboard ? null : takePress(button);
			if (!fromKeyboard && !press && !skipPressRule) return;
			// The opener of an open menu (open when the press began, even if the press's
			// focus move has closed it since): the click dismisses it, it never queues.
			if ((press && press.menuOwner === button) || (menu && menu.button === button)) closeMenu(true);
			else submit(button, null);
		});
		// Only the keys the icon acts on stop here (Spotify's own Enter would play the row);
		// arrows, Home/End and Tab still reach Spotify's tracklist grid navigation.
		for (const type of ['keyup', 'keypress']) {
			button.addEventListener(type, (event) => {
				if (event.key === 'Enter' || event.key === ' ' || isMenuKey(event)) event.stopPropagation();
			});
		}
		button.addEventListener('contextmenu', (event) => {
			event.preventDefault();
			event.stopPropagation();
			if (trusted(event)) openMenu(button);
		});
		button.addEventListener('keydown', (event) => {
			const ours = event.key === 'Enter' || event.key === ' ' || isMenuKey(event) || (event.key === 'Escape' && menu && menu.button === button);
			if (!ours) return;
			event.stopPropagation();
			if (!trusted(event)) {
				event.preventDefault();
				return;
			}
			if (event.key === 'Enter' || event.key === ' ') lastKeyIcon = button;
			if (event.key === 'Escape') {
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
				setState(own, shownState(item.url));
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
		// A menu whose icon's row went away (virtualized out, or a navigation) closes with it.
		if (menu && !menu.button.isConnected) closeMenu(false);
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

	function shownState(url) {
		return inflight.has(url) ? 'sending' : (itemStates.get(url) ?? 'idle');
	}

	// Every icon showing `url` now (one item can have two: search's top result and its row,
	// a track twice in a playlist).
	function iconsFor(url) {
		return Array.from(doc.querySelectorAll(`[${ICON_ATTR}]`)).filter(
			(candidate) => candidate.dataset.spotdlUrl === url && hostItem(candidate),
		);
	}

	// The icon an answer belongs to: the one clicked while it still shows the item, else the
	// one a re-render put in its place.
	function iconFor(url, clicked) {
		if (clicked && clicked.isConnected && clicked.dataset.spotdlUrl === url && hostItem(clicked)) return clicked;
		return iconsFor(url)[0] ?? null;
	}

	function setStates(url, state) {
		for (const icon of iconsFor(url)) setState(icon, state);
	}

	async function submit(clicked, cascade, override) {
		const item = hostItem(clicked);
		if (!item) return;
		if (inflight.has(item.url)) {
			// One request per item at a time: say so, rather than drop the choice unseen.
			showToast(clicked, t('toastStillSending'), 'error');
			return;
		}
		const url = override ? override.url : item.url;
		inflight.add(item.url);
		setStates(item.url, 'sending');
		setState(clicked, 'sending');
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
		inflight.delete(item.url);
		// The row may have been recycled, or re-rendered with a new icon, while it ran.
		const button = iconFor(item.url, clicked);
		const stillOurs = button !== null;

		if (answer.outcome === 'ambiguous') {
			const candidates = artistChoices(answer.candidates);
			setStates(item.url, shownState(item.url));
			// The menu opens only while focus is still on the icon (where choosing put it):
			// anywhere else, even the page's <body> after a click on empty space, the user has
			// moved on, and the next Enter or Space would queue an artist nobody chose.
			if (stillOurs && candidates.length > 0 && doc.activeElement === button) openMenu(button, candidates);
			else if (candidates.length > 0) showToast(button, t('toastChooseArtistAgain'), 'error');
			else showToast(button, t('errorFailed'), 'error');
			return;
		}
		const success = answer.outcome in SUCCESS_KEYS;
		const direct = !cascade && !override;
		if (success && direct) itemStates.set(item.url, answer.outcome);
		// Every icon of the item shows the answer; a transient one (an error, a cascade's) goes
		// back to the item's own state after a moment.
		setStates(item.url, success && direct ? answer.outcome : shownState(item.url));
		if (stillOurs) {
			setState(button, success ? answer.outcome : 'error');
			if (!success || !direct) {
				win.setTimeout(() => {
					for (const now of iconsFor(item.url)) {
						if (now.dataset.state !== 'sending') setState(now, shownState(item.url));
					}
				}, TRANSIENT_MS);
			}
		}
		showToast(button, message(answer, cascade, override), success ? 'ok' : 'error');
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
		return t('errorFailed');
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
		if (menu && menu.button === button && !candidates) {
			// Opened again (a Menu key's own contextmenu event, a second right-click): focus
			// goes back into the menu, never left on the icon beside an open menu.
			if (!menu.el.contains(doc.activeElement)) items()[0]?.focus();
			return;
		}
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
			// As on the icon: a click counts only after a press inside this entry (the keyboard
			// path, onMenuKey, calls the chooser directly).
			entry.addEventListener('click', (event) => {
				event.preventDefault();
				event.stopPropagation();
				const press = takePress(entry);
				if (trusted(event) && (press || skipPressRule)) choosers.get(entry)?.();
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
			const to = event.relatedTarget;
			// Focus going to the opener is the opener's click, which dismisses the menu itself.
			if (menu && menu.el === el && to !== null && !el.contains(to) && !menu.button.contains(to)) {
				closeMenu(false);
			}
		});
		doc.body.append(el);
		menu = { el, button };
		// The opener stays visible and pressed while its menu is open (the menu lives in
		// <body>, so the row's own :hover/:focus-within no longer shows it).
		button.setAttribute('aria-haspopup', 'menu');
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
		// A press recorded while it was open no longer means "dismiss".
		if (lastPress && lastPress.menuOwner === button) lastPress = { ...lastPress, menuOwner: null };
		// Only while open: the button's own activation queues, it doesn't open a menu.
		button.removeAttribute('aria-haspopup');
		button.removeAttribute('aria-expanded');
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
		// A press on the opener (its glyph included) is left to the opener's click.
		if (menu && !menu.el.contains(event.target) && !menu.button.contains(event.target)) closeMenu(false);
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
		skipPressRule = acceptSynthetic && options.requirePress !== true;
		win = window;
		doc = window.document;
		api = browserApi;
		selectors = selectorSet;
		scan();
		observer = new win.MutationObserver(scheduleScan);
		observer.observe(doc.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['href'] });
		win.addEventListener('popstate', scheduleScan);
		// Before onOutsidePointer: a press records which menu was open as it began.
		win.addEventListener('pointerdown', onAnyPress, true);
		win.addEventListener('mousedown', onAnyPress, true);
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
