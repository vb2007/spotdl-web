import { existsSync } from 'node:fs';
import path from 'node:path';

export const E2E_DIR = path.resolve(import.meta.dirname, '..');
export const REPO_ROOT = path.resolve(E2E_DIR, '..', '..');
const ENV_FILE = path.join(E2E_DIR, '.env.e2e');

/** Loads the gitignored `e2e/.env.e2e` into `process.env`, leaving any variable already set in
 * the shell as it is. A missing file is only an error once a credential is actually read. */
export function loadE2eEnv(): void {
	if (existsSync(ENV_FILE)) process.loadEnvFile(ENV_FILE);
}

export function requireEnv(name: string): string {
	const value = process.env[name];
	if (!value) {
		throw new Error(
			`${name} is not set. Copy frontend/e2e/.env.e2e.example to frontend/e2e/.env.e2e and fill in ` +
				'two test identities (docs/LOCAL_DEV.md, "Browser end-to-end suite").'
		);
	}
	return value;
}
