import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import type { APIRequestContext } from '@playwright/test';
import type { Job, TrackAttempt } from '../../src/lib/api';
import { E2E_DIR, REPO_ROOT, requireEnv } from './env';

export const AUTH_DIR = path.join(E2E_DIR, '.auth');
export const ADMIN_STATE = path.join(AUTH_DIR, 'admin.json');
export const USER_STATE = path.join(AUTH_DIR, 'user.json');
const SEED_FILE = path.join(AUTH_DIR, 'seed.json');

export interface Identity {
	email: string;
	password: string;
}

export function adminIdentity(): Identity {
	return { email: requireEnv('E2E_ADMIN_EMAIL'), password: requireEnv('E2E_ADMIN_PASSWORD') };
}

export function userIdentity(): Identity {
	return { email: requireEnv('E2E_USER_EMAIL'), password: requireEnv('E2E_USER_PASSWORD') };
}

/** Tracks already in the dev ledger (`downloaded_tracks`, files under `./downloads`), so a job
 * for one settles as `skipped_duplicate` without ever reaching YouTube. Each is used by exactly
 * one identity: spec 7 relies on the user never owning a title the admin owns. */
export const LEDGER_TRACKS = {
	/** The admin's seed job (specs 1, 3, 4, 7, 8). */
	adminSeed: '69kOkLUCkxIZYexIgSG8rq', // Daft Punk - Get Lucky
	/** The user's seed job (specs 1, 6, 7). */
	userSeed: '2KHRENHQzTIQ001nlP9Gdc', // Daft Punk - Contact
	/** Spec 2's fresh submissions, one per project, so each run's row is unambiguous. */
	submitDesktop: '79koEJRtKOOGJ0VSAF3FMk', // Daft Punk - Motherboard
	submitMobile: '0k1xMUwn9sb7bZiqdT9ygx' // Daft Punk - Beyond
} as const;

export function spotifyTrackUrl(id: string): string {
	return `https://open.spotify.com/track/${id}`;
}

/** A well-formed track URL for an id Spotify doesn't have: its expansion fails, leaving a
 * zero-track `failed` job in the incoming overlay until it's dismissed. Random per call, so a
 * spec can find its own row by URL. */
export function missingTrackUrl(): string {
	const alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
	let id = '';
	for (let i = 0; i < 22; i++) id += alphabet[Math.floor(Math.random() * alphabet.length)];
	return spotifyTrackUrl(id);
}

export interface SeedJob {
	jobId: string;
	title: string;
	trackId: string;
	trackTitle: string;
}

export interface Seed {
	/** Database time when the run started, for the teardown's zero-download check. */
	startedAt: string;
	admin: SeedJob;
	user: SeedJob;
}

export function readSeed(): Seed {
	return JSON.parse(readFileSync(SEED_FILE, 'utf8')) as Seed;
}

export { SEED_FILE };

/** Runs a Python snippet inside `worker-meta`, which has the app code, the dev database and
 * both file roots (`/downloads` and the library) mounted -- `api` mounts neither. */
export function stackPython(code: string, args: string[] = []): string {
	return execFileSync(
		'docker',
		['compose', 'exec', '-T', 'worker-meta', 'python', '-c', code, ...args],
		{ cwd: REPO_ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }
	).trim();
}

/** The file `GET /api/tracks/{id}/file` serves, resolved by the API's own resolver and hashed
 * on the stack side, with its modification time (epoch seconds, the stack's clock). */
export function serverTrackFile(trackId: string): { sha256: string; mtime: number; name: string } {
	const out = stackPython(
		`
import hashlib, sys, uuid
from app.db import SessionLocal
from app.models.track import Track
from app.routers.tracks import _resolve_track_file_path
db = SessionLocal()
path = _resolve_track_file_path(db, db.get(Track, uuid.UUID(sys.argv[1])))
print(hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime, path.name)
`,
		[trackId]
	);
	const [sha256, mtime, ...name] = out.split(' ');
	return { sha256, mtime: Number(mtime), name: name.join(' ') };
}

/** Polls `GET /api/jobs/{id}` until `done` holds, returning the last job read. */
export async function waitForJob(
	request: APIRequestContext,
	jobId: string,
	done: (job: Job) => boolean,
	timeoutMs: number
): Promise<Job> {
	const deadline = Date.now() + timeoutMs;
	for (;;) {
		const response = await request.get(`/api/jobs/${jobId}`);
		if (!response.ok()) throw new Error(`GET /api/jobs/${jobId}: ${response.status()}`);
		const job = (await response.json()) as Job;
		if (done(job)) return job;
		if (Date.now() > deadline) {
			throw new Error(`job ${jobId} still ${JSON.stringify(job.status)} after ${timeoutMs}ms`);
		}
		await new Promise((resolve) => setTimeout(resolve, 2000));
	}
}

export function isSettled(job: Job): boolean {
	return ['settled', 'failed', 'cancelled'].includes(job.status.lifecycle);
}

/** What `TrackRow.svelte` renders for an attempt's network path (v35 (b)). Kept as a copy on
 * purpose: spec 3 checks the UI against the API's `network_path`, so this is the contract,
 * not a reuse of the component's own function. */
export function expectedAttemptVia(attempt: TrackAttempt): string {
	if (attempt.network_path === 'direct-ipv4') return 'direct · IPv4';
	if (attempt.network_path === 'direct-ipv6') return 'direct · IPv6';
	if (attempt.network_path === 'proxy') return `via proxy ${attempt.proxy_label ?? ''}`.trim();
	if (attempt.proxy_id) return 'via proxy';
	if (attempt.outcome === 'completed' || attempt.outcome === 'failed') return 'direct';
	return 'no network';
}
