import { test } from '@playwright/test';
import * as m from '../../src/lib/paraglide/messages.js';

/** v46: the suite reads accessible names from the same compiled message files the app renders
 * (`npm run check`/`lint`/`build` compile them into src/lib/paraglide), so a spec runs in either
 * language without a second copy of every string. Identities carry no saved language (global
 * setup clears it), so the page speaks its project's browser locale. */
export { m };

export type Lang = 'en' | 'hu';

/** The language a project's browser locale asks for: `hu-HU` is Hungarian, anything else English. */
export function projectLang(): Lang {
	const locale = test.info().project.use.locale ?? 'en-US';
	return locale.toLowerCase().startsWith('hu') ? 'hu' : 'en';
}

/** A message in the project's language (or `lang`), with the inputs it takes. */
export function t<I>(
	message: (inputs: I, options?: { locale?: Lang }) => string,
	inputs?: I,
	lang: Lang = projectLang()
): string {
	return message((inputs ?? {}) as I, { locale: lang });
}
