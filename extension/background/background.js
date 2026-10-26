// The background script: the extension's only network client. The content script, the popup
// and the options page all ask it through runtime messages.
import { history, me, remember, submit } from './api.js';

const deps = {
	fetch: (...args) => fetch(...args),
	storage: browser.storage,
	permissions: browser.permissions,
	version: browser.runtime.getManifest().version,
};

// The answers that need the user to act in the options page: it opens for them.
const NEEDS_OPTIONS = new Set(['login_required', 'key_invalid', 'permission_missing']);

async function onSubmit(message) {
	const cascade = message.cascade === 'album' || message.cascade === 'artist' ? message.cascade : null;
	const result = await submit(deps, { url: message.url, cascade });
	if (result.outcome !== 'ambiguous') {
		await remember(deps.storage, {
			url: typeof message.url === 'string' ? message.url.slice(0, 200) : '',
			type: typeof message.itemType === 'string' ? message.itemType : null,
			title: typeof message.title === 'string' ? message.title.slice(0, 200) : null,
			cascade,
			outcome: result.outcome,
			code: result.code ?? null,
			// What the popup's sentence for an error needs (no secret, nothing from the page).
			origin: result.origin ?? null,
			retryAfter: result.retryAfter ?? null,
			jobId: result.job?.id ?? null,
			via: result.via ?? null,
			at: new Date().toISOString(),
		});
	}
	if (NEEDS_OPTIONS.has(result.code)) {
		browser.runtime.openOptionsPage().catch(() => {});
	}
	return result;
}

browser.runtime.onMessage.addListener((message, sender) => {
	// Only this extension's own scripts and pages.
	if (sender.id !== browser.runtime.id || !message || typeof message.type !== 'string') return undefined;
	switch (message.type) {
		case 'submit':
			return onSubmit(message);
		case 'me':
			return me(deps);
		case 'history':
			return history(deps.storage);
		default:
			return undefined;
	}
});
