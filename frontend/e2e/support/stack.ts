import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { expect, request, type APIRequestContext } from '@playwright/test';
import type { Job, TrackAttempt } from '../../src/lib/api';
import { E2E_DIR, REPO_ROOT, requireEnv } from './env';

export const AUTH_DIR = path.join(E2E_DIR, '.auth');
export const ADMIN_STATE = path.join(AUTH_DIR, 'admin.json');
export const USER_STATE = path.join(AUTH_DIR, 'user.json');
const SEED_FILE = path.join(AUTH_DIR, 'seed.json');
/** Written first by global setup (and removed before it), so teardown never checks a window
 * belonging to an earlier run, even when this run's setup failed part-way. */
const RUN_FILE = path.join(AUTH_DIR, 'run.json');

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

/** v43: what spec 12 changed on the shared worker, written *before* it changes it, so the
 * spec's own `finally` and, after a killed run, the next global setup can put it back. */
const WORKER_STAGE_FILE = path.join(AUTH_DIR, 'worker-stage.json');

export interface WorkerStage {
	/** The spec paused the worker (it only does so from a running one). */
	paused?: boolean;
	/** The hold it staged, as the row's own isoformat: cleared only while still that value. */
	hold?: string;
	/** The failure streak before a release it performs (a release zeroes it). */
	failures?: number;
}

export function stageWorker(change: WorkerStage): void {
	const current = existsSync(WORKER_STAGE_FILE)
		? (JSON.parse(readFileSync(WORKER_STAGE_FILE, 'utf8')) as WorkerStage)
		: {};
	writeFileSync(WORKER_STAGE_FILE, JSON.stringify({ ...current, ...change }));
}

/** Undoes a recorded stage straight in `worker_state` (no API release, which would zero the
 * streak again), then forgets it. A no-op when nothing is recorded. */
export function restoreWorker(): void {
	if (!existsSync(WORKER_STAGE_FILE)) return;
	stackPython(
		`
import json, sys
from app.db import SessionLocal
from app.models.worker_state import WorkerState
stage = json.loads(sys.argv[1])
db = SessionLocal()
row = db.query(WorkerState).one()
if stage.get("paused"):
    row.paused = False
hold = stage.get("hold")
if hold and row.breaker_tripped_until is not None and row.breaker_tripped_until.isoformat() == hold:
    row.breaker_tripped_until = None
# Only over the zero the spec's own release left: a real failure since then is the
# stack's, not the spec's, and is kept.
if "failures" in stage and row.consecutive_failures == 0:
    row.consecutive_failures = stage["failures"]
db.commit()
`,
		[readFileSync(WORKER_STAGE_FILE, 'utf8')]
	);
	rmSync(WORKER_STAGE_FILE);
}

/** v43: written just before spec 12 stops `worker-expand`, removed once it is started again,
 * so only a run killed in between makes the next global setup start it (a worker-expand the
 * developer stopped on purpose is left alone). */
const EXPAND_STOPPED_FILE = path.join(AUTH_DIR, 'expand-stopped');

function compose(...args: string[]): string {
	return execFileSync('docker', ['compose', ...args], {
		cwd: REPO_ROOT,
		encoding: 'utf8',
		stdio: ['ignore', 'pipe', 'pipe']
	}).trim();
}

export function stopExpandWorker(): void {
	writeFileSync(EXPAND_STOPPED_FILE, '');
	compose('stop', 'worker-expand');
}

/** Starts `worker-expand` again if this suite stopped it, and waits until it's healthy. */
export async function restartExpandWorker(): Promise<void> {
	if (!existsSync(EXPAND_STOPPED_FILE)) return;
	compose('start', 'worker-expand');
	rmSync(EXPAND_STOPPED_FILE);
	const deadline = Date.now() + 90_000;
	while (compose('ps', 'worker-expand', '--format', '{{.Health}}') !== 'healthy') {
		if (Date.now() > deadline) throw new Error('worker-expand did not come back healthy');
		await new Promise((resolve) => setTimeout(resolve, 2000));
	}
}

/** Anything `worker-expand` is busy with right now (any user's expansion, a library sweep):
 * stopping it would kill that mid-task. */
export function expandWorkerBusy(): string[] {
	const out = stackPython(`
from sqlalchemy import text
from app.db import SessionLocal
db = SessionLocal()
busy = []
n = db.execute(text("select count(*) from jobs where state = 'expanding'")).scalar()
if n:
    busy.append(f"{n} expanding job(s)")
if db.execute(text("select count(*) from library_sort_runs where state = 'running'")).scalar():
    busy.append("a library sweep")
print("; ".join(busy))
`);
	return out ? [out] : [];
}

/** The one library-sweep report row, as JSON (or 'null'), so a spec that runs a sweep can put
 * the developer's last report back afterwards. */
export function snapshotSweepReport(): string {
	return stackPython(`
import json
from app.db import SessionLocal
from app.models.library_sort_run import LibrarySortRun
row = SessionLocal().get(LibrarySortRun, 1)
fields = ("started_at", "finished_at", "total", "processed", "moved", "skipped_present", "quarantined", "errors")
print(json.dumps(None if row is None else {
    f: (getattr(row, f).isoformat() if hasattr(getattr(row, f), "isoformat") else getattr(row, f))
    for f in fields
}))
`);
}

/** Puts a snapshot back, only once the row is idle again (never over a running sweep). */
export function restoreSweepReport(snapshot: string): void {
	stackPython(
		`
import json, sys
from datetime import datetime
from app.db import SessionLocal
from app.models.library_sort_run import LibrarySortRun
snap = json.loads(sys.argv[1])
db = SessionLocal()
row = db.get(LibrarySortRun, 1)
if snap is not None and row is not None and row.state.value == "idle":
    for key, value in snap.items():
        if key in ("started_at", "finished_at") and value is not None:
            value = datetime.fromisoformat(value)
        setattr(row, key, value)
    db.commit()
`,
		[snapshot]
	);
}

/** Tracks already in the dev ledger (`downloaded_tracks`, files under `./downloads`), so a job
 * for one settles as `skipped_duplicate` without ever reaching YouTube. Each is used by exactly
 * one identity: spec 7 relies on the user never owning a title the admin owns. */
export const LEDGER_TRACKS = {
	/** The admin's seed job (specs 1, 3, 4, 7, 8, 10). */
	adminSeed: '69kOkLUCkxIZYexIgSG8rq', // Daft Punk - Get Lucky
	/** The user's seed job (specs 1, 7). */
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
	admin: SeedJob;
	user: SeedJob;
	/** An admin-owned track whose attempts recorded a real network path (left by an earlier
	 * `@network` pass), for spec 3's real-path labels. Null on a dev DB without one. Its job is
	 * archived by setup, and its title is the only one of its kind among the admin's jobs. */
	realPath: SeedJob | null;
}

export function readSeed(): Seed {
	return JSON.parse(readFileSync(SEED_FILE, 'utf8')) as Seed;
}

export interface Run {
	/** Database time when the run started, for the teardown's zero-download check. */
	startedAt: string;
}

export function readRun(): Run {
	return JSON.parse(readFileSync(RUN_FILE, 'utf8')) as Run;
}

export { RUN_FILE, SEED_FILE };

/** Runs a Python snippet inside a backend service: by default `worker-meta`, which has the app
 * code, the dev database and both file roots (`/downloads` and the library) mounted -- `api`
 * mounts neither. */
export function stackPython(
	code: string,
	args: string[] = [],
	service: 'worker-meta' | 'worker-dl' = 'worker-meta'
): string {
	return execFileSync('docker', ['compose', 'exec', '-T', service, 'python', '-c', code, ...args], {
		cwd: REPO_ROOT,
		encoding: 'utf8',
		stdio: ['ignore', 'pipe', 'pipe']
	}).trim();
}

/** The `LEDGER_TRACKS` ids worker-dl would NOT resolve as duplicates right now, by the dedup
 * gate's own check: no ledger row, its file is gone (a download), or its root looks unmounted
 * (held as `waiting`, so the job never settles). Asked inside `worker-dl`, the worker that
 * actually decides. Since v38 it mounts the library too, so its answer matches `worker-meta`'s;
 * before that, a file the library sort moved was a hit there and a miss here. */
export function ledgerMisses(spotifyIds: string[]): string[] {
	const out = stackPython(
		`
import sys
from app.services.dedup import LedgerRootUnavailable, is_already_downloaded
def miss(i):
    try:
        return is_already_downloaded(i) is None
    except LedgerRootUnavailable:
        return True
print(" ".join(i for i in sys.argv[1:] if miss(i)))
`,
		spotifyIds,
		'worker-dl'
	);
	return out ? out.split(' ') : [];
}

export interface MovedTrack {
	spotifyId: string;
	/** The ledger's `file_path`: under the library root, where the sort moved it. */
	filePath: string;
	/** sha256 of that file, read on the stack side straight from the ledger path. */
	sha256: string;
}

/** Ledger rows the library sort moved (`in_library`, the file present under the library root),
 * that the admin identity never submitted, so they stay the user's alone (the `LEDGER_TRACKS`
 * rule spec 7 relies on), and that the user never downloaded itself, so every resubmission is
 * cross-user. Ordered by Spotify id, so each project picks the same row every run. */
export function movedLedgerTracks(): MovedTrack[] {
	const out = stackPython(
		`
import hashlib, json, sys
from pathlib import Path
from sqlalchemy import text
from app.db import SessionLocal
from app.services import app_settings
db = SessionLocal()
root = Path(app_settings.get_library_settings(db).library_target_dir)
rows = db.execute(text("""
    select d.spotify_track_id, d.file_path from downloaded_tracks d
    where d.in_library
      and not (d.spotify_track_id = any(:ledger))
      and not exists (
          select 1 from tracks t
          join jobs j on j.id = t.job_id
          join users u on u.id = j.user_id
          where u.email = :admin and t.spotify_track_id = d.spotify_track_id
      )
      and not exists (
          select 1 from track_attempts a
          join tracks t on t.id = a.track_id
          join jobs j on j.id = t.job_id
          join users u on u.id = j.user_id
          where u.email = :user and t.spotify_track_id = d.spotify_track_id
            and a.network_path is not null
      )
    order by d.spotify_track_id
"""), {"ledger": sys.argv[3:], "admin": sys.argv[1], "user": sys.argv[2]}).all()
moved = []
for spotify_id, file_path in rows:
    path = Path(file_path)
    if path.is_relative_to(root) and path.is_file():
        moved.append({"spotifyId": spotify_id, "filePath": file_path,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if len(moved) == 2:
        break
print(json.dumps(moved))
`,
		[
			normalizeEmail(adminIdentity().email),
			normalizeEmail(userIdentity().email),
			...Object.values(LEDGER_TRACKS)
		]
	);
	return JSON.parse(out) as MovedTrack[];
}

/** The ledger's current `file_path` for a Spotify id, or null without a row. */
export function ledgerFilePath(spotifyId: string): string | null {
	const out = stackPython(
		`
import sys
from app.db import SessionLocal
from app.models import DownloadedTrack
row = SessionLocal().get(DownloadedTrack, sys.argv[1])
print(row.file_path if row else "")
`,
		[spotifyId]
	);
	return out || null;
}

/** The ids worker-dl would actually download (no ledger row, or its file gone under a root it
 * can see), by the dedup gate's own check. Unlike `ledgerMisses`, a root that looks unmounted
 * isn't counted: that track is held, never downloaded. */
export function ledgerDownloads(spotifyIds: string[]): string[] {
	const out = stackPython(
		`
import sys
from app.services.dedup import LedgerRootUnavailable, is_already_downloaded
def downloads(i):
    try:
        return is_already_downloaded(i) is None
    except LedgerRootUnavailable:
        return False
print(" ".join(i for i in sys.argv[1:] if downloads(i)))
`,
		spotifyIds,
		'worker-dl'
	);
	return out ? out.split(' ') : [];
}

/** `{ trackId, jobId }` of the given user's tracks with a recorded network path, newest first. */
export function tracksWithNetworkPath(email: string): { trackId: string; jobId: string }[] {
	const out = stackPython(
		`
import sys
from sqlalchemy import text
from app.db import SessionLocal
rows = SessionLocal().execute(text("""
    select t.id, t.job_id from track_attempts a
    join tracks t on t.id = a.track_id
    join jobs j on j.id = t.job_id
    join users u on u.id = j.user_id
    where u.email = :email and a.network_path is not null
    group by t.id, t.job_id order by max(a.finished_at) desc limit 20
"""), {"email": sys.argv[1]})
print(" ".join(f"{t}:{j}" for t, j in rows))
`,
		[normalizeEmail(email)]
	);
	return out
		? out.split(' ').map((pair) => {
				const [trackId, jobId] = pair.split(':');
				return { trackId, jobId };
			})
		: [];
}

/** How many `download_track` tasks worker-dl is running right now for either e2e identity, by
 * asking the worker itself (celery inspect): a cancelled job's download keeps going, and its
 * attempt row only appears once it ends. Throws if worker-dl doesn't answer. */
export function e2eDownloadsInFlight(): string {
	return stackPython(
		`
import sys
from sqlalchemy import text
from app.db import SessionLocal
from app.tasks.celery_app import celery_app
active = celery_app.control.inspect(timeout=5).active()
workers = [w for w in (active or {}) if w.startswith("worker-dl@")]
if not workers:
    sys.exit("worker-dl did not answer celery inspect")
ids = [t["args"][0] for w in workers for t in active[w] if t["name"].endswith("download_track")]
print(SessionLocal().execute(text("""
    select count(*) from tracks t
    join jobs j on j.id = t.job_id
    join users u on u.id = j.user_id
    where u.email in (:a, :b) and cast(t.id as text) = any(:ids)
"""), {"a": sys.argv[1], "b": sys.argv[2], "ids": ids}).scalar())
`,
		[normalizeEmail(adminIdentity().email), normalizeEmail(userIdentity().email)]
	);
}

/** How the backend stores an email (`services/users.py`): login accepts any case. */
export function normalizeEmail(email: string): string {
	return email.trim().toLowerCase();
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

/** Cancels a job unless it settled: anything else could be a real download in flight, which
 * must not keep retrying on the ladder after the run. Acts as the job's owner (`storageState`,
 * the admin by default). Uses its own request context, so it still works when a test-level
 * timeout has already closed the page. */
export async function cancelUnlessSettled(
	baseURL: string,
	jobId: string,
	storageState: string = ADMIN_STATE
): Promise<void> {
	const owner = await request.newContext({ baseURL, storageState });
	try {
		const job = (await (await owner.get(`/api/jobs/${jobId}`)).json()) as Job;
		if (job.status.lifecycle !== 'settled') {
			const cancelled = await owner.delete(`/api/jobs/${jobId}`);
			expect.soft(cancelled.status(), `cancelling unsettled job ${jobId}`).toBe(200);
		}
	} finally {
		await owner.dispose();
	}
}

export function isSettled(job: Job): boolean {
	return ['settled', 'failed', 'cancelled'].includes(job.status.lifecycle);
}

/** v41: the timeline's entries, newest first, with consecutive attempts that read the same
 * (outcome, error class, error text, note) collapsed into one. A copy of the component's rule
 * for the same reason as `expectedAttemptVia` below. */
export function expectedTimeline(oldestFirst: TrackAttempt[]): TrackAttempt[][] {
	const entries: TrackAttempt[][] = [];
	for (const attempt of [...oldestFirst].reverse()) {
		const last = entries.at(-1)?.[0];
		const same =
			last !== undefined &&
			last.outcome === attempt.outcome &&
			last.error_type === attempt.error_type &&
			last.error_message === attempt.error_message &&
			last.warning_message === attempt.warning_message;
		if (same) entries.at(-1)!.push(attempt);
		else entries.push([attempt]);
	}
	return entries;
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
