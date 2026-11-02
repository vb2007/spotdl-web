// v67 (U8): the per-language message loader vite.config.ts's `paraglideLocaleSplit` provides.
declare module 'virtual:locale-messages' {
	import type { Locale } from '$lib/paraglide/runtime';
	/** Downloads `locale`'s messages (once); messages render in it only after this resolves. */
	export function loadLocaleMessages(locale: Locale): Promise<void>;
	/** Whether `locale`'s messages are already here. */
	export function hasLocaleMessages(locale: Locale): boolean;
}
