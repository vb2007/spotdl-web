import { derived, get, writable } from 'svelte/store';
import * as api from '$lib/api';
import type {
	Job,
	JobsPage,
	JobTracksPage,
	StreamEvent,
	Track,
	TrackJobSummary,
	TrackState,
	TrackWithJob
} from '$lib/api';

/** States nothing in this app ever transitions a track *out of* -- `waiting`/
 * `lookup_failed` don't qualify since retry-now can revive them back to `waiting`. A
 * track's own real (uninterruptible) download can keep publishing stray `downloading`
 * progress events for several seconds after a cancel has already landed (spotdl's
 * progress callback has no idea a cancel happened -- see CLAUDE.md's v10 gotchas); once
 * a track is known to be in one of these states, any further event for it is necessarily
 * stale and must be ignored, not applied. */
const TRULY_TERMINAL_STATES = new Set<TrackState>(['completed', 'skipped_duplicate', 'cancelled']);

export type LiveTrack = Track & { progress?: number };
export type LiveTrackWithJob = TrackWithJob & { progress?: number };

export type Scope = 'jobs' | 'tracks';

export interface Filters {
	scope: Scope;
	q: string;
	/** Job rollup-status tokens (`statusKey()` form) -- meaningful only in `scope: 'jobs'`. */
	status: string[];
	/** Track-state tokens -- meaningful only in `scope: 'tracks'`. */
	state: string[];
	includeArchived: boolean;
	sort: string;
	dir: 'asc' | 'desc';
}

const DEFAULT_FILTERS: Filters = {
	scope: 'jobs',
	q: '',
	status: [],
	state: [],
	includeArchived: false,
	sort: 'created_at',
	dir: 'desc'
};

export type PageItem = Job | LiveTrackWithJob;

export function isTrackItem(item: PageItem): item is LiveTrackWithJob {
	return 'job' in item;
}

interface PageState {
	items: PageItem[];
	nextCursor: string | null;
	totalEstimate: number;
	countsByStatus: Record<string, number>;
	loading: boolean;
	loadingMore: boolean;
	error: string;
}

const EMPTY_PAGE: PageState = {
	items: [],
	nextCursor: null,
	totalEstimate: 0,
	countsByStatus: {},
	loading: false,
	loadingMore: false,
	error: ''
};

export interface ExpandedJob {
	items: LiveTrack[];
	nextCursor: string | null;
	countsByState: Record<string, number>;
	loading: boolean;
	loadingMore: boolean;
	error: string;
}

function newExpandedJob(): ExpandedJob {
	return {
		items: [],
		nextCursor: null,
		countsByState: {},
		loading: false,
		loadingMore: false,
		error: ''
	};
}

/** Groups a flat Tracks-scope page into per-job sections in the order each job's first
 * matching track appears, preserving the server's own ordering within and across groups
 * -- the "Tracks scope auto-expands matching jobs" view (v20 plan). Pure/derivable, not
 * store state, so it's exposed as a plain function rather than another writable. */
export function groupTracksByJob(
	items: LiveTrackWithJob[]
): { job: TrackJobSummary; tracks: LiveTrackWithJob[] }[] {
	const order: string[] = [];
	const groups: Record<string, { job: TrackJobSummary; tracks: LiveTrackWithJob[] }> = {};
	for (const item of items) {
		if (!groups[item.job.id]) {
			groups[item.job.id] = { job: item.job, tracks: [] };
			order.push(item.job.id);
		}
		groups[item.job.id].tracks.push(item);
	}
	return order.map((id) => groups[id]);
}

function createQueueStore() {
	const filters = writable<Filters>({ ...DEFAULT_FILTERS });
	const page = writable<PageState>({ ...EMPTY_PAGE });
	const expanded = writable<Record<string, ExpandedJob>>({});

	/** SSE-fed only, never REST-loaded -- Waterfall's "what's downloading right now" view.
	 * `worker-dl` runs `--concurrency=1` (CLAUDE.md invariant), so this can never hold more
	 * than one entry for a non-admin session; an admin's all-users pattern-subscribe sees
	 * the same single global slot, not one per user. Because it can never exceed one entry,
	 * there is no meaningful order to preserve and therefore nothing for an `updatedAt`
	 * tiebreaker to do -- unlike the retired QueueTable, nothing here ever re-sorts a live
	 * -patched row (every row below patches in place inside a server-ordered page), so the
	 * v09 "completed track visibly jumps/vanishes" failure mode has no client sort left to
	 * reintroduce it. */
	const liveActive = writable<Record<string, LiveTrack>>({});

	/** A job between "submitted" and "its tracks exist" (or one whose expansion failed
	 * with zero tracks) has nothing else in the UI to represent it -- same v09 rationale as
	 * before, just fed by push (SSE + the optimistic post-submit insert) instead of derived
	 * from a full local mirror. */
	const incoming = writable<Record<string, Job>>({});

	let allUsers = false;
	let pageFetchSeq = 0;
	const expandedFetchSeq: Record<string, number> = {};

	// Coarse-vs-fine event filtering: a `downloading` track can publish many same-state
	// progress-percent ticks per second. Refreshing a job row's aggregate counts/rollup on
	// every tick would hammer the API for no visible benefit (the row already shows
	// "active" throughout); only an actual state *change* warrants re-fetching the row.
	const lastKnownTrackState: Record<string, TrackState> = {};
	const pendingJobRefresh = new Set<string>();
	let jobRefreshTimer: ReturnType<typeof setTimeout> | undefined;

	function scheduleJobRefresh(jobId: string): void {
		pendingJobRefresh.add(jobId);
		clearTimeout(jobRefreshTimer);
		jobRefreshTimer = setTimeout(flushJobRefreshes, 400);
	}

	/** v23: root-caused the Waterfall's appear/disappear/reappear glitch by raw-`curl -N`
	 * capturing a real failing-then-retrying track -- `downloading` to `waiting` landed
	 * under a second apart, then the identical cycle repeated every ~30s (beat's own
	 * dispatch-tick interval -- app/tasks/celery_app.py's `dispatch-due-tracks` schedule)
	 * for as long as the track kept failing fast (docs/GOTCHAS.md's v23 entry has the
	 * full capture, including confirming a short first cut of this fix at 4s wasn't
	 * enough to bridge that real gap). `liveActive`'s add-on-`downloading`/remove-on-
	 * anything-else rule is otherwise correct -- the fix is to debounce the *removal* the
	 * same way scheduleJobRefresh above debounces job-row refreshes: a track leaving
	 * `downloading` stays in `liveActive` (updated in place) for this grace window, and
	 * only actually drops out if no further `downloading` event arrives before the timer
	 * fires. 60s covers the worst case of beat's own 30s tick landing just after a track
	 * becomes due (up to another 30s of pure dispatch latency) -- the realistic minimum
	 * gap between two attempts, e.g. a user clicking "retry now" right after a fast
	 * failure -- while staying a tiny fraction of the real retry ladder's 15-minute
	 * floor, so a genuine multi-minute-or-longer wait still correctly reads as "not
	 * active" almost immediately rather than being misrepresented for its whole
	 * duration. */
	const LIVE_REMOVAL_GRACE_MS = 60000;
	const liveRemovalTimers: Record<string, ReturnType<typeof setTimeout>> = {};

	function clearLiveRemovalTimer(trackId: string): void {
		clearTimeout(liveRemovalTimers[trackId]);
		delete liveRemovalTimers[trackId];
	}

	function scheduleLiveRemoval(trackId: string): void {
		clearLiveRemovalTimer(trackId);
		liveRemovalTimers[trackId] = setTimeout(() => {
			delete liveRemovalTimers[trackId];
			liveActive.update((current) => {
				if (!(trackId in current)) return current;
				const { [trackId]: _drop, ...rest } = current;
				return rest;
			});
		}, LIVE_REMOVAL_GRACE_MS);
	}

	/** Every direct `liveActive.set({})` (a scope switch, a reset) must also cancel any
	 * pending grace-window timers above -- otherwise one fires later against whatever
	 * identity/scope is current by then. Harmless in practice (the timer's own
	 * `trackId in current` guard no-ops against an unrelated store), but a leaked timer
	 * outliving the state it was scheduled for is exactly the kind of thing the v22
	 * store-reset gotcha exists to catch on sight, not just when it happens to matter. */
	function clearAllLiveRemovalTimers(): void {
		for (const trackId of Object.keys(liveRemovalTimers)) clearLiveRemovalTimer(trackId);
	}

	async function flushJobRefreshes(): Promise<void> {
		const ids = [...pendingJobRefresh];
		pendingJobRefresh.clear();
		await Promise.all(ids.map(refreshJobRow));
	}

	/** Single-row refresh, the same pattern every mutating action below already uses
	 * (cancelJob/bumpJob/etc. all patch in exactly one row from their own response) --
	 * not the "per-job request loop" the project's invariant warns against, since this is
	 * one row reacting to one real event, never a loop issued while rendering a listing. */
	async function refreshJobRow(jobId: string): Promise<void> {
		let job: Job;
		try {
			job = await api.getJob(jobId);
		} catch {
			// 404 (deleted, or this session lost visibility) -- drop it from view.
			page.update((p) => ({ ...p, items: p.items.filter((i) => i.id !== jobId) }));
			return;
		}
		page.update((p) => {
			if (get(filters).scope !== 'jobs') return p;
			const idx = p.items.findIndex((i) => i.id === jobId);
			if (idx === -1) return p;
			const items = [...p.items];
			items[idx] = job;
			return { ...p, items };
		});
	}

	function currentQueryParams() {
		const f = get(filters);
		return {
			q: f.q || undefined,
			includeArchived: f.includeArchived,
			sort: f.sort,
			dir: f.dir,
			allUsers
		};
	}

	async function reload(): Promise<void> {
		const f = get(filters);
		const seq = ++pageFetchSeq;
		page.update((p) => ({ ...p, loading: true, error: '' }));
		try {
			if (f.scope === 'jobs') {
				const result: JobsPage = await api.listJobsPage({
					...currentQueryParams(),
					status: f.status.length ? f.status : undefined
				});
				if (seq !== pageFetchSeq) return;
				page.set({
					items: result.items,
					nextCursor: result.next_cursor,
					totalEstimate: result.total_estimate,
					countsByStatus: result.counts_by_status,
					loading: false,
					loadingMore: false,
					error: ''
				});
			} else {
				const result = await api.listTracksPage({
					...currentQueryParams(),
					status: f.status.length ? f.status : undefined,
					state: f.state.length ? f.state : undefined
				});
				if (seq !== pageFetchSeq) return;
				page.set({
					items: result.items,
					nextCursor: result.next_cursor,
					totalEstimate: 0,
					countsByStatus: {},
					loading: false,
					loadingMore: false,
					error: ''
				});
			}
		} catch (err) {
			if (seq !== pageFetchSeq) return;
			page.update((p) => ({
				...p,
				loading: false,
				error: err instanceof api.ApiError ? err.message : 'Could not reach the server.'
			}));
		}
	}

	async function loadMore(): Promise<void> {
		const current = get(page);
		if (current.nextCursor === null || current.loadingMore) return;
		const f = get(filters);
		const seq = pageFetchSeq;
		page.update((p) => ({ ...p, loadingMore: true }));
		try {
			if (f.scope === 'jobs') {
				const result: JobsPage = await api.listJobsPage({
					...currentQueryParams(),
					status: f.status.length ? f.status : undefined,
					cursor: current.nextCursor
				});
				if (seq !== pageFetchSeq) return;
				page.update((p) => ({
					...p,
					items: [...p.items, ...result.items],
					nextCursor: result.next_cursor,
					totalEstimate: result.total_estimate,
					countsByStatus: result.counts_by_status,
					loadingMore: false
				}));
			} else {
				const result = await api.listTracksPage({
					...currentQueryParams(),
					status: f.status.length ? f.status : undefined,
					state: f.state.length ? f.state : undefined,
					cursor: current.nextCursor
				});
				if (seq !== pageFetchSeq) return;
				page.update((p) => ({
					...p,
					items: [...p.items, ...result.items],
					nextCursor: result.next_cursor,
					loadingMore: false
				}));
			}
		} catch (err) {
			if (seq !== pageFetchSeq) return;
			page.update((p) => ({
				...p,
				loadingMore: false,
				error: err instanceof api.ApiError ? err.message : 'Could not reach the server.'
			}));
		}
	}

	/** Merges a filter patch and reloads -- the sole entry point QueueControls uses, so a
	 * scope switch resets the axis (status/state) that means nothing in the new scope
	 * rather than silently carrying over a token the other scope's endpoint would 400 on. */
	function setFilters(patch: Partial<Filters>): void {
		filters.update((f) => {
			const next = { ...f, ...patch };
			if (patch.scope !== undefined && patch.scope !== f.scope) {
				next.status = [];
				next.state = [];
				next.sort = 'created_at';
				next.dir = 'desc';
			}
			return next;
		});
		reload();
	}

	/** Bumps a job's expanded-fetch sequence without starting a new fetch -- makes any
	 * already-in-flight `loadExpandedTracks`/`loadMoreExpandedTracks` call for this job a
	 * guaranteed no-op on resolve. Collapsing a row (or clearing the whole map on a scope
	 * switch) must call this, or a slow/stale response for a job the user already closed
	 * can land afterward and silently re-open it. */
	function invalidateExpandedFetch(jobId: string): void {
		expandedFetchSeq[jobId] = (expandedFetchSeq[jobId] ?? 0) + 1;
	}

	function setAllUsers(value: boolean): void {
		allUsers = value;
		for (const jobId of Object.keys(expandedFetchSeq)) invalidateExpandedFetch(jobId);
		expanded.set({});
		incoming.set({});
		clearAllLiveRemovalTimers();
		liveActive.set({});
		reload();
	}

	function getAllUsers(): boolean {
		return allUsers;
	}

	/** Wipes every accumulated row back to empty and invalidates any in-flight fetch, so a
	 * stale response landing after a logout can never repopulate the store. `queue` is a
	 * module-level singleton (survives SvelteKit's client-side `goto` navigation, which
	 * never reloads the page) -- without this, a same-tab logout(A) -> login(B) leaves A's
	 * jobs/tracks sitting in `page`/`expanded`/`liveActive`/`incoming` until B's own
	 * post-mount `reload()` resolves and replaces them, a real window where B's freshly
	 * mounted dashboard renders A's rows. Call this on logout, before the next identity's
	 * session can start writing to these stores. */
	function reset(): void {
		pageFetchSeq++;
		for (const jobId of Object.keys(expandedFetchSeq)) invalidateExpandedFetch(jobId);
		allUsers = false;
		filters.set({ ...DEFAULT_FILTERS });
		page.set({ ...EMPTY_PAGE });
		expanded.set({});
		incoming.set({});
		clearAllLiveRemovalTimers();
		liveActive.set({});
	}

	function toggleExpand(jobId: string): void {
		const current = get(expanded);
		if (current[jobId]) {
			invalidateExpandedFetch(jobId);
			const { [jobId]: _drop, ...rest } = current;
			expanded.set(rest);
			return;
		}
		expanded.update((e) => ({ ...e, [jobId]: newExpandedJob() }));
		loadExpandedTracks(jobId);
	}

	function isExpanded(jobId: string): boolean {
		return jobId in get(expanded);
	}

	async function loadExpandedTracks(jobId: string): Promise<void> {
		const seq = (expandedFetchSeq[jobId] ?? 0) + 1;
		expandedFetchSeq[jobId] = seq;
		expanded.update((e) => ({
			...e,
			[jobId]: { ...(e[jobId] ?? newExpandedJob()), loading: true, error: '' }
		}));
		try {
			const result: JobTracksPage = await api.listJobTracksPage(jobId);
			if (expandedFetchSeq[jobId] !== seq) return;
			expanded.update((e) => ({
				...e,
				[jobId]: {
					items: result.items,
					nextCursor: result.next_cursor,
					countsByState: result.counts_by_state,
					loading: false,
					loadingMore: false,
					error: ''
				}
			}));
		} catch (err) {
			if (expandedFetchSeq[jobId] !== seq) return;
			expanded.update((e) => ({
				...e,
				[jobId]: {
					...(e[jobId] ?? newExpandedJob()),
					loading: false,
					error: err instanceof api.ApiError ? err.message : 'Could not reach the server.'
				}
			}));
		}
	}

	async function loadMoreExpandedTracks(jobId: string): Promise<void> {
		const current = get(expanded)[jobId];
		if (!current || current.nextCursor === null || current.loadingMore) return;
		const seq = expandedFetchSeq[jobId];
		expanded.update((e) => ({ ...e, [jobId]: { ...e[jobId], loadingMore: true } }));
		try {
			const result: JobTracksPage = await api.listJobTracksPage(jobId, {
				cursor: current.nextCursor
			});
			if (expandedFetchSeq[jobId] !== seq) return;
			expanded.update((e) => ({
				...e,
				[jobId]: {
					...e[jobId],
					items: [...e[jobId].items, ...result.items],
					nextCursor: result.next_cursor,
					countsByState: result.counts_by_state,
					loadingMore: false
				}
			}));
		} catch (err) {
			if (expandedFetchSeq[jobId] !== seq) return;
			expanded.update((e) => ({
				...e,
				[jobId]: {
					...e[jobId],
					loadingMore: false,
					error: err instanceof api.ApiError ? err.message : 'Could not reach the server.'
				}
			}));
		}
	}

	/** Optimistic insert right after a successful `POST /api/jobs`, so the new job is
	 * visible immediately rather than waiting for its own `expanding` SSE echo. Only ever
	 * needs the incoming overlay -- a brand-new job is essentially never on the current
	 * page (it sorts last under the default created_at-desc... actually first; either way
	 * it may not match the active filters, e.g. an archived-only view), so patching `page`
	 * directly would be wrong more often than right. */
	function addJob(job: Job): void {
		incoming.update((current) => ({ ...current, [job.id]: job }));
	}

	/** Whether `job` belongs in the currently-loaded page under the active filters --
	 * `includeArchived`/`status` are exact, since both live directly on `Job`. `q` (full-
	 * text search) is deliberately not checked here: `search.job_matches()` (backend) also
	 * matches on the job's *tracks*, which this store never holds for a job it hasn't
	 * fetched tracks for, so a caller needing to honor an active `q` must treat "can't
	 * tell" as its own case rather than trusting this to cover it. */
	function jobMatchesFilters(job: Job, f: Filters): boolean {
		if (!f.includeArchived && job.archived_at !== null) return false;
		if (f.status.length > 0 && !f.status.includes(api.statusKey(job.status))) return false;
		return true;
	}

	/** The value `job` sorts by under a given `sort` field, mirroring
	 * `job_listing._sort_value` (backend) for every field this store can compute from a
	 * single `Job` object. `next_retry` is deliberately absent: it's `next_retry_at`,
	 * derived server-side from a track's `scheduled_at` and never returned on `Job` at all
	 * -- a caller sorting by it can't place a row correctly from this alone and must fall
	 * back to a reload instead of calling this. */
	function jobSortValue(job: Job, sort: string): number | string {
		switch (sort) {
			case 'title':
				return job.title;
			case 'status':
				return api.STATUS_TOKENS.indexOf(api.statusKey(job.status));
			case 'track_count':
				return Object.values(job.track_counts).reduce((sum, n) => sum + n, 0);
			default:
				return new Date(job.created_at).getTime();
		}
	}

	/** Where `job` belongs among `items` (already in `sort`/`dir` order) -- a linear scan
	 * against the loaded window only, since that's all this store has; a sort position
	 * relative to rows on a not-yet-fetched page can't be known any more precisely than
	 * the real backend query already guarantees once that page is actually loaded. */
	function jobInsertIndex(items: PageItem[], job: Job, sort: string, dir: 'asc' | 'desc'): number {
		const value = jobSortValue(job, sort);
		const descending = dir === 'desc';
		for (let i = 0; i < items.length; i++) {
			const otherValue = jobSortValue(items[i] as Job, sort);
			const belongsBefore = descending ? value > otherValue : value < otherValue;
			if (belongsBefore) return i;
		}
		return items.length;
	}

	/** Patches a job already on the page in place, and -- only when `allowInsert` is true
	 * -- inserts it if it's missing. `allowInsert` must stay opt-in: `applyJobEvent` below
	 * runs for *every* `job.state` event this session's SSE channel carries, which is every
	 * job change the owning user makes anywhere (this tab, another tab/device, an admin
	 * acting on it, `beat`'s retention auto-archive sweep -- see `cancel_job`
	 * (`backend/app/routers/jobs.py`) publishing to the job's *owner*, not the acting
	 * session), not only ones for a job this store has ever seen before. A job sitting
	 * beyond the currently-loaded page window (rank 50 in a 20-per-page list, say) that
	 * merely changes state is *not* new -- it was already counted in the original
	 * `totalEstimate`/`countsByStatus` snapshot, and its correct position in the full
	 * (mostly unloaded) ordering could be anywhere, not just the tail. Blindly inserting it
	 * here would double-count it and could still collide with `loadMore()` the same way
	 * described below. The only two call sites that pass `allowInsert: true` are ones that
	 * know for certain this job is (or just was) one this store is actively tracking as new
	 * -- a job leaving the `incoming` overlay (`applyJobEvent`, gated on `wasIncoming`), and
	 * this session's own `cancelJob` (reachable while a job is still `expanding` straight
	 * from `IncomingJobs`). Without this gate at all, a brand-new job vanished from both the
	 * overlay (removed by the caller) and the page (never inserted) until a full reload --
	 * the original production bug this fixes.
	 *
	 * Insertion itself: `jobMatchesFilters` can't resolve an active `q`, and
	 * `jobSortValue`/`jobInsertIndex` can't place a `next_retry` sort -- both fall back to
	 * `scheduleReload()` rather than guessing, the same escape hatch `applyOwnArchiveAction`'s
	 * bulk path already uses. Inserting strictly before an already-loaded row can never
	 * duplicate a later page: that row's sort value is strictly before `p.nextCursor`'s own
	 * (whatever produced it), so nothing about a not-yet-fetched page changes. Appending at
	 * the *tail* is a different case -- if `p.nextCursor` is non-null, a real page beyond
	 * this one still exists, keyed off the old last row's own (sort value, id) tuple
	 * (`pagination.apply_cursor`, backend), which knows nothing about this brand-new job. A
	 * tie or a value after that row is exactly what the server's own "everything after the
	 * cursor" condition matches, so `loadMore()` (which concatenates with no id dedup) can
	 * legitimately fetch this same job again from the server and duplicate it. Only safe
	 * when there's nothing left to fetch (`p.nextCursor === null`); otherwise fall back to
	 * `scheduleReload()` the same as the two cases above. */
	function patchPageJob(job: Job, opts: { allowInsert?: boolean } = {}): void {
		const f = get(filters);
		if (f.scope !== 'jobs') return;
		page.update((p) => {
			const idx = p.items.findIndex((i) => i.id === job.id);
			if (idx !== -1) {
				const items = [...p.items];
				items[idx] = job;
				return { ...p, items };
			}
			if (!opts.allowInsert) return p;
			// `expanding`/`failed` belong only in the `incoming` overlay (the same check
			// `applyJobEvent` uses to decide overlay membership) -- a zero-track job has no
			// track-derived title yet (or, for `failed`, never will), so inserting it here
			// on a real SSE echo of its *own* `expanding` state (confirmed happening in
			// practice, not just a hypothetical) would sort it by its raw `source_url`
			// under a title/track_count sort. That position would then be permanently
			// wrong: once a row exists, the idx !== -1 branch above only ever patches it in
			// place and never re-sorts it, so a later `expanded` event with the real title
			// would update the text but never move the row.
			if (job.state === 'expanding' || job.state === 'failed') return p;
			if (!jobMatchesFilters(job, f)) return p;
			if (f.q || f.sort === 'next_retry') {
				scheduleReload();
				return p;
			}
			const items = [...p.items];
			const insertAt = jobInsertIndex(items, job, f.sort, f.dir);
			if (insertAt === items.length && p.nextCursor !== null) {
				scheduleReload();
				return p;
			}
			items.splice(insertAt, 0, job);
			const key = api.statusKey(job.status);
			return {
				...p,
				items,
				totalEstimate: p.totalEstimate + 1,
				countsByStatus: { ...p.countsByStatus, [key]: (p.countsByStatus[key] ?? 0) + 1 }
			};
		});
	}

	async function cancelJob(jobId: string): Promise<void> {
		const job = await api.cancelJob(jobId);
		// `allowInsert: true` -- this is always a job the acting session could already see
		// somewhere (either `IncomingJobs`, still `expanding`, or an in-page `JobRow`,
		// already `idx !== -1` and so unaffected either way), never an arbitrary
		// off-page job, so promoting it onto the page here is always legitimate.
		patchPageJob(job, { allowInsert: true });
		incoming.update((current) => {
			const { [jobId]: _drop, ...rest } = current;
			return rest;
		});
		if (isExpanded(jobId)) await loadExpandedTracks(jobId);
	}

	async function bumpJob(jobId: string): Promise<void> {
		patchPageJob(await api.bumpJob(jobId));
	}

	async function setJobPriority(jobId: string, priority: number): Promise<void> {
		patchPageJob(await api.setJobPriority(jobId, priority));
	}

	/** "Clear log" (`allSettled`) or a single job's archive button -- *this session's own*
	 * action, straight from its direct HTTP response. On success, a job that no longer
	 * matches the active `includeArchived` filter is dropped from view; one that still
	 * matches (the "archived toggle already on" case) is patched in place -- either way,
	 * no reload, per the plan's explicit "leaves the default view live" requirement.
	 *
	 * `archive_jobs`/`unarchive_jobs` (backend) also publish a `job.state` SSE event
	 * (`archived: true/false`) for every job touched, including an ordinary single-job
	 * action, and this session's own already-open stream receives that echo too -- and
	 * can receive and process it *before* this function's own direct-response call runs,
	 * since the backend commits and starts publishing before the HTTP response finishes
	 * writing back (confirmed via a real-stack Playwright run measuring actual request
	 * timing, not assumed). This function is the only caller with the complete,
	 * trustworthy id list for an action, so it's the only place that decides "patch
	 * precisely" vs. "bulk reload beyond the loaded page" -- but that decision alone
	 * can't tell "this id is missing because it's genuinely part of a bulk action beyond
	 * this page" apart from "this id is missing because the echo already removed it,
	 * correctly, moments before I got here." `recentlyEchoRemovedArchiveIds` closes that
	 * gap: `patchArchivedFlagFromEvent` marks an id there when *it* does a removal, and
	 * this function treats a marked id as already accounted for rather than a sign of an
	 * unloaded bulk job (see docs/GOTCHAS.md's v20 entry for the five-round history behind
	 * this exact interaction). */
	async function archiveJobs(opts: { jobIds?: string[]; allSettled?: boolean }): Promise<string[]> {
		const result = await api.archiveJobs(opts);
		applyOwnArchiveAction(result.archived_ids, true);
		return result.archived_ids;
	}

	async function unarchiveJobs(jobIds: string[]): Promise<string[]> {
		const result = await api.unarchiveJobs(jobIds);
		applyOwnArchiveAction(result.unarchived_ids, false);
		return result.unarchived_ids;
	}

	// Shared "don't guess, ask the server" escape hatch for anywhere a precise local patch
	// isn't possible: `archive_jobs` (backend) publishes one SSE event *per archived job*,
	// individually -- for the "clear log" bulk case, that's potentially dozens of separate
	// messages for one click, so debouncing collapses a reload that might otherwise seem
	// needed once per message into the one reload actually needed (the same pattern
	// `scheduleJobRefresh`/`flushJobRefreshes` already uses for the analogous per-track
	// -event flood). `patchPageJob` below reuses it for the two cases it can't resolve
	// from the `Job` object alone (an active search query, a `next_retry` sort).
	let pendingReloadTimer: ReturnType<typeof setTimeout> | undefined;
	function scheduleReload(): void {
		clearTimeout(pendingReloadTimer);
		pendingReloadTimer = setTimeout(reload, 300);
	}

	// Ids `patchArchivedFlagFromEvent` has already removed from view (and already
	// decremented counts for) via an SSE echo that arrived before this action's own
	// direct HTTP response did. `applyOwnArchiveAction` consumes an entry here instead of
	// treating that id as evidence of an unloaded bulk job -- the entry is removed the
	// moment it's consumed, and the short timeout is only a safety net against a leaked
	// entry if `applyOwnArchiveAction` is somehow never called for it (it always is, in
	// practice, since it's this store's own action that caused the echo in the first
	// place).
	const recentlyEchoRemovedArchiveIds = new Set<string>();

	function applyOwnArchiveAction(ids: string[], archived: boolean): void {
		if (ids.length === 0) return;
		const idSet = new Set(ids);
		const f = get(filters);
		if (f.scope !== 'jobs') return;

		if (f.includeArchived) {
			page.update((p) => ({
				...p,
				items: p.items.map((i) =>
					idSet.has(i.id)
						? { ...(i as Job), archived_at: archived ? new Date().toISOString() : null }
						: i
				)
			}));
			return;
		}

		// A job leaving view under the current (non-archived) filter also leaves the
		// status-bucket it was counted under -- countsByStatus/totalEstimate are
		// themselves scoped by include_archived server-side (job_listing.py builds them
		// from the same archived-filtered base query), so an archived-away row must be
		// subtracted from both here, not just removed from `items`, or the state-filter
		// chip counts drift from what's actually rendered until the next reload.
		const current = get(page);
		const removed = current.items.filter((i) => idSet.has(i.id)) as Job[];
		let alreadyHandledByEcho = 0;
		for (const id of ids) {
			const key = `${archived}:${id}`;
			if (recentlyEchoRemovedArchiveIds.has(key)) {
				recentlyEchoRemovedArchiveIds.delete(key);
				alreadyHandledByEcho++;
			}
		}
		if (removed.length + alreadyHandledByEcho < ids.length) {
			// The "clear log" bulk action (`all_settled: true`) archives every eligible
			// job for the user, not just whatever's on the currently loaded page
			// (`archive.archive_jobs`'s whole reason to exist) -- `ids` can therefore
			// contain jobs this store has no local record of, and there's no way to know
			// which status bucket an unloaded job belonged to well enough to decrement it
			// precisely. A single job's archive/unarchive button never hits this branch
			// (the clicked row is always already loaded, or already accounted for via
			// `alreadyHandledByEcho`); only the bulk path can.
			scheduleReload();
			return;
		}

		for (const job of removed) invalidateExpandedFetch(job.id);
		// A row leaving view this way must also stop being "expanded" -- otherwise
		// toggling the archived filter back on later re-shows it already-open with
		// whatever track snapshot was last fetched before it was archived, instead of a
		// fresh one.
		expanded.update((e) => {
			if (!removed.some((job) => job.id in e)) return e;
			const next = { ...e };
			for (const job of removed) delete next[job.id];
			return next;
		});

		// Only `removed` (jobs still actually present in `p.items`) need their counts
		// decremented here -- an id accounted for via `alreadyHandledByEcho` already had
		// its bucket decremented by `patchArchivedFlagFromEvent` itself.
		const countsByStatus = { ...current.countsByStatus };
		for (const job of removed) {
			const key = api.statusKey(job.status);
			countsByStatus[key] = Math.max(0, (countsByStatus[key] ?? 0) - 1);
		}
		page.update((p) => ({
			...p,
			items: p.items.filter((i) => !idSet.has(i.id)),
			totalEstimate: Math.max(0, p.totalEstimate - removed.length),
			countsByStatus
		}));
	}

	/** The SSE echo of an archive/unarchive action -- this session's own, or (v17's admin
	 * all-users pattern-subscribe aside) nobody else's, since jobs are per-user. Genuinely
	 * idempotent: safe to call any number of times, in any order relative to
	 * `applyOwnArchiveAction`, because it only ever acts when the currently-loaded row's
	 * `archived_at` doesn't already match the event, and records what it did (via
	 * `recentlyEchoRemovedArchiveIds`) so `applyOwnArchiveAction` can recognize its own
	 * action's effect already happened rather than mistaking the row's absence for an
	 * unloaded bulk job. A *different* tab of the same user archiving a job leaves this
	 * one's counts briefly stale until its own next reload/filter-change -- an accepted,
	 * narrow trade, not something this function tries to solve too. */
	function patchArchivedFlagFromEvent(jobId: string, archived: boolean): void {
		const f = get(filters);
		if (f.scope !== 'jobs') return;
		const current = get(page);
		const existing = current.items.find((i) => i.id === jobId) as Job | undefined;
		if (!existing || (existing.archived_at !== null) === archived) return;

		if (f.includeArchived) {
			page.update((p) => ({
				...p,
				items: p.items.map((i) =>
					i.id === jobId
						? { ...(i as Job), archived_at: archived ? new Date().toISOString() : null }
						: i
				)
			}));
			return;
		}

		invalidateExpandedFetch(jobId);
		expanded.update((e) => {
			if (!(jobId in e)) return e;
			const next = { ...e };
			delete next[jobId];
			return next;
		});
		const key = api.statusKey(existing.status);
		page.update((p) => ({
			...p,
			items: p.items.filter((i) => i.id !== jobId),
			totalEstimate: Math.max(0, p.totalEstimate - 1),
			countsByStatus: {
				...p.countsByStatus,
				[key]: Math.max(0, (p.countsByStatus[key] ?? 0) - 1)
			}
		}));

		const claimKey = `${archived}:${jobId}`;
		recentlyEchoRemovedArchiveIds.add(claimKey);
		setTimeout(() => recentlyEchoRemovedArchiveIds.delete(claimKey), 3000);
	}

	async function cancelTrack(trackId: string, jobId?: string): Promise<void> {
		const track = await api.cancelTrack(trackId);
		applyTrackPatch(track, jobId);
	}

	/** Returns whether the retry is held behind the global breaker, so the caller can
	 * surface that precedence to the user rather than leaving a silent no-op. */
	async function retryTrack(trackId: string, jobId?: string): Promise<{ breakerHeld: boolean }> {
		const { breaker_held, ...track } = await api.retryTrack(trackId);
		applyTrackPatch(track, jobId);
		return { breakerHeld: breaker_held };
	}

	function applyTrackPatch(track: Track, jobId?: string): void {
		const owningJobId = jobId ?? track.job_id;
		if (isExpanded(owningJobId)) {
			expanded.update((e) => {
				const job = e[owningJobId];
				if (!job) return e;
				const idx = job.items.findIndex((t) => t.id === track.id);
				if (idx === -1) return e;
				const items = [...job.items];
				items[idx] = { ...items[idx], ...track };
				return { ...e, [owningJobId]: { ...job, items } };
			});
		}
		page.update((p) => {
			if (get(filters).scope !== 'tracks') return p;
			const idx = p.items.findIndex((i) => i.id === track.id);
			if (idx === -1) return p;
			const items = [...p.items];
			items[idx] = { ...(items[idx] as LiveTrackWithJob), ...track };
			return { ...p, items };
		});
		scheduleJobRefresh(owningJobId);
	}

	function findCachedTrackMeta(trackId: string): Track | undefined {
		const tracksScope = get(page).items;
		for (const item of tracksScope) {
			if (isTrackItem(item) && item.id === trackId) return item;
		}
		for (const job of Object.values(get(expanded))) {
			const found = job.items.find((t) => t.id === trackId);
			if (found) return found;
		}
		return undefined;
	}

	function applyTrackEvent(event: Extract<StreamEvent, { type: 'track.state' }>): void {
		// Coarse-vs-fine: only a genuine state change (including "first time seen") is
		// worth a job-row refresh -- a same-state progress-percent tick is not.
		if (lastKnownTrackState[event.track_id] !== event.state) {
			lastKnownTrackState[event.track_id] = event.state;
			scheduleJobRefresh(event.job_id);
		}

		liveActive.update((current) => {
			if (event.state !== 'downloading') {
				if (!(event.track_id in current)) return current;
				const existing = current[event.track_id];
				// A truly terminal state is never coming back -- drop it immediately, no
				// grace window to wait out. Must check the INCOMING event's state, not
				// existing.state: existing still holds the pre-event value (typically
				// 'downloading'), so checking it here would never match on the exact
				// transition that matters most (downloading -> completed) and every
				// finished/cancelled download would sit in the Waterfall at its last
				// progress reading for the full grace window instead of vanishing right
				// away -- caught by a fresh-eyes review, reproducing the very glitch this
				// version fixes in a new shape.
				if (TRULY_TERMINAL_STATES.has(event.state)) {
					clearLiveRemovalTimer(event.track_id);
					const { [event.track_id]: _drop, ...rest } = current;
					return rest;
				}
				scheduleLiveRemoval(event.track_id);
				const next: LiveTrack = { ...existing, state: event.state };
				if (event.scheduled_at !== undefined) next.scheduled_at = event.scheduled_at;
				if (event.error !== undefined) next.last_error = event.error;
				if (event.attempt_count !== undefined) next.attempt_count = event.attempt_count;
				return { ...current, [event.track_id]: next };
			}
			clearLiveRemovalTimer(event.track_id);
			const existing = current[event.track_id];
			if (existing && TRULY_TERMINAL_STATES.has(existing.state)) return current;
			// v23: the event itself carries title/artists/album now (events.py's
			// publish_track_event, backed by the same song_json the worker already has
			// loaded) -- prefer that over findCachedTrackMeta, which only ever knew about
			// rows the browser had separately fetched via REST. Still fall back to the
			// cache for an event published before this field existed or a call site with
			// nothing to offer, and still re-apply on every update (not just at creation)
			// so a first event that happened to lack metadata doesn't permanently freeze
			// this track as unknown once a later one supplies it.
			const seed = existing ?? findCachedTrackMeta(event.track_id);
			const base: LiveTrack = existing ?? {
				id: event.track_id,
				job_id: event.job_id,
				state: event.state,
				title: event.title ?? seed?.title ?? null,
				artists: event.artists ?? seed?.artists ?? null,
				album: event.album ?? seed?.album ?? null,
				spotify_track_id: seed?.spotify_track_id ?? '',
				attempt_count: seed?.attempt_count ?? 0,
				scheduled_at: null,
				last_error: null,
				last_error_type: null
			};
			const next: LiveTrack = {
				...base,
				state: event.state,
				progress: event.progress ?? base.progress,
				title: event.title ?? base.title,
				artists: event.artists ?? base.artists,
				album: event.album ?? base.album
			};
			if (event.scheduled_at !== undefined) next.scheduled_at = event.scheduled_at;
			if (event.error !== undefined) next.last_error = event.error;
			if (event.attempt_count !== undefined) next.attempt_count = event.attempt_count;
			return { ...current, [event.track_id]: next };
		});

		const patchOne = <T extends Track>(items: T[]): T[] => {
			const idx = items.findIndex((t) => t.id === event.track_id);
			if (idx === -1) return items;
			const existing = items[idx];
			if (TRULY_TERMINAL_STATES.has(existing.state)) return items;
			const next = { ...existing, state: event.state } as T;
			if (event.scheduled_at !== undefined) next.scheduled_at = event.scheduled_at;
			if (event.error !== undefined) next.last_error = event.error;
			if (event.attempt_count !== undefined) next.attempt_count = event.attempt_count;
			if (event.progress !== undefined) (next as LiveTrack).progress = event.progress;
			const copy = [...items];
			copy[idx] = next;
			return copy;
		};

		if (isExpanded(event.job_id)) {
			expanded.update((e) => {
				const job = e[event.job_id];
				if (!job) return e;
				return { ...e, [event.job_id]: { ...job, items: patchOne(job.items) } };
			});
		}
		page.update((p) => {
			if (get(filters).scope !== 'tracks') return p;
			return { ...p, items: patchOne(p.items as LiveTrackWithJob[]) };
		});
	}

	/** Unlike `track.state`, a job.state event has no high-frequency flood equivalent to a
	 * downloading track's progress ticks (v10's ladder/breaker are the only thing that
	 * repeatedly touches a track's state without ever touching its parent job's), so this
	 * fetches the fresh row immediately rather than going through the debounced
	 * `scheduleJobRefresh` path -- and needs the fetch either way, since the event itself
	 * carries no title/track_counts/priority to populate the incoming overlay with. */
	async function applyJobEvent(event: Extract<StreamEvent, { type: 'job.state' }>): Promise<void> {
		if (event.archived !== undefined) {
			patchArchivedFlagFromEvent(event.job_id, event.archived);
		}

		let job: Job;
		try {
			job = await api.getJob(event.job_id);
		} catch {
			// 404 (deleted, or this session lost visibility) -- drop it from view everywhere.
			incoming.update((current) => {
				const { [event.job_id]: _drop, ...rest } = current;
				return rest;
			});
			page.update((p) => ({ ...p, items: p.items.filter((i) => i.id !== event.job_id) }));
			return;
		}

		// Read before mutating: whether this store was tracking `job` as new (in
		// `incoming`) is what tells `patchPageJob` whether inserting it is legitimate.
		// This event fires for *every* state change on *every* job the owning user's SSE
		// channel carries -- another tab/device acting on it, an admin, `beat`'s retention
		// sweep -- not only ones this store has ever seen before, so `allowInsert` must
		// stay narrowly scoped to "was actually in the overlay a moment ago", never a bare
		// `idx === -1`.
		const wasIncoming = event.job_id in get(incoming);

		if (job.state === 'expanding' || job.state === 'failed') {
			incoming.update((current) => ({ ...current, [job.id]: job }));
		} else {
			incoming.update((current) => {
				const { [job.id]: _drop, ...rest } = current;
				return rest;
			});
		}
		patchPageJob(job, { allowInsert: wasIncoming });
		if (isExpanded(event.job_id) && event.state === 'expanded') {
			await loadExpandedTracks(event.job_id);
		}
	}

	async function applyEvent(event: StreamEvent): Promise<void> {
		if (event.type === 'track.state') {
			applyTrackEvent(event);
		} else {
			await applyJobEvent(event);
		}
	}

	const incomingJobs = derived(incoming, ($incoming) =>
		Object.values($incoming).sort(
			(a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
		)
	);

	const activeTracks = derived(liveActive, ($liveActive) => Object.values($liveActive));

	return {
		filters,
		page,
		expanded,
		incomingJobs,
		activeTracks,
		setFilters,
		reload,
		loadMore,
		setAllUsers,
		getAllUsers,
		reset,
		toggleExpand,
		isExpanded,
		loadMoreExpandedTracks,
		addJob,
		applyEvent,
		cancelJob,
		cancelTrack,
		retryTrack,
		bumpJob,
		setJobPriority,
		archiveJobs,
		unarchiveJobs
	};
}

export const queue = createQueueStore();
