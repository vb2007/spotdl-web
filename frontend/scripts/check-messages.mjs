// v46: the message files' guard, run by `lint`, `check` and `build`.
//
// 1. `en.json` and `hu.json` hold the same keys. Paraglide falls back to English for a key a
//    locale lacks, so a missing Hungarian string would otherwise ship silently.
// 2. Each key takes the same inputs in both, so a translation can't drop or rename a value.
// 3. The compiled output holds every key. The inlang SDK reports a plugin it couldn't load
//    as a warning and still "successfully" compiles zero messages.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { compile } from '@inlang/paraglide-js';

const root = path.resolve(import.meta.dirname, '..');
const project = JSON.parse(readFileSync(path.join(root, 'project.inlang/settings.json'), 'utf8'));
const patterns = [project['plugin.inlang.messageFormat'].pathPattern].flat();
const outdir = path.join(root, 'src/lib/paraglide');

function load(locale) {
	const merged = {};
	for (const pattern of patterns) {
		const file = path.join(root, pattern.replace('{locale}', locale));
		const json = JSON.parse(readFileSync(file, 'utf8'));
		delete json.$schema;
		for (const [key, value] of Object.entries(json)) {
			if (key in merged) throw new Error(`${locale}: "${key}" is defined twice (${file})`);
			merged[key] = value;
		}
	}
	return merged;
}

function inputs(message) {
	const names = new Set();
	if (typeof message === 'string') {
		for (const match of message.matchAll(/\{(\w+)\}/g)) names.add(match[1]);
		return names;
	}
	for (const variant of [message].flat()) {
		for (const declaration of variant.declarations ?? []) {
			const input = /^input (\w+)$/.exec(declaration);
			if (input) names.add(input[1]);
		}
	}
	return names;
}

const problems = [];
const messages = Object.fromEntries(project.locales.map((locale) => [locale, load(locale)]));
const base = messages[project.baseLocale];
const allKeys = new Set(Object.values(messages).flatMap((m) => Object.keys(m)));

for (const key of allKeys) {
	for (const locale of project.locales) {
		if (!(key in messages[locale])) problems.push(`${locale}.json is missing "${key}"`);
	}
	if (!(key in base)) continue;
	const expected = [...inputs(base[key])].sort().join(', ');
	for (const locale of project.locales) {
		if (!(key in messages[locale])) continue;
		const got = [...inputs(messages[locale][key])].sort().join(', ');
		if (got !== expected)
			problems.push(
				`"${key}": ${locale} takes {${got}}, ${project.baseLocale} takes {${expected}}`
			);
	}
}

if (problems.length === 0) {
	await compile({
		project: path.join(root, 'project.inlang'),
		outdir,
		strategy: ['globalVariable', 'baseLocale'],
		// Must match vite.config.ts's paraglideVitePlugin options.
		outputStructure: 'locale-modules'
	});
	const index = readFileSync(path.join(outdir, 'messages/_index.js'), 'utf8');
	const compiled = index.match(/^export const /gm)?.length ?? 0;
	if (compiled !== allKeys.size)
		problems.push(`compiled ${compiled} messages, the files hold ${allKeys.size}`);
}

if (problems.length) {
	console.error(`i18n: ${problems.length} problem(s) in messages/:`);
	for (const problem of problems) console.error(`  - ${problem}`);
	process.exit(1);
}
console.log(`i18n: ${allKeys.size} keys, identical in ${project.locales.join(' and ')}.`);
