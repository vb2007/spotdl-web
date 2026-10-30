import { describe, expect, it } from 'vitest';
import { loginFor, safeNext } from './nextPath';

describe('v65 login next', () => {
	it("keeps a share's own path and query", () => {
		const share = '/share?text=Listen%20https%3A%2F%2Fopen.spotify.com%2Ftrack%2Fx&title=a';
		expect(safeNext(share)).toBe(share);
		expect(safeNext('/')).toBe('/');
		expect(safeNext('/account#install')).toBe('/account#install');
		// An escape stays escaped: a same-origin path, not a redirect.
		expect(safeNext('/%0a/evil')).toBe('/%0a/evil');
	});

	it('round-trips through the login address', () => {
		const share = '/share?url=https%3A%2F%2Fopen.spotify.com%2Ftrack%2Fx&text=a+b';
		const login = new URL(loginFor(share), 'https://x.test');
		expect(login.pathname).toBe('/login');
		expect(safeNext(login.searchParams.get('next'))).toBe(share);
	});

	it.each([
		null,
		undefined,
		'',
		'https://evil.example/',
		'http:evil.example',
		'//evil.example/share',
		'///evil.example',
		'/\\evil.example',
		'\\\\evil.example',
		'/\t/evil.example',
		'javascript:alert(1)',
		'share',
		'/login',
		'/login?next=/share'
	])('refuses %s', (raw) => {
		expect(safeNext(raw)).toBeNull();
	});
});
