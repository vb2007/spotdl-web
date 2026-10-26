// _locales key parity, and every string the code or markup asks for exists in both languages.
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const load = (lang) => JSON.parse(readFileSync(join(root, '_locales', lang, 'messages.json'), 'utf8'));
const en = load('en');
const hu = load('hu');

function sources(dir = root, found = []) {
	for (const name of readdirSync(dir)) {
		if (['node_modules', 'test', 'web-ext-artifacts', '_locales'].includes(name)) continue;
		const path = join(dir, name);
		if (statSync(path).isDirectory()) sources(path, found);
		else if (/\.(js|html|json)$/.test(name) && !name.startsWith('package')) found.push(path);
	}
	return found;
}

function usedKeys() {
	const keys = new Set();
	for (const file of sources()) {
		// Comments name example keys; only code and markup count.
		const text = readFileSync(file, 'utf8')
			.replace(/<!--[\s\S]*?-->/g, '')
			.replace(/^\s*(\/\/|\*|\/\*).*$/gm, '');
		for (const m of text.matchAll(/\bt\(\s*'([A-Za-z0-9_]+)'/g)) keys.add(m[1]);
		for (const m of text.matchAll(/getMessage\(\s*'([A-Za-z0-9_]+)'/g)) keys.add(m[1]);
		for (const m of text.matchAll(/data-i18n="([A-Za-z0-9_]+)"/g)) keys.add(m[1]);
		for (const m of text.matchAll(/data-i18n-attr="([^"]+)"/g)) {
			for (const [, key] of m[1].split(',').map((pair) => pair.split(':'))) if (key) keys.add(key.trim());
		}
		for (const m of text.matchAll(/__MSG_([A-Za-z0-9_]+)__/g)) keys.add(m[1]);
		// Keys picked from a table (`ERROR_KEYS`, `TYPE_KEYS`, …): every quoted camelCase value
		// whose shape is a message key.
		for (const m of text.matchAll(/:\s*'((?:toast|error|type|outcome|popup|menu|icon|via|status|options)[A-Z][A-Za-z]*)'/g)) {
			keys.add(m[1]);
		}
	}
	keys.delete('@@ui_locale');
	return keys;
}

describe('_locales', () => {
	it('en and hu hold exactly the same keys', () => {
		assert.deepEqual(Object.keys(hu).sort(), Object.keys(en).sort());
	});

	it('each message has the same placeholders in both, and uses each one', () => {
		for (const key of Object.keys(en)) {
			const names = (m) => [...m.matchAll(/\$([A-Z_]+)\$/g)].map((x) => x[1].toLowerCase()).sort();
			assert.deepEqual(Object.keys(hu[key].placeholders ?? {}).sort(), Object.keys(en[key].placeholders ?? {}).sort(), key);
			assert.deepEqual([...new Set(names(en[key].message))], Object.keys(en[key].placeholders ?? {}).sort(), `${key} (en)`);
			assert.deepEqual([...new Set(names(hu[key].message))], Object.keys(hu[key].placeholders ?? {}).sort(), `${key} (hu)`);
			for (const [name, def] of Object.entries(en[key].placeholders ?? {})) {
				assert.equal(hu[key].placeholders[name].content, def.content, `${key}.${name}`);
			}
		}
	});

	it('no message is empty or left untranslated by accident', () => {
		const sameOnPurpose = new Set(['extName', 'actionTitle', 'optionsHeading', 'optionsSpotifyHeading', 'typeAlbum']);
		for (const key of Object.keys(en)) {
			assert.ok(en[key].message.trim(), `${key} (en) empty`);
			assert.ok(hu[key].message.trim(), `${key} (hu) empty`);
			if (!sameOnPurpose.has(key)) assert.notEqual(hu[key].message, en[key].message, `${key} untranslated`);
		}
	});

	it('every key the code and markup use exists', () => {
		const used = usedKeys();
		assert.ok(used.size > 50, `found only ${used.size} keys: the scan broke`);
		for (const key of [...used].sort()) assert.ok(key in en, `${key} missing from _locales`);
	});

	it('every key exists for a reason (none left over)', () => {
		const used = usedKeys();
		// Picked by a ternary or a table: any quoted mention in the code counts.
		for (const file of sources()) {
			for (const m of readFileSync(file, 'utf8').matchAll(/'([A-Za-z0-9_]+)'/g)) used.add(m[1]);
		}
		// Built from a type name at run time: icon<Type>, icon<Type>Named.
		for (const type of ['Track', 'Album', 'Artist', 'Playlist']) {
			used.add(`icon${type}`);
			used.add(`icon${type}Named`);
		}
		for (const key of Object.keys(en)) assert.ok(used.has(key), `${key} is never used`);
	});
});
