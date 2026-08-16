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

/** v18's two derived rollup axes -- never stored, always computed server-side from the
 * job's own state plus its tracks' states (see CLAUDE.md's "Job rollup status" section).
 * `outcome` is only non-null once `lifecycle === 'settled'`. */
export type JobLifecycle = 'expanding' | 'active' | 'waiting' | 'settled' | 'cancelled' | 'failed';
export type JobOutcome = 'complete' | 'partial';
export interface JobStatus {
	lifecycle: JobLifecycle;
	outcome: JobOutcome | null;
}

/** The wire/filter form `status=` params use -- `settled:partial`, or the bare lifecycle
 * name otherwise. Mirrors `rollup.status_key` server-side. */
export function statusKey(status: JobStatus): string {
	return status.outcome ? `${status.lifecycle}:${status.outcome}` : status.lifecycle;
}

/** Every token the state filter can offer, in the server's own display rank order
 * (`rollup.STATUS_ORDER`) -- still-in-flight first, dead ends last. */
export const STATUS_TOKENS: string[] = [
	'expanding',
	'active',
	'waiting',
	'settled:partial',
	'settled:complete',
	'cancelled',
	'failed'
];

export const STATUS_LABEL: Record<string, string> = {
	expanding: 'tuning in',
	active: 'active',
	waiting: 'waiting',
	'settled:partial': 'done — partial',
	'settled:complete': 'done',
	cancelled: 'cancelled',
	failed: 'failed'
};

export interface Job {
	id: string;
	source_url: string;
	source_type: JobSourceType;
	state: JobState;
	priority: number;
	error: string | null;
	created_at: string;
	/** null while not archived -- v19. */
	archived_at: string | null;
	track_counts: Record<string, number>;
	/** Whose job this is -- always present, but only interesting once an admin's "all
	 * users" scope makes a foreign row visible at all. */
	owner_email: string;
	/** v25: null until the owner's first successful upstream `GET /user`. Display this,
	 * falling back to owner_email -- see `displayName()`. */
	owner_username: string | null;
	/** v18: derived display name (first track's playlist/album name, else its own song
	 * name, else the raw source_url for a job with no tracks yet) -- `Job` itself has no
	 * title column. */
	title: string;
	status: JobStatus;
}

/** v16 removed `TrackState.FAILED` (a migration, not just a rename) -- the backend has
 * never sent this value since. Any lookup keyed on `TrackState` must cover exactly this
 * set, no more. */
export type TrackState =
	| 'pending'
	| 'queued'
	| 'downloading'
	| 'completed'
	| 'waiting'
	| 'lookup_failed'
	| 'skipped_duplicate'
	| 'cancelled';

export type TrackErrorType = 'audio_provider' | 'lookup' | 'other' | 'no_output';

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

export type TrackAttemptOutcome = 'completed' | 'failed' | 'cancelled' | 'skipped_duplicate';

/** One row per `download_track` invocation (v24) -- `GET /api/tracks/{id}/attempts`,
 * oldest first. `proxy_id` is `null` for a direct attempt, `error_type`/`error_message`
 * are `null` for anything that isn't `failed`. Diagnostic only, not a headline feature --
 * see TrackRow.svelte's rendering. */
export interface TrackAttempt {
	id: string;
	attempt_number: number;
	started_at: string;
	finished_at: string;
	outcome: TrackAttemptOutcome;
	error_type: TrackErrorType | null;
	error_message: string | null;
	proxy_id: string | null;
}

/** The parent-job summary `GET /api/tracks`/`?scope=track` embeds on every row -- not a
 * full `Job` (no priority/state/status/track_counts: those describe the *whole* job, and
 * this is one matching track's context, not a job-scoped fetch). `title` is the same
 * v18 derived display name as `Job.title`, added in v20 so the Tracks-scope view can
 * show a real album/playlist name instead of the raw URL without a per-job follow-up
 * request. */
export interface TrackJobSummary {
	id: string;
	source_url: string;
	source_type: JobSourceType;
	owner_email: string;
	owner_username: string | null;
	title: string;
}

export type TrackWithJob = Track & { job: TrackJobSummary };

export interface TrackStateEvent {
	type: 'track.state';
	track_id: string;
	job_id: string;
	state: TrackState;
	progress?: number;
	scheduled_at?: string;
	error?: string;
	attempt_count?: number;
	/** v23: present whenever the publishing call site has the track's song metadata to
	 * offer (effectively always, as of this version) -- absent only for events published
	 * before this field existed or a call site with none to give. See
	 * queue.ts's findCachedTrackMeta for the fallback that covers that gap. */
	title?: string | null;
	artists?: string[] | null;
	album?: string | null;
	ts: string;
}

export interface JobStateEvent {
	type: 'job.state';
	job_id: string;
	state: JobState;
	error?: string;
	/** v19: present (true/false) only on an archive/unarchive-triggered publish; absent
	 * for every other job.state event. */
	archived?: boolean;
	ts: string;
}

export type StreamEvent = TrackStateEvent | JobStateEvent;

export interface WorkerStatus {
	paused: boolean;
	breaker_tripped_until: string | null;
	breaker_trip_count: number;
	consecutive_failures: number;
	/** v20: true if *any* user's track is currently `downloading` -- global, not scoped
	 * to the caller (`worker-dl` runs `--concurrency=1`, so this is 0-or-1 tracks system
	 * -wide). Carries no id/title, only the boolean. */
	busy: boolean;
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
	/** Returned by the API for completeness but not rendered by the settings page at
	 * all -- fixed by the container's volume mount at deploy time (DOWNLOAD_OUTPUT_DIR),
	 * not editable at the app level, and confusing to even show as a field when nothing
	 * about it can change. Never sent by updateOutputSettings. */
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

/** v19: per-user log-retention preference (settings/retention), open to every user --
 * unlike OutputSettings, never admin-gated. `null` means "never auto-archive." */
export interface RetentionSettings {
	retention_days: number | null;
}

/** v17: every session carries the admin flag so the frontend can hide admin-only UI --
 * cosmetic only, the server-side `require_admin` gate is the real enforcement. */
export interface SessionInfo {
	email: string;
	/** v25: null until the first successful upstream `GET /user`. Display this, falling
	 * back to email -- see `displayName()`. */
	username: string | null;
	is_admin: boolean;
}

/** Shared display rule for username-or-email, everywhere either can appear (session
 * header, job/track owner columns) -- username when known, email otherwise. */
export function displayName(username: string | null, email: string): string {
	return username ?? email;
}

/** v18's shared paginated-listing envelope -- every cursor-paginated endpoint returns
 * exactly this shape (plus endpoint-specific extras, see JobsPage/JobTracksPage). */
export interface Page<T> {
	items: T[];
	next_cursor: string | null;
}

export interface JobsPage extends Page<Job> {
	/** Capped (see backend's pagination.CAP) -- "at least this many," not exact, past
	 * the cap. Good enough for "~3,000 tracks," never rendered as a precise count. */
	total_estimate: number;
	/** Grouped over the *pre-status-filter* result, so every status tab's count stays
	 * visible regardless of which one is currently selected. Keys are `statusKey()`
	 * tokens. */
	counts_by_status: Record<string, number>;
}

export type TracksPage = Page<TrackWithJob>;

export interface JobTracksPage extends Page<Track> {
	/** Ignores this request's own `state` filter (so switching tabs keeps every tab's
	 * count visible) -- the simple per-job breakdown, not q-aware. */
	counts_by_state: Record<string, number>;
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

/** Shared query-string builder for every v18 listing endpoint -- `undefined`/empty-array
 * values are omitted entirely (never sent as `key=`) so an unset filter is indistinguishable
 * from "not passed" server-side, and array values repeat the key (`status=a&status=b`),
 * matching FastAPI's `Query(default=[])` parsing convention, not a comma-joined string. */
function buildQuery(
	params: Record<string, string | number | boolean | string[] | undefined>
): string {
	const qs = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value === undefined) continue;
		if (Array.isArray(value)) {
			for (const v of value) qs.append(key, v);
		} else {
			qs.append(key, String(value));
		}
	}
	const s = qs.toString();
	return s ? `?${s}` : '';
}

export interface ListJobsParams {
	q?: string;
	status?: string[];
	sourceType?: JobSourceType;
	includeArchived?: boolean;
	sort?: string;
	dir?: 'asc' | 'desc';
	limit?: number;
	cursor?: string;
	allUsers?: boolean;
}

export interface ListTracksParams {
	q?: string;
	status?: string[];
	state?: string[];
	sourceType?: JobSourceType;
	includeArchived?: boolean;
	sort?: string;
	dir?: 'asc' | 'desc';
	limit?: number;
	cursor?: string;
	allUsers?: boolean;
}

function jobsQuery(params: ListJobsParams): string {
	return buildQuery({
		q: params.q || undefined,
		status: params.status,
		source_type: params.sourceType,
		include_archived: params.includeArchived || undefined,
		sort: params.sort,
		dir: params.dir,
		limit: params.limit,
		cursor: params.cursor,
		all_users: params.allUsers || undefined
	});
}

function tracksQuery(params: ListTracksParams): string {
	return buildQuery({
		q: params.q || undefined,
		status: params.status,
		state: params.state,
		source_type: params.sourceType,
		include_archived: params.includeArchived || undefined,
		sort: params.sort,
		dir: params.dir,
		limit: params.limit,
		cursor: params.cursor,
		all_users: params.allUsers || undefined
	});
}

export function login(email: string, password: string): Promise<SessionInfo> {
	return request('/api/auth/login', {
		method: 'POST',
		body: JSON.stringify({ email, password })
	});
}

export function me(): Promise<SessionInfo> {
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

export function listJobsPage(params: ListJobsParams = {}): Promise<JobsPage> {
	return request(`/api/jobs${jobsQuery(params)}`);
}

export function getJob(jobId: string): Promise<Job> {
	return request(`/api/jobs/${jobId}`);
}

export interface ListJobTracksParams {
	q?: string;
	state?: string[];
	sort?: string;
	dir?: 'asc' | 'desc';
	limit?: number;
	cursor?: string;
}

export function listJobTracksPage(
	jobId: string,
	params: ListJobTracksParams = {}
): Promise<JobTracksPage> {
	const qs = buildQuery({
		q: params.q || undefined,
		state: params.state,
		sort: params.sort,
		dir: params.dir,
		limit: params.limit,
		cursor: params.cursor
	});
	return request(`/api/jobs/${jobId}/tracks${qs}`);
}

/** The Tracks-scope listing -- search/filter/sort run over tracks, each with its parent
 * job embedded, one page at a time. Identical query to `GET /api/jobs?scope=track`; this
 * project's frontend always calls the dedicated `/api/tracks` URL (v18 left the choice of
 * URL to the frontend, see docs/GOTCHAS.md's v18 entry). */
export function listTracksPage(params: ListTracksParams = {}): Promise<TracksPage> {
	return request(`/api/tracks${tracksQuery(params)}`);
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

/** "Clear log": archives every eligible settled/failed/cancelled job for the caller with
 * no age restriction. Pass explicit `jobIds` instead for a single-job archive action. */
export function archiveJobs(opts: { jobIds?: string[]; allSettled?: boolean }): Promise<{
	archived_ids: string[];
}> {
	return request('/api/jobs/archive', {
		method: 'POST',
		body: JSON.stringify({ job_ids: opts.jobIds ?? null, all_settled: opts.allSettled ?? false })
	});
}

export function unarchiveJobs(jobIds: string[]): Promise<{ unarchived_ids: string[] }> {
	return request('/api/jobs/unarchive', {
		method: 'POST',
		body: JSON.stringify({ job_ids: jobIds })
	});
}

export function cancelTrack(trackId: string): Promise<Track> {
	return request(`/api/tracks/${trackId}`, { method: 'DELETE' });
}

export function retryTrack(trackId: string): Promise<Track & { breaker_held: boolean }> {
	return request(`/api/tracks/${trackId}/retry`, { method: 'POST' });
}

export function getTrackAttempts(trackId: string): Promise<TrackAttempt[]> {
	return request(`/api/tracks/${trackId}/attempts`);
}

/** `filename*=UTF-8''...` (RFC 5987) first, falling back to the plain quoted `filename=`
 * -- matches the two forms the backend's `_content_disposition` (tracks.py) can send. */
function parseContentDispositionFilename(header: string | null): string | null {
	if (!header) return null;
	const extended = header.match(/filename\*=UTF-8''([^;]+)/i);
	if (extended) {
		try {
			return decodeURIComponent(extended[1]);
		} catch {
			// Malformed percent-encoding -- fall through to the plain form below.
		}
	}
	const plain = header.match(/filename="([^"]*)"/);
	return plain ? plain[1] : null;
}

/** Fetches a completed track's audio file (v27) -- not routed through the shared
 * `request()` helper since a successful response here is a binary blob, not JSON. The
 * caller (TrackRow's handleDownload) turns the result into a real browser "Save As" via
 * an object URL, rather than a plain `<a href>` navigation, so a 404/error response
 * renders as this app's own notice UI instead of replacing the page with raw JSON. */
export async function downloadTrackFile(
	trackId: string
): Promise<{ blob: Blob; filename: string }> {
	const response = await fetch(`${API_BASE}/api/tracks/${trackId}/file`, {
		credentials: 'include'
	});

	if (!response.ok) {
		let detail = response.statusText;
		try {
			const body = await response.json();
			detail = body.detail ?? detail;
		} catch {
			// Non-JSON error body -- fall back to statusText.
		}
		throw new ApiError(response.status, detail);
	}

	const filename = parseContentDispositionFilename(response.headers.get('Content-Disposition'));
	const blob = await response.blob();
	return { blob, filename: filename ?? 'track' };
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

export function getRetentionSettings(): Promise<RetentionSettings> {
	return request('/api/settings/retention');
}

export function updateRetentionSettings(retentionDays: number | null): Promise<RetentionSettings> {
	return request('/api/settings/retention', {
		method: 'PATCH',
		body: JSON.stringify({ retention_days: retentionDays })
	});
}

/** `EventSource` needs `withCredentials: true` for the (now rare, see resolveApiBase)
 * case where `API_BASE` is a genuinely different absolute origin — a plain
 * `new EventSource(url)` defaults to omitting cookies there, which would silently 401
 * the stream. A harmless no-op for the same-origin default. */
export function createEventSource(allUsers = false): EventSource {
	return new EventSource(`${API_BASE}/api/stream${allUsers ? '?all_users=true' : ''}`, {
		withCredentials: true
	});
}
