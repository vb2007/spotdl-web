import { defineConfig } from '@playwright/test';
import { loadE2eEnv } from './e2e/support/env';

loadE2eEnv();

// v37: the suite drives the real local stack (`docker compose up`, the dev database, the real
// backend and network) -- nothing here starts a server or mocks an API. Local-only by design:
// the CI runner is the production host (docs/LOCAL_DEV.md, "Browser end-to-end suite").
const baseURL = process.env.E2E_BASE_URL || 'http://localhost:5173';
// Setup's ledger preflight and teardown's zero-download check read the local compose stack, so
// the browser must drive that same stack: never a deployed origin.
if (!['localhost', '127.0.0.1', '[::1]'].includes(new URL(baseURL).hostname)) {
	throw new Error(`E2E_BASE_URL must be a loopback origin (the local stack), got ${baseURL}`);
}

// The `@network` spec does a real YouTube download, so a default run never selects it.
// `npm run test:e2e:network` opts in.
const includeNetwork = process.env.E2E_NETWORK === '1';

export default defineConfig({
	testDir: './e2e',
	testMatch: '**/*.e2e.ts',
	// One stack, one beat and one `worker-dl`: every spec shares the same queue and the same
	// two identities, so they run one at a time, and a failure is never retried into a pass.
	fullyParallel: false,
	workers: 1,
	retries: 0,
	// Seeded jobs only settle once beat's 30s dispatch pass reaches them.
	timeout: 180_000,
	expect: { timeout: 15_000 },
	grepInvert: includeNetwork ? undefined : /@network/,
	globalSetup: './e2e/global-setup.ts',
	globalTeardown: './e2e/global-teardown.ts',
	reporter: [['list'], ['html', { open: 'never' }]],
	use: {
		baseURL,
		trace: 'retain-on-failure',
		screenshot: 'only-on-failure'
	},
	// Each project pins `locale` itself: accessible names are text, and v46's Hungarian would
	// otherwise change them under the specs. The `en` projects run the whole suite; `hu` is the
	// v46 smoke (login, dashboard, a track's detail, the /account switch) plus v45's keyboard
	// journeys, with names read from the same message files the app renders. Spec 16 drives its
	// own browser contexts (one per locale) and runs once, on desktop.
	projects: [
		{
			name: 'desktop',
			testIgnore: ['**/15-hu-smoke.e2e.ts'],
			use: {
				browserName: 'chromium',
				viewport: { width: 1280, height: 800 },
				locale: 'en-US'
			}
		},
		{
			name: 'mobile',
			testIgnore: ['**/15-hu-smoke.e2e.ts', '**/16-i18n.e2e.ts'],
			use: {
				browserName: 'chromium',
				viewport: { width: 390, height: 844 },
				deviceScaleFactor: 3,
				isMobile: true,
				hasTouch: true,
				locale: 'en-US'
			}
		},
		{
			name: 'hu',
			testMatch: ['**/14-keyboard.e2e.ts', '**/15-hu-smoke.e2e.ts'],
			use: {
				browserName: 'chromium',
				viewport: { width: 1280, height: 800 },
				locale: 'hu-HU'
			}
		}
	]
});
