// Turns a raw open.spotify.com page capture into a test fixture (see README.md in this folder).
//
//   node test/fixtures/sanitize.mjs <raw.html> <out.html> <page url>
//
// Keeps the structure the selectors read (tags, data-testid, data-encore-id, role, aria-*,
// href, dir, tabindex) and the visible text, and drops everything else: scripts, styles,
// hashed class names, inline styles, image sources, SVG path data, the hidden language picker,
// and any query string on a link but the one Spotify itself navigates with (`highlight`).
// The page URL is written into the file (a `<meta name="fixture-url">`), so a test loads the
// fixture at the address it was captured from.
import { readFileSync, writeFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';

const [raw, out, pageUrl] = process.argv.slice(2);
if (!raw || !out || !pageUrl) {
	console.error('usage: node test/fixtures/sanitize.mjs <raw.html> <out.html> <page url>');
	process.exit(2);
}

const KEEP = /^(data-testid|data-encore-id|role|aria-[a-z-]+|href|dir|tabindex|type|id)$/;
// The extension's own icons, menu and toast too, when the capture ran with it installed.
const DROP =
	'script, style, link, meta, noscript, iframe, template, [data-testid="language-selection-modal"], ' +
	'[data-spotdl-icon], .spotdl-ext-menu, .spotdl-ext-toast';

const doc = new JSDOM(readFileSync(raw, 'utf8')).window.document;
const root = doc.querySelector('[data-testid="root"]') ?? doc.body;
for (const el of root.querySelectorAll(DROP)) el.remove();
for (const svg of root.querySelectorAll('svg')) svg.replaceChildren();
for (const el of [root, ...root.querySelectorAll('*')]) {
	for (const attr of [...el.attributes]) {
		if (!KEEP.test(attr.name)) el.removeAttribute(attr.name);
	}
	const href = el.getAttribute('href');
	if (href && href.includes('?')) {
		const url = new URL(href, 'https://open.spotify.com');
		const highlight = url.searchParams.get('highlight');
		const keep = url.origin === 'https://open.spotify.com' ? url.pathname : `${url.origin}${url.pathname}`;
		el.setAttribute('href', highlight ? `${keep}?highlight=${highlight}` : keep);
	}
}

const html = `<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="fixture-url" content="${pageUrl}"><title>fixture</title></head>
<body>
${root.outerHTML}
</body>
</html>
`;
writeFileSync(out, html);
console.log(`${out}: ${(html.length / 1024).toFixed(0)} KiB`);
