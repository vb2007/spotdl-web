// Localizes an extension page: every user-visible string comes from browser.i18n (the
// browser's UI language picks _locales/en or _locales/hu).
//   data-i18n="key"                 → textContent
//   data-i18n-attr="attr:key,…"     → attributes (aria-label, placeholder, title)

export const t = (key, substitutions) => browser.i18n.getMessage(key, substitutions) || key;

export function localize(root = document) {
	document.documentElement.lang = t('@@ui_locale').split(/[-_]/)[0] || 'en';
	for (const el of root.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n);
	for (const el of root.querySelectorAll('[data-i18n-attr]')) {
		for (const pair of el.dataset.i18nAttr.split(',')) {
			const [attr, key] = pair.split(':');
			el.setAttribute(attr.trim(), t(key.trim()));
		}
	}
}

// The same sentences the in-page toast uses (content/inject.js's ERROR_KEYS).
const ERROR_KEYS = {
	login_required: 'errorLoginRequired',
	key_invalid: 'errorKeyInvalid',
	url_not_spotify: 'errorUrlNotSpotify',
	cascade_not_found: 'errorCascadeNotFound',
	cascade_unavailable: 'errorCascadeUnavailable',
	cascade_invalid: 'errorCascadeInvalid',
	queue_unavailable: 'errorQueueUnavailable',
};

/** The sentence an error answer reads as: never its raw code alone. */
export function errorText(result) {
	switch (result.code) {
		case 'permission_missing':
			return t('errorPermissionMissing', [result.origin ?? '']);
		case 'unreachable':
			return t('errorUnreachable', [result.origin ?? '']);
		case 'not_an_app':
			return t('errorNotAnApp', [result.origin ?? '']);
		case 'rate_limited':
			return t('errorRateLimited', [String(result.retryAfter ?? 60)]);
		default:
			return ERROR_KEYS[result.code] ? t(ERROR_KEYS[result.code]) : t('errorGeneric', [result.code ?? '?']);
	}
}

/** The sentence a `me` answer (or its error) reads as, on the options page and the popup. */
export function connectionText(result) {
	if (result.outcome === 'signed_in') {
		const name = result.user.username || result.user.email;
		return t('statusSignedIn', [name, t(result.via === 'key' ? 'viaKey' : 'viaCookie')]);
	}
	switch (result.code) {
		case 'login_required':
			return t('statusLoginRequired');
		case 'key_invalid':
			return t('errorKeyInvalid');
		default:
			return errorText(result);
	}
}
