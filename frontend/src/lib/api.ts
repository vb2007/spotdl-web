import { PUBLIC_API_BASE_URL } from '$env/static/public';

/** v12: both production (via the `web` container's nginx /api/ proxy, see
 * frontend/nginx.conf) and local dev (via Vite's dev-server /api proxy, see
 * vite.config.ts) are same-origin by default — `PUBLIC_API_BASE_URL` is "" in both, and
 * every request is a plain relative `/api/...` fetch against whatever origin the page
 * itself was loaded from. No cross-origin request, no CORS, no SameSite-cookie special
 * casing needed either way.
 *
 * This function only matters if `PUBLIC_API_BASE_URL` is explicitly set to a real
 * absolute URL (e.g. pointing dev's Vite server directly at the api container's
 * published port for debugging, bypassing the proxy) — in which case it's used exactly
 * as configured, no rewriting. `new URL('')` throws, so the empty-string default must be
 * checked first. */
function resolveApiBase(): string {
	if (!PUBLIC_API_BASE_URL) {
		return '';
	}
	return new URL(PUBLIC_API_BASE_URL).toString().replace(/\/$/, '');
}

const API_BASE = resolveApiBase();

export type JobSourceType = 'track' | 'album' | 'playlist' | 'artist' | 'search';
export type JobState = 'expanding' | 'expanded' | 'failed' | 'cancelled';

export interface Job {
	id: string;
	source_url: string;
	source_type: JobSourceType;
	state: JobState;
	priority: number;
	error: string | null;
	created_at: string;
	track_counts: Record<string, number>;
}

export type TrackState =
	| 'pending'
	| 'queued'
	| 'downloading'
	| 'completed'
	| 'waiting'
	| 'lookup_failed'
	| 'failed'
	| 'skipped_duplicate'
	| 'cancelled';

export type TrackErrorType = 'audio_provider' | 'lookup' | 'other';

export interface Track {
	id: string;
	job_id: string;
	state: TrackState;
	title: string | null;
	artists: string[] | null;
	album: string | null;
	spotify_track_id: string;
	attempt_count: number;
	scheduled_at: string | null;
	last_error: string | null;
	last_error_type: TrackErrorType | null;
}

export interface TrackStateEvent {
	type: 'track.state';
	track_id: string;
	job_id: string;
	state: TrackState;
	progress?: number;
	scheduled_at?: string;
	error?: string;
	attempt_count?: number;
	ts: string;
}

export interface JobStateEvent {
	type: 'job.state';
	job_id: string;
	state: JobState;
	error?: string;
	ts: string;
}

export type StreamEvent = TrackStateEvent | JobStateEvent;

export interface WorkerStatus {
	paused: boolean;
	breaker_tripped_until: string | null;
	breaker_trip_count: number;
	consecutive_failures: number;
}

export type ProxySource = 'file' | 'manual';

export interface Proxy {
	id: string;
	/** scheme://host:port only -- the backend never returns a proxy's plaintext
	 * user:pass, matching the same redaction discipline applied to logs/last_error. */
	url: string;
	enabled: boolean;
	source: ProxySource;
	consecutive_failures: number;
	cooldown_until: string | null;
	last_used_at: string | null;
	last_success_at: string | null;
}

export interface OutputSettings {
	default_format: string;
	default_bitrate: string;
	/** Informational only -- read-only in the UI. Fixed by the container's volume mount
	 * at deploy time (DOWNLOAD_OUTPUT_DIR), not editable at the app level; never sent by
	 * updateOutputSettings. */
	output_dir: string;
	output_template: string;
}

/** Only the fields the settings UI can actually change -- see OutputSettings.output_dir. */
export type EditableOutputSettings = Pick<
	OutputSettings,
	'default_format' | 'default_bitrate' | 'output_template'
>;

/** The real, live set of format/bitrate values the installed spotdl accepts --
 * introspected server-side from spotdl's own argparse definition, never hardcoded here. */
export interface OutputOptions {
	formats: string[];
	bitrates: string[];
}

export class ApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
		this.name = 'ApiError';
	}
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	const response = await fetch(`${API_BASE}${path}`, {
		...init,
		credentials: 'include',
		headers: {
			...(init?.body ? { 'Content-Type': 'application/json' } : {}),
			...init?.headers
		}
	});

	if (!response.ok) {
		let detail = response.statusText;
		try {
			const body = await response.json();
			detail = body.detail ?? detail;
		} catch {
			// Non-JSON error body — fall back to statusText.
		}
		throw new ApiError(response.status, detail);
	}

	if (response.status === 204) {
		return undefined as T;
	}
	return (await response.json()) as T;
}

export function login(email: string, password: string): Promise<{ email: string }> {
	return request('/api/auth/login', {
		method: 'POST',
		body: JSON.stringify({ email, password })
	});
}

export function me(): Promise<{ email: string }> {
	return request('/api/auth/me');
}

export function logout(): Promise<{ status: string }> {
	return request('/api/auth/logout', { method: 'POST' });
}

export function createJob(url: string): Promise<Job> {
	return request('/api/jobs', {
		method: 'POST',
		body: JSON.stringify({ url })
	});
}

export function listJobs(): Promise<Job[]> {
	return request('/api/jobs');
}

export function listJobTracks(jobId: string): Promise<Track[]> {
	return request(`/api/jobs/${jobId}/tracks`);
}

/** Every track across every job in one request -- what `queue.ts`'s `loadAll()` uses
 * instead of firing one `listJobTracks` call per job. See `GET /api/tracks`'s own
 * comment for why: N concurrent per-job requests stopped being harmless once real usage
 * accumulated 100+ historical jobs. */
export function listTracks(): Promise<Track[]> {
	return request('/api/tracks');
}

export function cancelJob(jobId: string): Promise<Job> {
	return request(`/api/jobs/${jobId}`, { method: 'DELETE' });
}

export function setJobPriority(jobId: string, priority: number): Promise<Job> {
	return request(`/api/jobs/${jobId}/priority`, {
		method: 'PATCH',
		body: JSON.stringify({ priority })
	});
}

export function bumpJob(jobId: string): Promise<Job> {
	return request(`/api/jobs/${jobId}/bump`, { method: 'POST' });
}

export function cancelTrack(trackId: string): Promise<Track> {
	return request(`/api/tracks/${trackId}`, { method: 'DELETE' });
}

export function retryTrack(trackId: string): Promise<Track & { breaker_held: boolean }> {
	return request(`/api/tracks/${trackId}/retry`, { method: 'POST' });
}

export function workerStatus(): Promise<WorkerStatus> {
	return request('/api/worker/status');
}

export function pauseWorker(): Promise<WorkerStatus> {
	return request('/api/worker/pause', { method: 'POST' });
}

export function resumeWorker(): Promise<WorkerStatus> {
	return request('/api/worker/resume', { method: 'POST' });
}

export function releaseBreaker(): Promise<WorkerStatus> {
	return request('/api/worker/breaker/release', { method: 'POST' });
}

export function listProxies(): Promise<Proxy[]> {
	return request('/api/proxies');
}

export function createProxy(url: string): Promise<Proxy> {
	return request('/api/proxies', {
		method: 'POST',
		body: JSON.stringify({ url })
	});
}

export function setProxyEnabled(proxyId: string, enabled: boolean): Promise<Proxy> {
	return request(`/api/proxies/${proxyId}`, {
		method: 'PATCH',
		body: JSON.stringify({ enabled })
	});
}

/** A manual proxy is hard-deleted (204, no body); a file-sourced proxy is only
 * soft-disabled (200, returns the updated row) -- see the backend's own docstring for
 * why. `undefined` back means "the row is really gone." */
export function deleteProxy(proxyId: string): Promise<Proxy | undefined> {
	return request(`/api/proxies/${proxyId}`, { method: 'DELETE' });
}

export function getOutputSettings(): Promise<OutputSettings> {
	return request('/api/settings/output');
}

export function getOutputOptions(): Promise<OutputOptions> {
	return request('/api/settings/output/options');
}

export function updateOutputSettings(
	patch: Partial<EditableOutputSettings>
): Promise<OutputSettings> {
	return request('/api/settings/output', {
		method: 'PATCH',
		body: JSON.stringify(patch)
	});
}

/** `EventSource` needs `withCredentials: true` for the (now rare, see resolveApiBase)
 * case where `API_BASE` is a genuinely different absolute origin — a plain
 * `new EventSource(url)` defaults to omitting cookies there, which would silently 401
 * the stream. A harmless no-op for the same-origin default. */
export function createEventSource(): EventSource {
	return new EventSource(`${API_BASE}/api/stream`, { withCredentials: true });
}
