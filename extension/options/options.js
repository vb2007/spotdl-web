// The options page: the app's address, the optional API key, and a connection test. Network
// I/O goes through the background script (`me`); this page only touches storage and
// permissions, which need the user's own click.
import { DEFAULT_ORIGIN, KEYS, looksLikeApiKey, normalizeOrigin, originPattern, readSettings } from '../shared/config.js';
import { connectionText, localize, t } from '../shared/i18n.js';

const SPOTIFY = 'https://open.spotify.com/*';
const $ = (id) => document.getElementById(id);

function setStatus(el, text, tone) {
	el.textContent = text;
	if (tone) el.dataset.tone = tone;
	else delete el.dataset.tone;
}

// Only the newest connection test, and the newest key check, may write their answer: an older
// one landing late (a blackholed address timing out) would overwrite a newer result.
let testRun = 0;
let keyRun = 0;

async function test() {
	const run = ++testRun;
	const status = $('test-status');
	const button = $('test');
	button.disabled = true;
	button.textContent = t('optionsTesting');
	setStatus(status, t('popupChecking'), null);
	let result;
	try {
		result = await browser.runtime.sendMessage({ type: 'me' });
	} catch {
		result = { outcome: 'error', code: 'extension_error' };
	}
	if (run !== testRun) return result;
	setStatus(status, connectionText(result), result.outcome === 'signed_in' ? 'ok' : 'error');
	$('app-grant').hidden = result.code !== 'permission_missing';
	button.disabled = false;
	button.textContent = t('optionsTest');
	return result;
}

async function showSettings() {
	const { origin, apiKey } = await readSettings(browser.storage);
	$('app-origin').value = origin;
	$('account-link').href = `${origin}/account`;
	setStatus(
		$('key-status'),
		apiKey ? t('optionsKeyStored', [apiKey.slice(-4)]) : t('optionsKeyNone'),
		apiKey ? 'ok' : null,
	);
	const granted = await browser.permissions.contains({ origins: [SPOTIFY] });
	setStatus($('spotify-status'), t(granted ? 'optionsSpotifyGranted' : 'optionsSpotifyMissing'), granted ? 'ok' : 'error');
	$('spotify-grant').hidden = granted;
}

// The answers that come from a spotdl app (signed in or not): an address worth saving.
const FROM_AN_APP = new Set(['login_required', 'key_invalid']);

// permissions.request must run inside the click's own handler, before any await, or Firefox
// refuses it as not user-initiated: everything it needs is computed synchronously first.
function saveOrigin(origin) {
	const previous = $('app-origin').dataset.saved;
	const pattern = originPattern(origin);
	// Asked even for the default, whose access is declared but can be revoked in about:addons
	// (an already granted origin answers at once, with no prompt).
	const had = browser.permissions.contains({ origins: [pattern] });
	const asked = browser.permissions.request({ origins: [pattern] });
	return Promise.all([had, asked])
		.then(async ([hadAccess, granted]) => {
			if (!granted) {
				setStatus($('app-status'), t('optionsAppDenied', [origin]), 'error');
				$('app-grant').hidden = true;
				return;
			}
			// Validated before it's saved: only an address that answers like a spotdl app.
			setStatus($('app-status'), t('popupChecking'), null);
			const result = await browser.runtime
				.sendMessage({ type: 'me', origin })
				.catch(() => ({ outcome: 'error', code: 'extension_error' }));
			if (result.outcome !== 'signed_in' && !FROM_AN_APP.has(result.code)) {
				setStatus($('app-status'), t('optionsAppNotSaved', [connectionText(result)]), 'error');
				// The access just granted for an address that isn't kept goes again.
				const keep = [previous, DEFAULT_ORIGIN].some((o) => o && originPattern(o) === pattern);
				if (!hadAccess && !keep) await browser.permissions.remove({ origins: [pattern] }).catch(() => {});
				return;
			}
			await browser.storage.local.set({ [KEYS.origin]: origin });
			// A key belongs to the app it came from: another address drops it.
			const { storedKey, keyOrigin } = await readSettings(browser.storage);
			if (storedKey && keyOrigin !== origin) await browser.storage.local.remove([KEYS.apiKey, KEYS.apiKeyOrigin]);
			// The old non-default origin's access goes with it (the default's is declared).
			if (previous && previous !== origin && previous !== DEFAULT_ORIGIN) {
				const stillNeeded = originPattern(previous) === originPattern(origin);
				if (!stillNeeded) await browser.permissions.remove({ origins: [originPattern(previous)] }).catch(() => {});
			}
			$('app-origin').dataset.saved = origin;
			await showSettings();
			const tested = await test();
			setStatus($('app-status'), t('optionsAppSaved', [connectionText(tested)]), tested.outcome === 'signed_in' ? 'ok' : 'error');
		})
		.catch(() => setStatus($('app-status'), t('optionsAppDenied', [origin]), 'error'));
}

$('app-form').addEventListener('submit', (event) => {
	event.preventDefault();
	const origin = normalizeOrigin($('app-origin').value);
	if (!origin) {
		setStatus($('app-status'), t('optionsAppInvalid'), 'error');
		$('app-origin').focus();
		return;
	}
	void saveOrigin(origin);
});

$('app-reset').addEventListener('click', () => {
	$('app-origin').value = DEFAULT_ORIGIN;
	void saveOrigin(DEFAULT_ORIGIN);
});

// The saved address only (what the failed test was about): a typed, unsaved one is granted
// through saving, which gives the access back if the address doesn't validate.
$('app-grant').addEventListener('click', () => {
	const origin = normalizeOrigin($('app-origin').dataset.saved ?? '') ?? DEFAULT_ORIGIN;
	browser.permissions
		.request({ origins: [originPattern(origin)] })
		.then(() => test())
		.catch(() => {});
});

$('key-form').addEventListener('submit', async (event) => {
	event.preventDefault();
	const value = $('api-key').value.trim();
	if (!looksLikeApiKey(value)) {
		setStatus($('key-status'), t('optionsKeyInvalid'), 'error');
		$('api-key').focus();
		return;
	}
	// Checked on its own (no cookie) before it's kept.
	const run = ++keyRun;
	setStatus($('key-status'), t('popupChecking'), null);
	const checked = await browser.runtime
		.sendMessage({ type: 'checkKey', key: value })
		.catch(() => ({ outcome: 'error', code: 'extension_error' }));
	// "remove key", or another save, came in while this check ran: it no longer decides.
	if (run !== keyRun) return;
	if (checked.outcome !== 'signed_in') {
		setStatus($('key-status'), t('optionsKeyNotSaved', [connectionText(checked)]), 'error');
		return;
	}
	// Tied to the address it was checked against, and only while that is still the saved one
	// (the address may have been changed while the check ran).
	const { origin } = await readSettings(browser.storage);
	if (checked.origin !== origin) {
		setStatus($('key-status'), t('optionsKeyNotSaved', [t('optionsKeyAddressChanged')]), 'error');
		return;
	}
	await browser.storage.local.set({ [KEYS.apiKey]: value, [KEYS.apiKeyOrigin]: origin });
	$('api-key').value = '';
	await showSettings();
	setStatus($('key-status'), t('optionsKeySaved', [value.slice(-4)]), 'ok');
	await test();
});

$('key-clear').addEventListener('click', async () => {
	keyRun++;
	await browser.storage.local.remove([KEYS.apiKey, KEYS.apiKeyOrigin]);
	$('api-key').value = '';
	await showSettings();
	setStatus($('key-status'), t('optionsKeyCleared'), null);
	await test();
});

$('test').addEventListener('click', () => void test());

$('spotify-grant').addEventListener('click', () => {
	browser.permissions
		.request({ origins: [SPOTIFY] })
		.then(() => showSettings())
		.catch(() => {});
});

localize();
$('app-hint').textContent = t('optionsAppHint', [DEFAULT_ORIGIN]);
readSettings(browser.storage).then(({ origin }) => {
	$('app-origin').dataset.saved = origin;
});
showSettings().then(test);
