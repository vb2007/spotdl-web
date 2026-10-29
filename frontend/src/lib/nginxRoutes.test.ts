import { readdirSync, readFileSync, statSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

// v62 (review round 2): CLAUDE.md's invariant, every route needs its own nginx `location`
// block. Since v62 an unknown path is answered with the SPA fallback (404.html, F5), so a
// route missing its block would still render, but under HTTP status 404, not as a visible
// failure: this check stands in for the failure that used to give it away.
const ROUTES = new URL('../routes/', import.meta.url);
const NGINX = new URL('../../nginx.conf', import.meta.url);

function routePaths(dir: URL, prefix = ''): string[] {
	const paths: string[] = [];
	for (const entry of readdirSync(dir)) {
		if (!statSync(new URL(entry, dir)).isDirectory()) continue;
		const child = new URL(`${entry}/`, dir);
		const path = `${prefix}/${entry}`;
		if (readdirSync(child).includes('+page.svelte')) paths.push(path);
		paths.push(...routePaths(child, path));
	}
	return paths;
}

describe('every route has its own nginx location', () => {
	it('lists each prerendered page', () => {
		const conf = readFileSync(NGINX, 'utf8');
		const routes = routePaths(ROUTES);
		expect(routes.length).toBeGreaterThan(0);
		for (const route of routes) {
			expect(conf, route).toContain(`location = ${route} {`);
			expect(conf, route).toContain(`try_files ${route}.html =404;`);
		}
		expect(conf).toContain('location = / {');
	});
});
