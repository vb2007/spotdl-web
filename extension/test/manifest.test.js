// The manifest's promises: Firefox MV3, a pinned id, the narrowest permissions.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { it } from 'node:test';

const manifest = JSON.parse(readFileSync(new URL('../manifest.json', import.meta.url), 'utf8'));

it('is MV3 for Firefox, with a pinned id and the current ESR as its floor', () => {
	assert.equal(manifest.manifest_version, 3);
	assert.equal(manifest.browser_specific_settings.gecko.id, 'spotdl-web@vb2007.hu');
	assert.equal(manifest.browser_specific_settings.gecko.strict_min_version, '153.0');
	assert.match(manifest.version, /^\d+\.\d+\.\d+$/);
	assert.equal(manifest.default_locale, 'en');
});

it('asks for storage, Spotify and the default app only; never <all_urls>', () => {
	assert.deepEqual(manifest.permissions, ['storage']);
	assert.deepEqual(manifest.host_permissions, ['https://open.spotify.com/*', 'https://spotdl.vb2007.hu/*']);
	const everything = JSON.stringify(manifest);
	assert.ok(!everything.includes('<all_urls>'));
	assert.ok(!manifest.optional_host_permissions.includes('*://*/*'));
	for (const pattern of manifest.optional_host_permissions) assert.ok(!/:\d+\//.test(pattern), pattern);
});

it('runs its content script on open.spotify.com only', () => {
	assert.equal(manifest.content_scripts.length, 1);
	assert.deepEqual(manifest.content_scripts[0].matches, ['https://open.spotify.com/*']);
	assert.equal(manifest.content_scripts[0].js.at(-1), 'content/main.js');
});
