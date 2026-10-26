// The toolbar popup: the connection's state and the last 10 submissions (kept in
// storage.local by the background script, never sent anywhere).
import { readSettings } from '../shared/config.js';
import { connectionText, localize, t } from '../shared/i18n.js';

const $ = (id) => document.getElementById(id);
const TYPE_KEYS = { track: 'typeTrack', album: 'typeAlbum', artist: 'typeArtist', playlist: 'typePlaylist' };
const OUTCOME_KEYS = { queued: 'outcomeQueued', already_queued: 'outcomeAlreadyQueued', in_library: 'outcomeInLibrary' };
const CASCADE_KEYS = { album: 'popupCascadeAlbum', artist: 'popupCascadeArtist' };

const locale = t('@@ui_locale').replace('_', '-');
const relative = new Intl.RelativeTimeFormat(locale, { numeric: 'auto', style: 'short' });

function ago(iso) {
	const seconds = Math.round((Date.parse(iso) - Date.now()) / 1000);
	if (!Number.isFinite(seconds)) return '';
	const steps = [
		[60, 'second'],
		[3600, 'minute', 60],
		[86400, 'hour', 3600],
		[Infinity, 'day', 86400],
	];
	for (const [limit, unit, size = 1] of steps) {
		if (Math.abs(seconds) < limit) return relative.format(Math.round(seconds / size), unit);
	}
	return '';
}

function row(entry, origin) {
	const li = document.createElement('li');
	const link = document.createElement('a');
	link.href = `${origin}/`;
	link.target = '_blank';
	link.rel = 'noopener';
	const title = document.createElement('span');
	title.className = 'title';
	title.textContent = entry.title || entry.url;
	const meta = document.createElement('span');
	meta.className = 'meta mono';
	const parts = [t(TYPE_KEYS[entry.type] ?? 'typeTrack')];
	if (entry.cascade) parts.push(t(CASCADE_KEYS[entry.cascade]));
	for (const part of parts) {
		const span = document.createElement('span');
		span.textContent = part;
		meta.append(span);
	}
	const outcome = document.createElement('span');
	outcome.className = 'outcome';
	const ok = entry.outcome in OUTCOME_KEYS;
	outcome.dataset.tone = ok ? 'ok' : 'error';
	outcome.textContent = ok ? t(OUTCOME_KEYS[entry.outcome]) : `${t('outcomeError')} · ${entry.code ?? '?'}`;
	const when = document.createElement('time');
	when.dateTime = entry.at;
	when.textContent = ago(entry.at);
	meta.append(outcome, when);
	link.append(title, meta);
	li.append(link);
	return li;
}

async function main() {
	localize();
	const { origin } = await readSettings(browser.storage);
	$('open-app').href = `${origin}/`;
	$('settings').addEventListener('click', () => {
		browser.runtime.openOptionsPage();
		window.close();
	});

	const list = await browser.runtime.sendMessage({ type: 'history' }).catch(() => []);
	$('recent').replaceChildren(...list.map((entry) => row(entry, origin)));
	$('empty').hidden = list.length > 0;

	const result = await browser.runtime.sendMessage({ type: 'me' }).catch(() => ({ outcome: 'error', code: 'extension_error' }));
	const status = $('connection');
	status.textContent = connectionText(result);
	status.dataset.tone = result.outcome === 'signed_in' ? 'ok' : 'error';
}

main();
