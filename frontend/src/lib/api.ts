import { PUBLIC_API_BASE_URL } from '$env/static/public';

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1']);

/** `localhost` and `127.0.0.1` are different *sites* to a browser's SameSite cookie
 * logic even though they're the same machine — a page opened at one, calling an API
 * whose configured base URL hardcodes the other, makes every request cross-site. The
 * session cookie (SameSite=Lax) then gets set fine on login but never sent back on the
 * next request, a confusing 200-then-401 that looks like nothing is wrong until you
 * read the network tab. In local dev, always call the API via whichever loopback
 * hostname the page itself was loaded with, keeping every request same-site. This
 * never applies in production: there the API and web app are genuinely different
 * hosts/subdomains, where cookie same-site-ness works differently and this rewrite
 * must not run. */
function resolveApiBase(): string {
	const configured = new URL(PUBLIC_API_BASE_URL);
	if (
		typeof window !== 'undefined' &&
		LOOPBACK_HOSTS.has(configured.hostname) &&
		LOOPBACK_HOSTS.has(window.location.hostname)
	) {
		return `${window.location.protocol}//${window.location.hostname}:${configured.port}`;
	}
	return PUBLIC_API_BASE_URL;
}

const API_BASE = resolveApiBase();

export type JobSourceType = 'track' | 'album' | 'playlist' | 'artist' | 'search';
export type JobState = 'expanding' | 'expanded' | 'failed';

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

/** `EventSource` needs `withCredentials: true` — a plain `new EventSource(url)` defaults
 * to omitting cookies, which would silently 401 the stream since the API and the SPA are
 * different origins. */
export function createEventSource(): EventSource {
	return new EventSource(`${API_BASE}/api/stream`, { withCredentials: true });
}
