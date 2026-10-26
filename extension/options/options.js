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

async function test() {
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

// permissions.request must run inside the click's own handler, before any await, or Firefox
// refuses it as not user-initiated: everything it needs is computed synchronously first.
function saveOrigin(origin) {
	const previous = $('app-origin').dataset.saved;
	const asked =
		origin === DEFAULT_ORIGIN ? Promise.resolve(true) : browser.permissions.request({ origins: [originPattern(origin)] });
	return asked.then(async (granted) => {
		if (!granted) {
			setStatus($('app-status'), t('optionsAppDenied', [origin]), 'error');
			return;
		}
		await browser.storage.local.set({ [KEYS.origin]: origin });
		// The old non-default origin's access goes with it (the default's is declared).
		if (previous && previous !== origin && previous !== DEFAULT_ORIGIN) {
			const stillNeeded = originPattern(previous) === originPattern(origin);
			if (!stillNeeded) await browser.permissions.remove({ origins: [originPattern(previous)] }).catch(() => {});
		}
		$('app-origin').dataset.saved = origin;
		await showSettings();
		const result = await test();
		setStatus($('app-status'), t('optionsAppSaved', [connectionText(result)]), result.outcome === 'signed_in' ? 'ok' : 'error');
	});
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
	await browser.storage.local.set({ [KEYS.apiKey]: value });
	$('api-key').value = '';
	await showSettings();
	setStatus($('key-status'), t('optionsKeySaved', [value.slice(-4)]), 'ok');
	await test();
});

$('key-clear').addEventListener('click', async () => {
	await browser.storage.local.remove(KEYS.apiKey);
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
