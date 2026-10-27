// The content script's entry point (loaded last, after selectors.js and inject.js).
'use strict';

globalThis.spotdlInject.start(
	window,
	{
		sendMessage: (message) => browser.runtime.sendMessage(message),
		getMessage: (key, substitutions) => browser.i18n.getMessage(key, substitutions),
	},
	globalThis.spotdlSelectors,
);
