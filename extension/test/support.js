// Loads a captured open.spotify.com fixture into jsdom and runs the real content scripts in it.
import { readFileSync } from 'node:fs';
import { JSDOM, VirtualConsole } from 'jsdom';

const root = new URL('..', import.meta.url);
const read = (path) => readFileSync(new URL(path, root), 'utf8');

export const en = JSON.parse(read('_locales/en/messages.json'));

/** browser.i18n.getMessage over _locales/en, placeholders included. */
export function getMessage(key, substitutions = []) {
	const entry = en[key];
	if (!entry) return '';
	const subs = Array.isArray(substitutions) ? substitutions : [substitutions];
	return entry.message.replace(/\$([A-Z_]+)\$/g, (_, name) => {
		const content = entry.placeholders?.[name.toLowerCase()]?.content ?? '';
		return content.replace(/\$(\d)/g, (__, n) => subs[Number(n) - 1] ?? '');
	});
}

/**
 * A fixture page with selectors.js and inject.js running in it. `mutate(document)` runs before
 * the scripts start (to break a selector). Collects every console error and uncaught error.
 */
export function loadPage(name, { mutate, sendMessage } = {}) {
	const html = read(`test/fixtures/${name}.html`);
	const url = /<meta name="fixture-url" content="([^"]+)"/.exec(html)[1];
	const errors = [];
	const virtualConsole = new VirtualConsole();
	virtualConsole.on('error', (...args) => errors.push(args.join(' ')));
	virtualConsole.on('jsdomError', (error) => errors.push(String(error.stack ?? error)));
	const dom = new JSDOM(html, { url, runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole });
	const { window } = dom;
	window.addEventListener('error', (event) => errors.push(String(event.error ?? event.message)));
	if (mutate) mutate(window.document);
	window.eval(read('content/selectors.js'));
	window.eval(read('content/inject.js'));
	const messages = [];
	const api = {
		getMessage,
		sendMessage: async (message) => {
			messages.push(message);
			return sendMessage ? sendMessage(message) : { outcome: 'queued', via: 'cookie' };
		},
	};
	window.spotdlInject.start(window, api, window.spotdlSelectors);
	return { window, document: window.document, inject: window.spotdlInject, messages, errors };
}

export const icons = (document, kind) =>
	Array.from(document.querySelectorAll(kind ? `[data-spotdl-icon="${kind}"]` : '[data-spotdl-icon]'));

export const settle = (window, ms = 200) => new Promise((resolve) => window.setTimeout(resolve, ms));
