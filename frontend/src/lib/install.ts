// v65: the "install app" entry on /account. Chromium (Android, desktop) offers an install with
// `beforeinstallprompt`, caught early by app.html's script and kept on `window`; Firefox on
// Android and Safari on iOS never fire it and install from their own menus instead, so for
// them the entry is a one-line hint.

/** Chromium's install offer (not in TypeScript's DOM types). */
export interface BeforeInstallPromptEvent extends Event {
	prompt(): Promise<void>;
	readonly userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

declare global {
	interface Window {
		__spotdlInstallPrompt?: BeforeInstallPromptEvent | null;
	}
}

/** The browser's pending install offer, if it made one. */
export function installPrompt(): BeforeInstallPromptEvent | null {
	return window.__spotdlInstallPrompt ?? null;
}

/** Calls `listener` whenever the offer comes or goes (offered, used, installed). */
export function onInstallPromptChange(listener: () => void): () => void {
	addEventListener('spotdl:installprompt', listener);
	return () => removeEventListener('spotdl:installprompt', listener);
}

/** Shows the browser's install dialog; an offer can be used only once. */
export async function promptInstall(): Promise<'accepted' | 'dismissed' | 'unavailable'> {
	const offer = installPrompt();
	if (!offer) return 'unavailable';
	window.__spotdlInstallPrompt = null;
	await offer.prompt();
	const { outcome } = await offer.userChoice;
	dispatchEvent(new Event('spotdl:installprompt'));
	return outcome;
}

/** Whether this page runs as the installed app (its own window). */
export function runningInstalled(): boolean {
	// i18n-ignore: a media query
	return window.matchMedia('(display-mode: standalone)').matches;
}

/** Which browser-menu hint applies: a browser that installs only from its own menu. */
export function installHint(userAgent: string, maxTouchPoints: number): 'ios' | 'firefox' | null {
	// iPadOS reports a Mac, telling itself apart only by touch.
	if (/iPhone|iPad|iPod/.test(userAgent) || (/Macintosh/.test(userAgent) && maxTouchPoints > 1))
		return 'ios';
	if (/Android/.test(userAgent) && /Firefox\//.test(userAgent)) return 'firefox';
	return null;
}

/** The build the service worker serves (its `version`), or null without one. */
export async function serviceWorkerVersion(timeoutMs = 2000): Promise<string | null> {
	const worker = navigator.serviceWorker?.controller;
	if (!worker) return null;
	return new Promise((resolve) => {
		const channel = new MessageChannel();
		const timer = setTimeout(() => resolve(null), timeoutMs);
		channel.port1.onmessage = (event) => {
			clearTimeout(timer);
			resolve(typeof event.data === 'string' ? event.data : null);
		};
		worker.postMessage({ type: 'version' }, [channel.port2]);
	});
}
