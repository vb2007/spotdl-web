import { PUBLIC_API_BASE_URL } from '$env/static/public';
import { announceSession } from '$lib/session';

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
	/** The retry ladder's failure count (what picks the next delay and network rung) --
	 * not what the UI shows as attempts; see attempts_made/failure_count (v35). */
	attempt_count: number;
	/** v35: track_attempts rows that actually reached the network, and `failed` rows. */
	attempts_made: number;
	failure_count: number;
	scheduled_at: string | null;
	last_error: string | null;
	last_error_type: TrackErrorType | null;
	/** v62 (F10): which run of `downloading` this is (null otherwise); its `downloading` events
	 * carry the same value. Absent on rows from before v62. */
	download_started_at?: string | null;
}

export type TrackAttemptOutcome =
	| 'completed'
	| 'failed'
	| 'cancelled'
	| 'skipped_duplicate'
	/** v35: rescheduled behind the circuit breaker/pause without touching the network. */
	| 'held';

export type NetworkPath = 'direct-ipv4' | 'direct-ipv6' | 'proxy';

/** One row per `download_track` invocation (v24) -- `GET /api/tracks/{id}/attempts`,
 * oldest first. `proxy_id` is `null` for a direct attempt, `error_type`/`error_message`
 * are `null` for anything that isn't `failed` (a non-failure's note is `warning_message`).
 * Diagnostic only, not a headline feature -- see TrackRow.svelte's rendering. */
export interface TrackAttempt {
	id: string;
	attempt_number: number;
	started_at: string;
	finished_at: string;
	/** v35: `finished_at - started_at`. */
	duration_seconds: number;
	outcome: TrackAttemptOutcome;
	error_type: TrackErrorType | null;
	error_message: string | null;
	/** v35: a note on an attempt that didn't fail (a tag-repair note, a breaker hold).
	 * Never a failure; `error_message` is only ever one. */
	warning_message: string | null;
	proxy_id: string | null;
	/** v35: the proxy's redacted `scheme://host:port`, never its credentials. */
	proxy_label: string | null;
	/** v35: `null` when the row never reached the network (held, duplicate, cancelled
	 * before dispatch), and on rows written before v29 recorded it. */
	network_path: NetworkPath | null;
	/** v55 (E11): a `held` row stands for this many consecutive holds (1 otherwise). */
	hold_count?: number;
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
	/** v35: present whenever the worker just wrote an attempt row. */
	attempts_made?: number;
	failure_count?: number;
	/** v23: present whenever the publishing call site has the track's song metadata to
	 * offer (effectively always, as of this version) -- absent only for events published
	 * before this field existed or a call site with none to give. See
	 * queue.ts's findCachedTrackMeta for the fallback that covers that gap. */
	title?: string | null;
	artists?: string[] | null;
	album?: string | null;
	/** v62 (F10): on `downloading` events, the run they belong to (see `Track`). */
	download_started_at?: string;
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

/** v28: library sort & move progress -- published only to the triggering admin's own
 * per-user channel (there's exactly one sweep at a time, admin-only), so any session
 * subscribed to its own channel can render this the same way it renders track/job
 * events, without a separate connection. */
export interface LibraryProgressEvent {
	type: 'library.progress';
	processed: number;
	total: number;
	moved: number;
	skipped_present: number;
	quarantined: number;
	current_file?: string;
	done: boolean;
	ts: string;
}

/** v62 (F1): a job's rollup status moved (`statusKey()` form). Each event's `prev_status` is the
 * previous one's `status`; `null` means the job is new (counted under nothing before), and no
 * `prev_status` at all means the server doesn't know what it left. */
export interface JobStatusEvent {
	type: 'job.status';
	job_id: string;
	status: string;
	prev_status?: string | null;
	archived: boolean;
	ts: string;
}

export type StreamEvent = TrackStateEvent | JobStateEvent | JobStatusEvent | LibraryProgressEvent;

export interface WorkerStatus {
	paused: boolean;
	/** v56 (A7): the breaker's pause is running, decided on the server's clock. */
	breaker_active: boolean;
	/** v56 (A7): how long it runs yet, from the server (null when it isn't running). */
	breaker_remaining_seconds: number | null;
	/** v56 (A7): when it clears on *this* browser's clock: the time this answer arrived plus
	 * `breaker_remaining_seconds`, so a countdown is right however far this clock is off.
	 * Added here, not sent. Never compare `breaker_tripped_until` (the server's clock) with
	 * `Date.now()`: that is #63's skewed countdown. */
	breaker_clears_at: string | null;
	/** The server's own timestamp: identifies a trip (equality), never a clock reading. */
	breaker_tripped_until: string | null;
	/** v56 (A7): the server's clock when it answered (`serverToLocal` uses it). */
	server_time: string;
	breaker_trip_count: number;
	consecutive_failures: number;
	/** v20: true if *any* user's track is currently `downloading` -- global, not scoped
	 * to the caller (`worker-dl` runs `--concurrency=1`, so this is 0-or-1 tracks system
	 * -wide). Carries no id/title, only the boolean. */
	busy: boolean;
}

/** v44: GET /api/admin/stats. Global (every user's attempts together), admin-only; counts,
 * timestamps and redacted proxy labels only. */
export type StatsWindow = '24h' | '7d' | '30d';

export interface OutcomeCounts {
	/** Real network attempts (completed + failed + not_found). */
	attempts: number;
	completed: number;
	/** Failed with anything but "not found": the ladder retries these. */
	failed: number;
	/** Terminal "no match": about the track, not the route. */
	not_found: number;
	/** completed / (completed + failed); null with nothing to rate. */
	success_rate: number | null;
}

export interface PathStats extends OutcomeCounts {
	path: 'direct-ipv4' | 'direct-ipv6' | 'proxy' | 'unknown';
}

export interface ProxyStats extends OutcomeCounts {
	/** `host:port` (proxies.redact() minus its scheme): never credentials, never a URL. */
	label: string;
	enabled: boolean;
	last_success_at: string | null;
	/** Only a cooldown still running. */
	cooldown_until: string | null;
}

export interface BreakerEvent {
	kind: 'tripped' | 'escalated' | 'released';
	occurred_at: string;
	step_seconds: number | null;
	trip_count: number | null;
	paused_until: string | null;
	manual: boolean;
}

export interface AdminStats {
	window: StatsWindow;
	generated_at: string;
	window_start: string;
	utc_offset_minutes: number;
	bucket_seconds: number;
	network_paths: PathStats[];
	proxies: ProxyStats[];
	failures: {
		/** Each bucket's start; the last one is the current, partial bucket. */
		buckets: string[];
		series: { error_type: string; counts: number[]; total: number }[];
	};
	breaker: {
		current: { paused: boolean; holding_until: string | null; trip_count: number };
		events: BreakerEvent[];
		trips: number;
	};
	queue: {
		counts: { pending: number; queued: number; downloading: number; waiting: number };
		oldest_waiting_since: string | null;
		oldest_waiting_age_seconds: number | null;
	};
}

export type ProxySource = 'file' | 'manual';

export interface Proxy {
	id: string;
	/** scheme://host:port only -- the backend never returns a proxy's plaintext
	 * user:pass, matching the same redaction discipline applied to logs/last_error. */
	url: string;
	enabled: boolean;
	source: ProxySource;
	/** v56 (A4): deleted while a download was using it; never picked again, gone once that
	 * download ends. */
	deleting: boolean;
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

/** v28: admin-only library sort & move config -- target directory and folder template
 * for the real music library, plus the quarantine toggle/directory for a folder+filename
 * conflict. All four live on the same settings row as OutputSettings above. */
export interface LibrarySettings {
	library_target_dir: string;
	library_folder_template: string;
	library_quarantine_enabled: boolean;
	library_quarantine_dir: string;
}

export type EditableLibrarySettings = LibrarySettings;

/** v36: admin-only Matrix alert controls. `configured` says whether the three MATRIX_*
 * env vars are set -- the API never returns the credentials themselves. */
export interface AlertSettings {
	configured: boolean;
	alerts_breaker_enabled: boolean;
	alerts_spike_enabled: boolean;
	alerts_beat_stale_enabled: boolean;
	alerts_library_enabled: boolean;
	alerts_worker_down_enabled: boolean;
	alert_spike_threshold: number;
	alert_spike_window_minutes: number;
	alert_beat_stale_seconds: number;
	alert_worker_down_minutes: number;
	alert_cooldown_minutes: number;
}

export type EditableAlertSettings = Omit<AlertSettings, 'configured'>;

export type LibrarySortState = 'idle' | 'running';

/** v28: `GET /api/library/sort/status` -- the same row serves both live progress while
 * `state === 'running'` and the last finished sweep's report once it's idle again. */
export interface LibrarySortRun {
	state: LibrarySortState;
	started_at: string | null;
	finished_at: string | null;
	total: number;
	processed: number;
	moved: number;
	skipped_present: number;
	quarantined: number;
	errors: { file: string; error: string }[];
	/** v57 (L1): a cancel was asked for; the sweep stops at its next file boundary. */
	cancel_requested: boolean;
	/** v57 (L1): it stopped on that cancel: "cancelled after `processed` of `total`". */
	cancelled: boolean;
}

/** v17: every session carries the admin flag so the frontend can hide admin-only UI --
 * cosmetic only, the server-side `require_admin` gate is the real enforcement. */
export interface SessionInfo {
	email: string;
	/** v25: null until the first successful upstream `GET /user`. Display this, falling
	 * back to email -- see `displayName()`. */
	username: string | null;
	is_admin: boolean;
	/** v45: the per-user switch for single-key shortcuts. `me()` always carries it; the login
	 * response doesn't (the layout's `me()` runs next anyway). */
	keyboard_shortcuts?: boolean;
	/** v46: the saved interface language, `null` while the user has none (the browser's
	 * language decides). Like `keyboard_shortcuts`, only `me()` carries it. */
	language?: Language | null;
	/** v46: the pinned time format, `null` for automatic (the browser's region decides). */
	clock?: Clock | null;
}

/** v46: the interface languages there are message files for. */
export type Language = 'hu' | 'en';

/** v46: a time format the user can pin. */
export type Clock = '12h' | '24h';

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

export interface TracksPage extends Page<TrackWithJob> {
	/** v35 (g): one grouped count over the same owner-scoped, filtered set, before this
	 * request's own `state` filter (so every state chip keeps its count). Unlike
	 * JobTracksPage's, q-aware. */
	counts_by_state: Record<string, number>;
}

export interface JobTracksPage extends Page<Track> {
	/** Ignores this request's own `state` filter (so switching tabs keeps every tab's
	 * count visible) -- the simple per-job breakdown, not q-aware. */
	counts_by_state: Record<string, number>;
}

/** v46: `message` is the backend's English `detail` (or a status line); `code` is its stable
 * machine code, which the UI translates (`$lib/i18n/errors`), falling back to `message` for a
 * code it doesn't know. `params` carries the values a translation interpolates. */
export class ApiError extends Error {
	constructor(
		public status: number,
		message: string,
		public code: string | null = null,
		public params: Record<string, string | number> = {}
	) {
		super(message);
		this.name = 'ApiError';
	}
}

// v47: what a 401 from anything but signing in or out means: the session is gone. The layout
// registers the one handler (back to /login, saying why), so no page is left showing "Not
// authenticated" with a retry that can only fail again. `/api/auth/me` is left to its callers:
// the layout's own load already redirects on it.
const SESSION_PATHS = new Set(['/api/auth/login', '/api/auth/logout', '/api/auth/me']);
let unauthorizedHandler: (() => void) | null = null;
// v47: set while this tab signs out (until the next sign-in): a request answered 401 in that
// window is the sign-out itself, not a session that ended under the user.
let signingOut = false;
// Whether this tab's sign-out has been answered: only a /me sent after that can undo it.
let signedOut = false;

export function isSigningOut(): boolean {
	return signingOut;
}

/** Registers what a 401 does (the layout's session-ended path); returns the unregister. */
export function onUnauthorized(handler: () => void): () => void {
	unauthorizedHandler = handler;
	return () => {
		if (unauthorizedHandler === handler) unauthorizedHandler = null;
	};
}

/** v47: for a caller that learns of a 401 some other way (an `api.me()` it already catches). */
export function sessionEnded(): void {
	unauthorizedHandler?.();
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
		let code: string | null = null;
		let params: Record<string, string | number> = {};
		try {
			const body = await response.json();
			// A validation error's `detail` is a list, not a sentence: keep the status line
			// and let the code-less fallback in `$lib/i18n/errors` speak for it.
			if (typeof body.detail === 'string') detail = body.detail;
			else if (body.detail != null) code = 'request_invalid';
			if (typeof body.code === 'string') code = body.code;
			if (body.params && typeof body.params === 'object') params = body.params;
		} catch {
			// Non-JSON error body — fall back to statusText. v46: a response like that (the proxy
			// answering for a restarting `api`, an unhandled exception's plain-text 500, or a page
			// from in front of the app such as a 429) gets a code, so the UI says so in the active
			// language around the same status line.
			code = response.status >= 500 ? 'server_error' : 'request_failed';
			// v47: the number, never the statusText ("Bad Gateway" is English inside a
			// Hungarian sentence).
			params = { status: String(response.status) };
		}
		if (response.status === 401 && !signingOut && !SESSION_PATHS.has(path.split('?')[0]))
			unauthorizedHandler?.();
		throw new ApiError(response.status, detail, code, params);
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

/** v54: the admin's list scope -- the viewer's own, everyone's, or everyone's but the viewer's.
 * The server normalizes a non-admin to `mine` whatever is sent. */
export type View = 'mine' | 'all' | 'others';

export interface ListJobsParams {
	q?: string;
	status?: string[];
	sourceType?: JobSourceType;
	includeArchived?: boolean;
	sort?: string;
	dir?: 'asc' | 'desc';
	limit?: number;
	cursor?: string;
	/** Omitted (and not sent) for `mine`, the server's default. */
	view?: View;
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
	/** Omitted (and not sent) for `mine`, the server's default. */
	view?: View;
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
		view: params.view === 'mine' ? undefined : params.view
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
		view: params.view === 'mine' ? undefined : params.view
	});
}

export async function login(email: string, password: string): Promise<SessionInfo> {
	const session = await request<SessionInfo>('/api/auth/login', {
		method: 'POST',
		body: JSON.stringify({ email, password })
	});
	signingOut = false;
	signedOut = false;
	// v62 (F9): the other tabs follow at once (session.ts).
	announceSession({ type: 'login', email: session.email });
	return session;
}

export async function me(): Promise<SessionInfo> {
	const afterSignOut = signedOut;
	const session = await request<SessionInfo>('/api/auth/me');
	// v47: a live session read after this tab's sign-out finished (a sign-in in another tab,
	// then Back) means a later 401 is a session ending again. One sent before it finished
	// says nothing about the sign-out, so it leaves the latch alone.
	if (afterSignOut) {
		signingOut = false;
		signedOut = false;
	}
	return session;
}

export async function logout(): Promise<{ status: string }> {
	signingOut = true;
	try {
		const answer = await request<{ status: string }>('/api/auth/logout', { method: 'POST' });
		signedOut = true;
		announceSession({ type: 'logout' });
		return answer;
	} catch (err) {
		// A 401: there was no session left to end, so this tab is signed out all the same.
		if (err instanceof ApiError && err.status === 401) {
			signedOut = true;
			announceSession({ type: 'logout' });
			return { status: 'ok' };
		}
		// Still signed in: a later 401 means what it says again.
		signingOut = false;
		throw err;
	}
}

/** v53: `hint` -- `already_queued` answers 200 with the caller's own unfinished job for the
 * same link (nothing new was created), `in_library` a track the ledger already has. */
export type CreateJobHint = 'already_queued' | 'in_library' | null;

export function createJob(url: string): Promise<Job & { hint?: CreateJobHint }> {
	return request('/api/jobs', {
		method: 'POST',
		body: JSON.stringify({ url })
	});
}

/** v53: a per-user API key, the browser extension's fallback when the session cookie doesn't
 * reach the API. Only `prefix` is ever shown again; the whole key exists once, in `create`'s
 * answer. */
export interface ApiKey {
	id: string;
	label: string;
	prefix: string;
	created_at: string;
	last_used_at: string | null;
}

export interface ApiKeyList {
	keys: ApiKey[];
	max_active: number;
}

export function listApiKeys(): Promise<ApiKeyList> {
	return request('/api/account/api-keys');
}

export function createApiKey(label: string): Promise<ApiKey & { key: string }> {
	return request('/api/account/api-keys', {
		method: 'POST',
		body: JSON.stringify({ label })
	});
}

export function revokeApiKey(keyId: string): Promise<ApiKey> {
	return request(`/api/account/api-keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' });
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

/** v56 (A3): one track as the server has it now (owner or admin; anyone else a 404). */
export function getTrack(trackId: string): Promise<TrackWithJob> {
	return request(`/api/tracks/${trackId}`);
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

/** A completed track's audio file URL (v27). v35 (e): handed to a real browser download
 * (TrackRow's handleDownload) so the bytes stream straight to disk, never through tab
 * memory, and nginx's X-Accel-Redirect streaming is kept end to end. */
export function trackFileUrl(trackId: string): string {
	return `${API_BASE}/api/tracks/${trackId}/file`;
}

/** v35 (e): a HEAD probe before the real download. A plain navigation to a 404 would
 * replace the page with raw JSON, so the error surface lives here: a missing ledger row
 * 404s in FastAPI, and a file deleted from disk 404s once nginx (or the Vite dev
 * fallback, vite.config.ts) follows the X-Accel-Redirect, which it does for HEAD too.
 * HEAD has no body, so the message comes from the status alone. */
export async function checkTrackFile(trackId: string): Promise<void> {
	const response = await fetch(trackFileUrl(trackId), {
		method: 'HEAD',
		credentials: 'include'
	});

	if (!response.ok) {
		// v47: an expired session is the session ending, the same as any other request's 401.
		if (response.status === 401 && !signingOut) unauthorizedHandler?.();
		// HEAD has no body, so no backend code either: the status picks one. An expired session
		// says so (as any other request's 401 would); anything else keeps its status line as the
		// `detail` a code-less fallback would show.
		const code =
			response.status === 404
				? 'file_not_found'
				: response.status === 401
					? 'not_authenticated'
					: 'download_failed';
		throw new ApiError(
			response.status,
			// i18n-ignore: the English `detail` behind the code, as the backend's would be.
			response.status === 404 ? 'File not found' : response.statusText || 'Download failed',
			code,
			// v47: the number, as request() does: never English statusText in a Hungarian line.
			{ status: String(response.status) }
		);
	}

	// v27's backstop, kept: FastAPI's own response is headers-only, so a proxy that
	// doesn't follow X-Accel-Redirect would otherwise report a 0-byte "success".
	if (response.headers.get('Content-Length') === '0') {
		throw new ApiError(
			502,
			// i18n-ignore: the English `detail` behind the code, as the backend's would be.
			'Downloaded file was empty -- the download did not complete.',
			'file_empty'
		);
	}
}

// --- v64: job export ---------------------------------------------------------------

/** v64: a job's present files as one zip, streamed (STORED, with a Content-Length, so the
 * browser shows real progress). Handed to a real browser download, as trackFileUrl is. */
export function jobExportUrl(jobId: string): string {
	return `${API_BASE}/api/jobs/${jobId}/export.zip`;
}

/** v64: the same tracks as an extended M3U, relative to the zip's layout. */
export function jobPlaylistUrl(jobId: string): string {
	return `${API_BASE}/api/jobs/${jobId}/playlist.m3u8`;
}

/** v64: v35 (e)'s probe, for an export URL above: a HEAD (the zip's with its limits), so a
 * 404 or an over-the-limit 413 shows in the row's notice instead of the page navigating to
 * JSON. HEAD has no body, so the status picks the code, as checkTrackFile's does. */
export async function checkJobExport(url: string): Promise<void> {
	const response = await fetch(url, { method: 'HEAD', credentials: 'include' });
	if (response.ok) return;
	if (response.status === 401 && !signingOut) unauthorizedHandler?.();
	const code =
		response.status === 413
			? 'export_too_large'
			: response.status === 404
				? 'job_not_found'
				: response.status === 401
					? 'not_authenticated'
					: 'download_failed';
	throw new ApiError(
		response.status,
		// i18n-ignore: the English `detail` behind the code, as the backend's would be.
		response.statusText || 'Export failed',
		code,
		{ status: String(response.status) }
	);
}

/** v64: how many of a job's tracks have a file on disk, out of how many: the zip's own
 * counts, from its HEAD (one request when a job is opened, never one per row). `null` when
 * the job can't be read (gone, or the session ended: the probe on download says why). */
export async function getJobExportCounts(
	jobId: string
): Promise<{ files: number; tracks: number } | null> {
	const response = await fetch(jobExportUrl(jobId), { method: 'HEAD', credentials: 'include' });
	// 413 (over the limit) still carries the counts: the playlist stays offered.
	if (!response.ok && response.status !== 413) return null;
	const files = Number(response.headers.get('X-Export-Files'));
	const tracks = Number(response.headers.get('X-Export-Tracks'));
	return Number.isFinite(files) && Number.isFinite(tracks) ? { files, tracks } : null;
}

/** v64: the export's limits; each `null` is "the env default" (`default_*`). Admin only. */
export interface ExportSettings {
	export_max_files: number | null;
	export_max_gb: number | null;
	default_max_files: number;
	default_max_gb: number;
}

export type EditableExportSettings = Pick<ExportSettings, 'export_max_files' | 'export_max_gb'>;

export function getExportSettings(): Promise<ExportSettings> {
	return request('/api/settings/export');
}

export function updateExportSettings(
	patch: Partial<EditableExportSettings>
): Promise<ExportSettings> {
	return request('/api/settings/export', { method: 'PATCH', body: JSON.stringify(patch) });
}

// --- end v64 ------------------------------------------------------------------------

// v56 (A7): every worker answer gets `breaker_clears_at` on arrival (see WorkerStatus). One
// trip keeps one deadline while each answer agrees with it to within 2s: recomputed from every
// 5s poll, network jitter could move it across a minute and make the pill's live region (which
// names the clock time) speak again. Global worker state, the same for every user.
let lastClear: { trip: string; at: number } | null = null;
// v56 (A7): how far the server's clock is ahead of this browser's, from the last worker answer
// (every page polls it). 0 until one arrives.
let serverAheadMs = 0;

/** A timestamp of the server's (a track's `scheduled_at`), placed on this browser's clock, so a
 * countdown to it is right however far this clock is off (#63). */
export function serverToLocal(iso: string): string {
	return new Date(Date.parse(iso) - serverAheadMs).toISOString();
}

async function workerAnswer(path: string, init?: RequestInit): Promise<WorkerStatus> {
	const status: Omit<WorkerStatus, 'breaker_clears_at'> = await request(path, init);
	serverAheadMs = Date.parse(status.server_time) - Date.now();
	const remaining = status.breaker_active ? status.breaker_remaining_seconds : null;
	const trip = status.breaker_tripped_until;
	if (remaining === null || trip === null) {
		lastClear = null;
		return { ...status, breaker_clears_at: null };
	}
	const at = Date.now() + remaining * 1000;
	if (!lastClear || lastClear.trip !== trip || Math.abs(lastClear.at - at) > 2000) {
		lastClear = { trip, at };
	}
	return { ...status, breaker_clears_at: new Date(lastClear.at).toISOString() };
}

export function workerStatus(): Promise<WorkerStatus> {
	return workerAnswer('/api/worker/status');
}

export function pauseWorker(): Promise<WorkerStatus> {
	return workerAnswer('/api/worker/pause', { method: 'POST' });
}

export function resumeWorker(): Promise<WorkerStatus> {
	return workerAnswer('/api/worker/resume', { method: 'POST' });
}

export function releaseBreaker(): Promise<WorkerStatus> {
	return workerAnswer('/api/worker/breaker/release', { method: 'POST' });
}

export function getAdminStats(window: StatsWindow): Promise<AdminStats> {
	// The viewer's own clock, so a day bucket is their day (owner's choice, v44).
	const offset = -new Date().getTimezoneOffset();
	return request<AdminStats>(`/api/admin/stats?window=${window}&utc_offset_minutes=${offset}`);
}

export type AlertCategory = 'breaker' | 'spike' | 'beat_stale' | 'worker_down' | 'library' | 'test';
export type AlertState = 'pending' | 'sent' | 'failed' | 'suppressed';

/** v59: one alert outbox row. `body_preview` is stored redacted and capped server-side;
 * `last_error` is the last failed send's reason, or why it was suppressed (untranslated). */
export interface AlertHistoryItem {
	id: string;
	created_at: string;
	category: AlertCategory | string;
	state: AlertState;
	attempts: number;
	next_attempt_at: string | null;
	sent_at: string | null;
	last_error: string | null;
	body_preview: string;
}

export interface AlertHistoryPage {
	configured: boolean;
	items: AlertHistoryItem[];
	next_cursor: string | null;
}

/** v59 (O6): admin-only, newest first, one cursor page per request. */
export function getAlertHistory(
	cursor: string | null = null,
	limit = 25
): Promise<AlertHistoryPage> {
	const params = new URLSearchParams({ limit: String(limit) });
	if (cursor !== null) params.set('cursor', cursor);
	return request<AlertHistoryPage>(`/api/admin/alerts?${params}`);
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

/** A manual proxy is hard-deleted (204, no body: `undefined` back means "the row is really
 * gone"), or, while a download is using it, marked `deleting` (202, the row; v56, A4); a
 * file-sourced proxy is only soft-disabled (200, the updated row) -- see the backend's own
 * docstring for why. */
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

export interface KeyboardSettings {
	keyboard_shortcuts: boolean;
}

/** v45: the per-user shortcut switch (WCAG 2.1.4), open to every user like retention. The
 * app reads it from `me()`; `GET /api/settings/keyboard` exists for completeness. */
export function updateKeyboardSettings(enabled: boolean): Promise<KeyboardSettings> {
	return request('/api/settings/keyboard', {
		method: 'PATCH',
		body: JSON.stringify({ keyboard_shortcuts: enabled })
	});
}

export function updateRetentionSettings(retentionDays: number | null): Promise<RetentionSettings> {
	return request('/api/settings/retention', {
		method: 'PATCH',
		body: JSON.stringify({ retention_days: retentionDays })
	});
}

export function getLibrarySettings(): Promise<LibrarySettings> {
	return request('/api/settings/library');
}

export function updateLibrarySettings(
	patch: Partial<EditableLibrarySettings>
): Promise<LibrarySettings> {
	return request('/api/settings/library', {
		method: 'PATCH',
		body: JSON.stringify(patch)
	});
}

export function getAlertSettings(): Promise<AlertSettings> {
	return request('/api/settings/alerts');
}

export function updateAlertSettings(patch: Partial<EditableAlertSettings>): Promise<AlertSettings> {
	return request('/api/settings/alerts', {
		method: 'PATCH',
		body: JSON.stringify(patch)
	});
}

export function sendTestAlert(): Promise<{ sent: boolean }> {
	return request('/api/settings/alerts/test', { method: 'POST' });
}

export function getLibrarySortStatus(): Promise<LibrarySortRun> {
	return request('/api/library/sort/status');
}

export function startLibrarySort(): Promise<LibrarySortRun> {
	return request('/api/library/sort', { method: 'POST' });
}

/** v57 (L1): asks the running sweep to stop between files (409 when none runs). */
export function cancelLibrarySort(): Promise<LibrarySortRun> {
	return request('/api/library/sort/cancel', { method: 'POST' });
}

/** `EventSource` needs `withCredentials: true` for the (now rare, see resolveApiBase)
 * case where `API_BASE` is a genuinely different absolute origin — a plain
 * `new EventSource(url)` defaults to omitting cookies there, which would silently 401
 * the stream. A harmless no-op for the same-origin default. */
export function createEventSource(view: View = 'mine'): EventSource {
	return new EventSource(`${API_BASE}/api/stream${view === 'mine' ? '' : `?view=${view}`}`, {
		withCredentials: true
	});
}

export interface LanguageSettings {
	language: Language | null;
}

/** v46: the per-user interface language, open to every user like the shortcut switch. Stored
 * server-side so it follows the user to every device; `me()` carries the same value. `null`
 * puts it back to automatic (the browser's language). */
export function updateLanguageSettings(language: Language | null): Promise<LanguageSettings> {
	return request('/api/settings/language', {
		method: 'PATCH',
		body: JSON.stringify({ language })
	});
}

export interface ClockSettings {
	clock: Clock | null;
}

/** v46: the per-user time format; `null` puts it back to automatic (the browser's region). */
export function updateClockSettings(clock: Clock | null): Promise<ClockSettings> {
	return request('/api/settings/clock', {
		method: 'PATCH',
		body: JSON.stringify({ clock })
	});
}
