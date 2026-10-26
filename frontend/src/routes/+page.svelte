<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import { get } from 'svelte/store';
	import { afterNavigate, goto, replaceState } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { navigating, page as route } from '$app/state';
	import * as api from '$lib/api';
	import { queue, groupTracksByJob } from '$lib/stores/queue';
	import type { Job, View } from '$lib/api';
	import type { LiveTrackWithJob } from '$lib/stores/queue';
	import { worker } from '$lib/stores/worker';
	import Waterfall from '$lib/components/Waterfall.svelte';
	import { link } from '$lib/stores/link';
	import IncomingJobs from '$lib/components/IncomingJobs.svelte';
	import WorkerStatusPill from '$lib/components/WorkerStatusPill.svelte';
	import QueueControls from '$lib/components/QueueControls.svelte';
	import JobRow from '$lib/components/JobRow.svelte';
	import TrackRow from '$lib/components/TrackRow.svelte';
	import { registerHandlers } from '$lib/keyboard/registry';
	import { collapseFocused, focusRowEl, kbList, listHandlers } from '$lib/keyboard/lists';
	import * as m from '$lib/paraglide/messages';
	import { errorText } from '$lib/i18n/errors';
	import { counted, formatNumber } from '$lib/i18n/format';
	import { countLinks, linkIn } from '$lib/submitLink';

	const { filters, page, incomingJobs, activeTracks } = queue;
	const { status: workerStatus } = worker;

	let { data } = $props();
	// Nullable per +layout.ts's type -- in practice never null here, since its `load`
	// redirects to /login before this page ever renders without a session. Falling back
	// to false/undefined rather than asserting non-null keeps this reactive to `data`
	// the same way the template's direct `data.session?.email` access already is.
	const isAdmin = $derived(data.session?.is_admin ?? false);

	let workerBusy = $derived($workerStatus?.busy ?? false);
	let workerPaused = $derived($workerStatus?.paused ?? false);
	// Only while it is still in the future (the backend's own `breaker_active` test); the
	// 5s poll below re-derives it, so a cleared hold drops out within one poll.
	let breakerUntil = $derived(
		$workerStatus?.breaker_tripped_until != null &&
			Date.parse($workerStatus.breaker_tripped_until) > Date.now()
			? $workerStatus.breaker_tripped_until
			: null
	);

	// v42 (F05): this page's own SSE link (`$link`), shown in the header and the Waterfall,
	// so a dropped stream never looks like a connected one; the layout reads it too.

	// Admin-only (v17): the mine/all scope, three-way since v54 (mine/all/others). "mine" by
	// default even for an admin -- switching it clears the queue store (see queue.setView) and
	// reconnects the SSE stream so both REST and live data agree on scope. v54: a reload keeps
	// it through the query string (`?view=others`). Without one it starts from the store's own
	// scope (v42), which outlives this page (a trip to /settings and back): starting at "mine"
	// while the store still fetched all users mislabelled every foreign row as the admin's.
	// Never for a non-admin, whatever the URL says or an earlier admin session on this tab
	// left in the store.
	const VIEWS: readonly View[] = ['mine', 'all', 'others'];
	// One rule for "is this the viewer's", the store's (`queue.setViewer`): case-insensitive.
	const myEmail = $derived(data.session?.email?.toLowerCase());
	const isMe = (email: string) => email.toLowerCase() === myEmail;
	// `location`, not `route.url`: a Back to an entry `replaceState` rewrote navigates to the URL
	// SvelteKit recorded for it (the one before the rewrite), so `route.url` can name a view the
	// admin has since left; the address bar can't. The page is client-only (`ssr = false`).
	function viewInUrl(): View | null {
		const asked = new URLSearchParams(window.location.search).get('view');
		return VIEWS.find((v) => v === asked) ?? null;
	}
	/** The view this history entry was left in (`syncViewUrl` keeps it in the entry's page
	 * state): a Back restores it, while a link or `g d` to `/` arrives with none. */
	function viewInEntry(): View | null {
		return VIEWS.find((v) => v === route.state.view) ?? null;
	}
	let view = $state<View>(
		untrack(() => (isAdmin ? (viewInUrl() ?? viewInEntry() ?? queue.getView()) : 'mine'))
	);

	// v54: an in-app navigation to a bare `/` while here (`g d`) would drop `?view=`; put it back. A
	// Back/Forward to another dashboard entry while this page is still mounted reuses it, so
	// that entry's own view (its URL, else its state) is adopted instead of overwritten.
	// A link or `goto` to `/?view=…` names its view too, and is adopted the same way.
	afterNavigate((navigation) => {
		if (navigation.type === 'enter') return;
		if (isAdmin) {
			const left = navigation.type === 'popstate' ? (viewInUrl() ?? viewInEntry()) : viewInUrl();
			if (left !== null && left !== view) {
				onViewChange(left);
				return;
			}
		}
		syncViewUrl();
	});

	/** v54: the query string says the view (none for "mine"), replaced in place, so a reload
	 * keeps it and switching adds no history entries. The entry's page state says it too, "mine"
	 * included, so a Back to an entry left in "mine" restores that, not the store's latest (a
	 * bare `/` from `g d` or a link still keeps the store's, v42). A non-admin's `?view=` is
	 * dropped. */
	// `location`, not `route.url`: `replaceState` leaves `page.url` at the last navigation.
	function syncViewUrl() {
		if (unmounted) return;
		const query = view === 'mine' ? '' : `?view=${view}`;
		const entryView = isAdmin ? view : undefined;
		if (query === window.location.search && viewInEntry() === (entryView ?? null)) return;
		// `resolve()` builds the path; the rule can't see that a query string after it stays on
		// that same resolved route.
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		replaceState(`${resolve('/')}${query}`, { ...route.state, view: entryView });
	}

	let filtersActive = $derived(
		$filters.q.trim() !== '' || $filters.status.length > 0 || $filters.state.length > 0
	);
	// v46: whole phrases per scope, never a noun spliced into a sentence (Hungarian inflects
	// it), and counts through Intl and plural rules.
	// v47: the exact total, from the same grouped counts the chips show (each is over the
	// searched set before its own filter, so the selected chips' sum is the list's size).
	// The capped estimate read "1,662 of 1,000+ jobs" at volume, and tracks only "150+".
	// `null` while there are no counts to sum (then the jobs head falls back to the estimate).
	function exactTotal(counts: Record<string, number>, selected: string[]): number | null {
		const keys = Object.keys(counts);
		if (keys.length === 0) return null;
		return (selected.length ? selected : keys).reduce((sum, key) => sum + (counts[key] ?? 0), 0);
	}
	let countText = $derived.by(() => {
		if ($page.loading) return m.dashboard_count_loading();
		if ($page.error) return '';
		const shown = $page.items.length;
		// v47: an empty queue says so in its own state below; "0 of 0 jobs" added nothing.
		if (shown === 0 && !filtersActive) return '';
		if ($filters.scope === 'jobs') {
			const exact = exactTotal($page.countsByStatus, $filters.status);
			const total = Math.max(exact ?? $page.totalEstimate, shown);
			return m.dashboard_count_jobs({
				shown: formatNumber(shown),
				total:
					exact === null && total >= 1000
						? m.dashboard_count_cap({ cap: formatNumber(1000) })
						: formatNumber(total),
				count: total
			});
		}
		const exact = exactTotal($page.countsByState, $filters.state);
		if (exact === null)
			return $page.nextCursor
				? m.dashboard_count_tracks_more(counted(shown))
				: m.dashboard_count_tracks(counted(shown));
		const total = Math.max(exact, shown);
		return m.dashboard_count_tracks_of({
			shown: formatNumber(shown),
			total: formatNumber(total),
			count: total
		});
	});
	let emptyTitle = $derived.by(() => {
		const query = $filters.q.trim();
		if ($filters.scope === 'jobs')
			return query ? m.dashboard_empty_jobs_query({ query }) : m.dashboard_empty_jobs_filters();
		return query ? m.dashboard_empty_tracks_query({ query }) : m.dashboard_empty_tracks_filters();
	});

	const SOURCE_LABEL: Record<Job['source_type'], () => string> = {
		track: m.incoming_source_track,
		album: m.incoming_source_album,
		playlist: m.incoming_source_playlist,
		artist: m.incoming_source_artist,
		search: m.incoming_source_search
	};

	// v42: both state buttons swap their own block out (loading replaces it), so focus is
	// handed to a target that stays: the search box, or the queue's heading.
	let controls: ReturnType<typeof QueueControls> | undefined = $state();

	function clearSearchAndFilters() {
		controls?.clearSearchAndFilters();
	}

	// v45: "load more" moves focus to the first row it loaded (where the user reads on), else
	// the queue's heading. Rows are found by item id, not DOM position: in tracks scope a new
	// page's tracks can join an earlier group. A pointer press leaves focus where it is unless
	// the last page took the button away from under it.
	async function loadMorePage(event: MouseEvent) {
		const button = event.currentTarget as HTMLElement;
		const fromKeyboard = event.detail === 0;
		// Safari doesn't focus a clicked button, so <body> says nothing about a pointer press.
		await loadMoreRows(() => fromKeyboard || !button.isConnected);
	}

	/** Loads the next page; `shouldFocus()` (asked once it's in) decides whether its first row
	 * takes focus. Whether there was a page to load. */
	async function loadMoreRows(shouldFocus: () => boolean = () => true): Promise<boolean> {
		if ($page.loading || $page.loadingMore || !$page.nextCursor) return false;
		const focusAtStart = document.activeElement;
		const known = new Set($page.items.map((item) => item.id));
		await queue.loadMore();
		await tick();
		// Focus the user moved somewhere else meanwhile is theirs.
		const moved =
			document.activeElement !== focusAtStart && document.activeElement !== document.body;
		if (moved || !shouldFocus()) return true;
		// Only a page that was appended moves focus: a failed one leaves it (on the button, to
		// retry), and one a reload superseded put an unrelated list there.
		const appended =
			!$page.moreError && $page.items.slice(0, known.size).every((item) => known.has(item.id));
		const fresh = appended ? $page.items.find((item) => !known.has(item.id)) : undefined;
		if (!fresh) {
			if (document.activeElement === document.body)
				document.getElementById('queue-heading')?.focus();
			return true;
		}
		const row = fresh
			? document.querySelector<HTMLElement>(`[data-kb-row="${CSS.escape(fresh.id)}"]`)
			: null;
		if (!focusRowEl(row)) document.getElementById('queue-heading')?.focus();
		return true;
	}

	// v45: the dashboard's keys -- the lists', the queue controls', and Esc's two jobs here
	// (close the focused row, else clear and leave the search).
	$effect(() =>
		registerHandlers({
			...listHandlers({
				mainList: () => ($filters.scope === 'jobs' ? 'jobs' : 'tracks'),
				loadMore: () => {
					if (!$page.nextCursor) return false;
					// Already loading: handled (End mustn't scroll the page meanwhile).
					if (!$page.loading && !$page.loadingMore) loadMoreRows();
					return true;
				}
			}),
			search: () => focusField('queue-search'),
			submit: () => focusField('submit-url'),
			escape: (event) => {
				if (collapseFocused()) return true;
				const search = document.getElementById('queue-search');
				if (!search || event.target !== search) return false;
				controls?.clearSearch();
				search.blur();
				return true;
			},
			'scope-jobs': () => (controls?.setScope('jobs'), true),
			// v54: mine -> all -> others -> mine (admin-only in the registry, and here too).
			'view-cycle': () => {
				if (!isAdmin) return false;
				onViewChange(VIEWS[(VIEWS.indexOf(view) + 1) % VIEWS.length]);
				return true;
			},
			'scope-tracks': () => (controls?.setScope('tracks'), true),
			filters: () => controls?.focusFilters() ?? false,
			sort: () => (controls?.cycleSort(), true),
			archived: () => (controls?.toggleArchived(), true)
		})
	);

	// v45: where focus goes when the focused list empties out (its last row cancelled or
	// archived away): the queue's heading, once no reload is still bringing the list back.
	function listFallback(): HTMLElement | null {
		return $page.loading ? null : document.getElementById('queue-heading');
	}

	function focusField(id: string): boolean {
		const field = document.getElementById(id) as HTMLInputElement | null;
		if (!field || field.disabled) return false;
		field.focus();
		return true;
	}

	function retryQueue() {
		queue.reload();
		document.getElementById('queue-heading')?.focus();
	}

	function focusSubmit() {
		document.getElementById('submit-url')?.focus();
	}

	let trackGroups = $derived(
		$filters.scope === 'tracks' ? groupTracksByJob($page.items as LiveTrackWithJob[]) : []
	);

	let url = $state('');
	// v47: a phone's field shows the short placeholder (the long one was cut mid-phrase at 390).
	let narrow = $state(false);
	$effect(() => {
		// i18n-ignore: a media query
		const query = window.matchMedia('(max-width: 40em)');
		narrow = query.matches;
		const update = () => (narrow = query.matches);
		query.addEventListener('change', update);
		return () => query.removeEventListener('change', update);
	});
	let submitting = $state(false);
	let submitError = $state('');
	// v53: the line under the form says something that isn't a failure (already queued).
	let submitNotice = $state(false);

	// v47: the form checks the link itself (`novalidate`): the browser's own bubble spoke the
	// browser's language, sat outside the design, and turned away a link pasted with words or
	// an emoji around it. What is sent out of what was pasted: `$lib/submitLink`.
	// v47: the form's own checks mark the field invalid, and a repeated sentence is announced
	// again (the region is emptied first; the same text twice isn't a change).
	let submitInvalid = $state(false);
	async function showSubmitProblem(text: string): Promise<void> {
		submitInvalid = true;
		submitNotice = false;
		submitError = '';
		await tick();
		submitError = text;
	}

	async function onsubmit(event: SubmitEvent) {
		event.preventDefault();
		submitInvalid = false;
		if (!url.trim()) {
			return showSubmitProblem(m.dashboard_submit_empty());
		}
		if (countLinks(url) > 1) {
			return showSubmitProblem(m.dashboard_submit_many_links());
		}
		const link = linkIn(url);
		if (!link) {
			return showSubmitProblem(m.dashboard_submit_not_link());
		}
		url = link;
		submitting = true;
		submitError = '';
		submitNotice = false;
		// A logout while the POST is in flight resets the store; the created job then belongs
		// to the previous identity and must not land in the next one's overlay (v42 sweep).
		const session = queue.getResetCount();
		try {
			const job = await api.createJob(link);
			if (queue.getResetCount() !== session) return;
			url = '';
			// v53: the same link is still downloading: nothing new was created, and the job
			// returned is already on the page (or the overlay); say so instead of adding it twice.
			if (job.hint === 'already_queued') {
				submitNotice = true;
				submitError = m.dashboard_submit_already_queued();
			} else if (queue.getView() === 'others') {
				// v54: the others view leaves the admin's own jobs out, this one too; say where it went.
				submitNotice = true;
				submitError = m.dashboard_submit_added_elsewhere();
			} else queue.addJob(job);
		} catch (err) {
			submitError = errorText(err, m.dashboard_submit_failed);
			// v53: the link itself was refused (too long): mark the field, as the form's own checks do.
			if (err instanceof api.ApiError && err.code === 'submit_too_long') submitInvalid = true;
		} finally {
			submitting = false;
		}
		// The disabled input lost focus while sending; give it back for the next link.
		await tick();
		// Not on touch: refocusing the input would reopen the keyboard over what was just sent.
		// i18n-ignore: a media query
		if (document.activeElement === document.body && !window.matchMedia('(pointer: coarse)').matches)
			document.getElementById('submit-url')?.focus();
	}

	// v47: a sign-out the server couldn't take says so (it failed silently on /).
	let logoutError = $state('');

	async function onLogout() {
		loggingOut = true;
		logoutError = '';
		try {
			await api.logout();
		} catch (err) {
			// Still here and still signed in: the reload guard must work again.
			loggingOut = false;
			const shown = m.dashboard_disconnect_failed({ error: errorText(err) });
			logoutError = shown;
			// It answers one press; it doesn't stay in the masthead for the rest of the visit.
			setTimeout(() => {
				if (logoutError === shown) logoutError = '';
			}, 10_000);
			return;
		}
		// `queue` is a module-level singleton that survives this SPA navigation -- clear it
		// before leaving, so a different identity logging in on the same tab next can never
		// render a flash of this session's rows while its own reload() is still in flight.
		queue.reset();
		source?.close();
		await goto(resolve('/login'));
	}

	// v12: previously relied entirely on the browser's built-in EventSource auto-reconnect,
	// which only covers a network-level drop (a raw TCP reset, readyState -> CONNECTING,
	// retried automatically). Per spec, a response with a non-2xx status or the wrong
	// content-type "fails the connection" permanently instead (readyState -> CLOSED, never
	// retried) -- something that was previously rare (a restarting `api` container gives the
	// browser a raw reset directly) but became routine once the same-origin nginx proxy
	// (frontend/nginx.conf) sits in front: `api` restarting now means nginx answers with a
	// real 502 (text/html), permanently killing the stream until a manual reload. This also
	// fixes a pre-existing gap where a 401 after session expiry already killed the stream for
	// the same reason. Reconnect manually with capped exponential backoff whenever the
	// browser has actually given up.
	let streamRetryDelayMs = 1000;
	// This page's own logout resets the store on purpose; outlived() must not reload then.
	let loggingOut = false;
	// The reset count this page mounted under; see connectStream's outlived(). Checked on
	// every poll too, so a reset is caught within 5s even while the stream is quiet.
	const mountedSession = queue.getResetCount();
	let streamRetryTimer: ReturnType<typeof setTimeout> | undefined;
	let source: EventSource | undefined;
	// v34.2: the stream's `onopen` is the only resync (see queue.reload). Mount and every
	// scope switch arm one fallback: if the stream hasn't opened when it fails outright
	// (a 502/401 closes it) or within RESYNC_FALLBACK_MS (a network-level failure keeps it
	// CONNECTING, which never reaches the CLOSED branch below), do one plain REST reload so
	// the page shows its data or its error instead of "Loading…" indefinitely. The
	// eventual `onopen` still resyncs as usual.
	// v47: 2.5s, down from 5s. A healthy stream opens in about 0.3s; with it down, five seconds
	// of "Loading…" read as a hung page.
	const RESYNC_FALLBACK_MS = 2500;
	let awaitingResync = false;
	let resyncFallbackTimer: ReturnType<typeof setTimeout> | undefined;

	function armResyncFallback() {
		awaitingResync = true;
		clearTimeout(resyncFallbackTimer);
		resyncFallbackTimer = setTimeout(resyncFallback, RESYNC_FALLBACK_MS);
	}

	function resyncFallback() {
		clearTimeout(resyncFallbackTimer);
		if (!awaitingResync) return;
		awaitingResync = false;
		queue.reload();
	}

	function connectStream() {
		if (unmounted) return;
		const stream = api.createEventSource(view);
		source = stream;
		// v42: the stream belongs to the session it was opened under. If the store is reset
		// meanwhile without this page logging out (an identity change in another tab, or a
		// session gone stale, caught by the layout -- possibly on a hover preload, with this
		// page still mounted), its events would refill the next identity's overlays and this
		// page's header and admin chrome describe someone else. Drop the event, stop the
		// stream, and reload: the layout then runs for whoever the session is now (or sends
		// the tab to /login), and nothing is left showing a dead link as "linked".
		// Against the count the page mounted under, not one captured here: a retry timer
		// firing after a reset must not open a stream that counts as current.
		const outlived = () => {
			if (queue.getResetCount() === mountedSession) return false;
			stream.close();
			clearTimeout(streamRetryTimer);
			if (!loggingOut) window.location.reload();
			return true;
		};
		// Events are applied only once this stream's identity check passed; anything dropped
		// before that is covered by the resync that follows it.
		let verified = false;
		const current = () => source === stream && stream.readyState === EventSource.OPEN;
		stream.onopen = async () => {
			// The browser can re-open this same EventSource: every opening is checked anew.
			verified = false;
			if (outlived()) return;
			// The cookie is shared across tabs: a reconnect sends whoever is signed in now.
			// If that isn't this page's identity, reload rather than adopt it under this
			// page's header and admin chrome (one request per (re)connect, not per row).
			try {
				const now = await api.me();
				if (now.email !== data.session?.email) {
					stream.close();
					window.location.reload();
					return;
				}
			} catch (err) {
				// v47: a 401 is the session ending (the layout takes the tab to /login). Anything
				// else can't tell (a blip): carry on; the layout and next reconnect check again.
				if (err instanceof api.ApiError && err.status === 401) {
					stream.close();
					// A stream that something else replaced meanwhile isn't this page's to retry.
					if (source !== stream) return;
					clearTimeout(streamRetryTimer);
					api.sessionEnded();
					// If the session turns out to be alive (a stale 401: a sign-in elsewhere), the
					// layout stays put, so this page keeps trying like any other drop; if it ended,
					// leaving the page clears the timer.
					link.set('reconnecting');
					streamRetryTimer = setTimeout(connectStream, streamRetryDelayMs);
					streamRetryDelayMs = Math.min(streamRetryDelayMs * 2, 30_000);
					return;
				}
			}
			// The stream may have dropped, or been replaced by a scope switch, meanwhile.
			if (outlived() || !current()) return;
			verified = true;
			link.set('live');
			awaitingResync = false;
			clearTimeout(resyncFallbackTimer);
			streamRetryDelayMs = 1000;
			// Per the v08 contract: resync full REST state on every connect/reconnect
			// rather than trying to replay whatever happened while disconnected.
			queue.reload();
		};
		stream.onmessage = (event) => {
			if (outlived() || !verified) return;
			queue.applyEvent(JSON.parse(event.data));
		};
		stream.onerror = () => {
			if (outlived()) return;
			// Either way the stream is down right now: the browser retrying on its own
			// (CONNECTING) or given up until the retry below (CLOSED).
			link.set('reconnecting');
			if (stream.readyState !== EventSource.CLOSED) {
				// Browser is already retrying on its own (readyState === CONNECTING).
				return;
			}
			stream.close();
			resyncFallback();
			streamRetryTimer = setTimeout(connectStream, streamRetryDelayMs);
			streamRetryDelayMs = Math.min(streamRetryDelayMs * 2, 30_000);
		};
	}

	/** Admin-only (v17): both REST and SSE must agree on scope, so switching requires
	 * clearing the accumulated store (queue.setView) and reconnecting the stream carrying
	 * the new view -- the existing connection has no way to change what channel it's
	 * subscribed to mid-flight. The new stream's `onopen` loads the new scope. */
	async function onViewChange(next: View) {
		if (next === view || !isAdmin) return;
		// Leaving `/` already: the switch would reach neither this page's history entry nor a
		// page that keeps it.
		if (navigating.to && navigating.to.route.id !== route.route.id) return;
		view = next;
		// Mid-navigation the browser's current entry may already be the one being navigated to:
		// writing into it would lose that entry's own view; `afterNavigate` settles it instead.
		if (!navigating.to) syncViewUrl();
		// A notice about where the last submit went is about the view it was sent from.
		if (submitNotice) {
			submitNotice = false;
			submitError = '';
		}
		link.set('connecting');
		clearTimeout(streamRetryTimer);
		streamRetryDelayMs = 1000;
		source?.close();
		queue.setView(next);
		armResyncFallback();
		connectStream();
	}

	// Worker/breaker state has no SSE event: the same 5s poll the v25 pill ran, now here
	// for every user (v42), since the Waterfall's status line and TrackRow's breaker-aware
	// countdown read it and the pill itself is admin-only. A failed poll keeps the last value.
	const WORKER_POLL_MS = 5000;

	// v47: an open EventSource can outlive the network under it (a dropped or changed network
	// while the page runs): no error, no events, the tell still "linked". The server's
	// heartbeat is an SSE comment, which a page can't see, so the poll is the watchdog: two
	// polls in a row that never reached the server (a network failure, not an error answer)
	// mean the link is down too, and the stream starts over. Not covered: a stream the server
	// dropped while the machine slept, if the network is back on wake (no poll fails, and a
	// quiet stream looks the same as a dead one); the browser's own socket timeout ends it.
	let unreachedPolls = 0;
	// A poll with no answer after 10s counts as unreached too, once: a request that hangs on
	// a dead connection never rejects. Later polls still go out, so one stuck request can't
	// stop the worker status from refreshing.
	const POLL_ANSWER_MS = 10_000;
	// Set by the cleanup: a poll, an offline/online event or a stream callback that settles
	// after the page is gone must not open a stream nobody owns.
	let unmounted = false;

	function pollWorker() {
		if (!loggingOut && queue.getResetCount() !== mountedSession) {
			window.location.reload();
			return;
		}
		let settled = false;
		const overdue = setTimeout(() => {
			if (settled || unmounted) return;
			settled = true;
			countUnreached();
		}, POLL_ANSWER_MS);
		const refreshed = worker.refresh();
		// v54 (U1): in the others view, whether the admin's own download (which that view's
		// stream leaves out) is receiving, so it still warms the page; asked only while this
		// poll's own answer says the worker is busy, and not once the page is gone.
		// Only there: the store awaits (and catches) this fork of the poll, so it never goes
		// unhandled when the poll fails.
		if (queue.getView() === 'others')
			queue.refreshOwnElsewhere(refreshed.then((status) => status.busy && !unmounted));
		refreshed
			.then(() => {
				unreachedPolls = 0;
			})
			.catch((err) => {
				if (settled) return;
				// An error answer reached the server: the run of unreached polls is broken.
				if (err instanceof api.ApiError) {
					unreachedPolls = 0;
					return;
				}
				countUnreached();
			})
			.finally(() => {
				settled = true;
				clearTimeout(overdue);
			});
	}

	function countUnreached() {
		unreachedPolls += 1;
		if (unreachedPolls >= 2 && get(link) === 'live') restartStream();
	}

	/** Drops the current stream and opens a new one now, at the first backoff step. */
	function restartStream() {
		if (unmounted) return;
		link.set('reconnecting');
		clearTimeout(streamRetryTimer);
		streamRetryDelayMs = 1000;
		source?.close();
		connectStream();
	}

	// v47: the browser knows when it's offline; the tell says so at once rather than "linked".
	// Back online, or back to this tab with the link down, it reconnects now instead of
	// waiting out a backoff of up to 30s.
	// A start-over rather than only the tell: a spurious `offline` (a VPN or Wi-Fi handoff)
	// with the stream still alive would otherwise pin "link lost" until something else fired.
	function onOffline() {
		restartStream();
	}

	// Only a link that is down starts over: an `online` with the stream still live (a VPN or
	// Wi-Fi handoff that never broke it) would otherwise wipe the list for a resync.
	function onOnline() {
		unreachedPolls = 0;
		if (get(link) !== 'live') restartStream();
	}

	function onVisible() {
		if (document.visibilityState === 'visible' && get(link) === 'reconnecting') restartStream();
	}

	onMount(() => {
		// The store's scope outlives the page; a non-admin must never inherit an admin's, and
		// an admin's reload starts from the URL's (v54).
		if (queue.getView() !== view) queue.setView(view);
		queue.setViewer(data.session?.email ?? null);
		// After the router has started: on a hard load, `replaceState` before then throws in dev.
		// Not while a later navigation is under way (a quick Back past this page): the entry is
		// no longer this one, and a client-side mount syncs from `afterNavigate` anyway.
		setTimeout(() => {
			if (!navigating.to) syncViewUrl();
		});
		link.set('connecting');
		queue.beginResync();
		armResyncFallback();
		connectStream();
		pollWorker();
		const workerPoll = setInterval(pollWorker, WORKER_POLL_MS);
		window.addEventListener('offline', onOffline);
		window.addEventListener('online', onOnline);
		document.addEventListener('visibilitychange', onVisible);

		return () => {
			unmounted = true;
			window.removeEventListener('offline', onOffline);
			window.removeEventListener('online', onOnline);
			document.removeEventListener('visibilitychange', onVisible);
			clearInterval(workerPoll);
			clearTimeout(streamRetryTimer);
			clearTimeout(resyncFallbackTimer);
			source?.close();
		};
	});
</script>

<svelte:head>
	<title>{m.dashboard_title()}</title>
</svelte:head>

<div class="stage">
	<header class="masthead">
		<div class="ident">
			<h1 class="wordmark">
				<!-- i18n-ignore: the wordmark and its spoken name are the same in every language. -->
				<span aria-hidden="true">SPOTDL // WEB</span><span class="sr-only">spotdl-web</span>
			</h1>
			<span class="label">{m.dashboard_ident_receiver()}</span>
		</div>
		<div class="status">
			<span class="link mono" class:down={$link !== 'live'} role="status">
				<span class="link-dot" aria-hidden="true"></span>
				{#if $link === 'live'}
					{m.dashboard_link_live()}
				{:else if $link === 'connecting'}
					{m.dashboard_link_connecting()}
				{:else}
					<!-- v47: the phone's masthead takes the short form; the Waterfall carries the
					     whole sentence, and the long one wrapped and pushed the page down. -->
					<span class="lost-full">{m.dashboard_link_lost()}</span><span class="lost-short"
						>{m.dashboard_link_lost_short()}</span
					>
				{/if}
			</span>
			{#if isAdmin}
				<WorkerStatusPill />
			{/if}
		</div>
		<nav class="session" aria-label={m.nav_pages()}>
			{#if isAdmin}
				<a class="nav-link" href={resolve('/library')}>{m.dashboard_nav_library()}</a>
				<a class="nav-link" href={resolve('/settings')}>{m.dashboard_nav_settings()}</a>
				<a class="nav-link" href={resolve('/stats')}>{m.dashboard_nav_stats()}</a>
			{/if}
			<a class="nav-link" href={resolve('/account')}>{m.dashboard_nav_account()}</a>
			<span class="who mono" title={data.session?.email}
				>{api.displayName(data.session?.username ?? null, data.session?.email ?? '')}</span
			>
			<button type="button" class="logout" onclick={onLogout}>{m.dashboard_disconnect()}</button>
			<p class="logout-error" role="alert">{logoutError}</p>
		</nav>
	</header>

	<!-- v42 (F29): the one main landmark; v45's skip link targets #main. No tabindex here:
	     a tabindex="-1" container takes focus on any click inside it and resets Tab order. -->
	<main id="main" class="main">
		<div class="submit-area">
			<form class="panel submit" {onsubmit} novalidate aria-label={m.dashboard_submit_form_label()}>
				<span class="prompt mono" class:sending={submitting} aria-hidden="true">&gt;</span>
				<input
					id="submit-url"
					class="well"
					type="url"
					placeholder={narrow
						? m.dashboard_submit_placeholder_short()
						: m.dashboard_submit_placeholder()}
					bind:value={url}
					disabled={submitting}
					aria-label={m.dashboard_submit_input_label()}
					aria-describedby="submit-error"
					aria-invalid={submitInvalid ? 'true' : undefined}
					oninput={() => (submitInvalid = false)}
				/>
				<button type="submit" class="mono" disabled={submitting}
					>{submitting ? m.dashboard_submit_sending() : m.dashboard_submit()}</button
				>
			</form>
			<p id="submit-error" class="submit-error" class:notice={submitNotice} role="alert">
				{submitError}
			</p>
		</div>

		<IncomingJobs jobs={$incomingJobs} {view} sessionEmail={data.session?.email ?? ''} {isAdmin} />

		<Waterfall
			tracks={$activeTracks}
			busy={workerBusy}
			link={$link}
			{breakerUntil}
			paused={workerPaused}
			{isAdmin}
		/>

		<section class="panel queue" aria-labelledby="queue-heading">
			<QueueControls
				bind:this={controls}
				{isAdmin}
				{view}
				{onViewChange}
				countsByStatus={$page.countsByStatus}
				countsByState={$page.countsByState}
				{countText}
			/>

			{#if $page.loading}
				<!-- Placeholder rows in the list's own rhythm; the head's "Loading…" says why. -->
				<ul class="skeleton" aria-hidden="true">
					{#each [0, 1, 2] as i (i)}
						<li><span class="bone badge"></span><span class="bone line"></span></li>
					{/each}
				</ul>
			{:else if $page.error}
				<div class="state" role="alert">
					<h3 class="state-title">{m.dashboard_error_title()}</h3>
					<p class="state-text">
						<span>{errorText($page.error.err)}</span>
					</p>
					<button type="button" class="state-action" onclick={retryQueue}
						>{m.dashboard_error_retry()}</button
					>
				</div>
			{:else if $page.items.length === 0}
				<div class="state">
					{#if filtersActive}
						<h3 class="state-title">{emptyTitle}</h3>
						<p class="state-text">
							{$filters.includeArchived
								? m.dashboard_empty_archived_included()
								: m.dashboard_empty_archived_hidden()}
						</p>
						<button type="button" class="state-action" onclick={clearSearchAndFilters}
							>{m.dashboard_empty_clear()}</button
						>
					{:else if $incomingJobs.some((j) => j.state === 'expanding' && (view !== 'mine' || isMe(j.owner_email)))}
						<h3 class="state-title">
							{view === 'all'
								? m.dashboard_reading_any()
								: view === 'others'
									? m.dashboard_reading_others()
									: m.dashboard_reading_own()}
						</h3>
						<p class="state-text">{m.dashboard_reading_text()}</p>
					{:else if view === 'all'}
						<h3 class="state-title">{m.dashboard_empty_all_title()}</h3>
						<p class="state-text">{m.dashboard_empty_all_text()}</p>
					{:else if view === 'others'}
						<h3 class="state-title">{m.dashboard_empty_others_title()}</h3>
						<p class="state-text">{m.dashboard_empty_others_text()}</p>
					{:else}
						<h3 class="state-title">{m.dashboard_empty_own_title()}</h3>
						<p class="state-text">
							{$filters.includeArchived
								? m.dashboard_empty_own_text()
								: m.dashboard_empty_own_text_archived_hidden()}
						</p>
						<button type="button" class="state-action" onclick={focusSubmit}
							>{m.dashboard_empty_own_action()}</button
						>
					{/if}
				</div>
			{:else if $filters.scope === 'jobs'}
				<!-- v45: each list is one Tab stop (roving tabindex, lib/keyboard/lists.ts). -->
				<ul
					class="job-list"
					aria-label={m.dashboard_list_jobs()}
					{@attach kbList('jobs', { fallback: listFallback })}
				>
					{#each $page.items as item (item.id)}
						<JobRow
							job={item as Job}
							{view}
							{isAdmin}
							own={view === 'mine' || isMe((item as Job).owner_email)}
						/>
					{/each}
				</ul>
			{:else}
				<ul
					class="job-list"
					aria-label={m.dashboard_list_tracks()}
					{@attach kbList('tracks', { fallback: listFallback })}
				>
					{#each trackGroups as group (group.job.id)}
						<li class="track-group" aria-labelledby="group-title-{group.job.id}">
							<!-- v41: the job row's grid, minus the chevron -- its type sits in the badge
							     column and its title over the track titles below (F02). -->
							<div class="group-header">
								<span class="source-type mono"
									>{SOURCE_LABEL[group.job.source_type]?.() ?? group.job.source_type}</span
								>
								<span class="title" id="group-title-{group.job.id}" title={group.job.title}
									>{group.job.title}</span
								>
								{#if view !== 'mine'}
									<span class="owner mono" title={group.job.owner_email}
										>{api.displayName(group.job.owner_username, group.job.owner_email)}</span
									>
								{/if}
							</div>
							<ul class="rows">
								{#each group.tracks as track (track.id)}
									<TrackRow
										{track}
										jobId={group.job.id}
										{isAdmin}
										elsewhere={view !== 'mine' && !isMe(group.job.owner_email)}
									/>
								{/each}
							</ul>
						</li>
					{/each}
				</ul>
			{/if}

			<!-- A failed "load more" keeps the loaded rows (moreError, not error); this button
			     retries just that page. -->
			{#if $page.moreError}
				<p class="more-error" role="alert">
					{m.dashboard_more_error()} <span>{errorText($page.moreError.err)}</span>
				</p>
			{/if}
			<!-- Stays mounted (aria-disabled) through a background reload (a reconnect's resync),
			     so a keyboard user's focus on it isn't dropped to the page. -->
			{#if $page.nextCursor && !$page.error}
				<button
					type="button"
					class="load-more"
					aria-disabled={$page.loadingMore || $page.loading}
					onclick={loadMorePage}
				>
					{$page.loadingMore
						? m.dashboard_more_loading()
						: $filters.scope === 'jobs'
							? m.dashboard_more_jobs()
							: m.dashboard_more_tracks()}
				</button>
			{/if}
		</section>
	</main>
</div>

<style>
	.stage {
		max-width: 64rem;
		margin: 0 auto;
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}

	/* Masthead: ident left, the account nav right, the receiver's own status (link tell,
	   and the admin's worker pill) between them, pushed against the nav. */
	.masthead {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		grid-template-areas: 'ident status nav';
		align-items: center;
		gap: var(--space-2) var(--space-5);
	}

	.ident {
		grid-area: ident;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.wordmark {
		font-family: var(--font-mono);
		font-size: var(--fs-lead);
		font-weight: var(--fw-strong);
		letter-spacing: 0.14em;
		line-height: 1.2;
		color: var(--text-primary);
	}

	.status {
		grid-area: status;
		display: flex;
		align-items: baseline;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-4);
	}

	/* F05: the link tell. Linked is quiet (a filled dot, muted); down is the waiting blue
	   with a hollow ring, so it differs in shape as well as hue. Never amber: a link is
	   not a download. */
	.link {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--fs-meta);
		color: var(--text-muted);
	}

	.link-dot {
		width: 0.4375rem;
		height: 0.4375rem;
		border-radius: 50%;
		background: var(--text-muted);
	}

	.link.down {
		color: var(--waiting);
	}

	.lost-short {
		display: none;
	}

	.link.down .link-dot {
		background: transparent;
		border: 1.5px solid var(--waiting);
		animation: link-pulse 2.4s ease-in-out infinite;
	}

	@keyframes link-pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.35;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.link.down .link-dot {
			animation: none;
		}
	}

	.session {
		grid-area: nav;
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: var(--space-1) var(--space-4);
		font-size: var(--fs-detail);
		color: var(--text-muted);
	}

	/* F10 (v40 verdict): a link is marked by its underline, never by amber. Hover only
	   brings the text up to primary. */
	.nav-link {
		color: var(--text-muted);
		text-decoration: underline;
		text-decoration-color: var(--line-control);
		text-underline-offset: 0.3em;
	}

	.nav-link:focus-visible {
		color: var(--text-primary);
		text-decoration-color: currentColor;
	}

	@media (hover: hover) {
		.nav-link:hover {
			color: var(--text-primary);
			text-decoration-color: currentColor;
		}
	}

	/* Wraps rather than truncating (the tooltip holding the full name is unreachable by
	   keyboard and touch), within a cap, so a long email-as-name can't squeeze the
	   masthead's status column off the desktop row. */
	.who {
		max-width: 20rem;
		color: var(--text-primary);
		overflow-wrap: anywhere;
	}

	/* v47: signing out isn't destructive, so it takes the neutral control's hover (DESIGN.md
	   §2), the same as /account's disconnect; it was the fail red. */
	.logout {
		background: transparent;
		border: 1px solid var(--line-control);
		border-radius: 4px;
		padding: var(--space-1) var(--space-3);
		color: var(--text-muted);
		font-size: var(--fs-detail);
		font-weight: var(--fw-medium);
		line-height: 1.25;
		cursor: pointer;
	}

	@media (hover: hover) {
		.logout:hover {
			background: var(--bg-3);
			border-color: var(--text-muted);
			color: var(--text-primary);
		}
	}

	.logout:active {
		background: var(--bg-3);
	}

	.logout-error {
		flex-basis: 100%;
		text-align: right;
		font-size: var(--fs-meta);
		color: var(--fail);
	}

	.logout-error:empty {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
	}

	.main {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}

	.submit-area {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.submit {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
	}

	/* F10 (v40 verdict): muted at rest; amber only while a link is actually being sent. */
	.prompt {
		color: var(--text-muted);
		font-weight: var(--fw-strong);
	}

	.prompt.sending {
		color: var(--signal);
	}

	.submit input {
		flex: 1;
		min-width: 0;
		padding: var(--space-3);
	}

	.submit button {
		background: var(--bg-2);
		border: 1px solid var(--line-control);
		border-radius: 4px;
		padding: var(--space-3) var(--space-4);
		font-weight: var(--fw-strong);
		letter-spacing: 0.06em;
		cursor: pointer;
		white-space: nowrap;
	}

	/* F10: no amber and no halo; focus is the global ring alone. */
	@media (hover: hover) {
		.submit button:hover:not(:disabled) {
			background: var(--bg-3);
			border-color: var(--text-muted);
		}
	}

	.submit button:active:not(:disabled) {
		background: var(--bg-3);
	}

	.submit-error {
		min-height: 1.25rem;
		padding: 0 var(--space-4);
		color: var(--fail);
		font-size: var(--fs-detail);
	}

	.submit-error.notice {
		color: var(--text-muted);
	}

	.submit-error:empty {
		min-height: 0;
	}

	.queue {
		display: flex;
		flex-direction: column;
	}

	.job-list {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	/* Loading: three still placeholder rows on the row grid -- no shimmer, the list is
	   seconds away and motion would only add noise. */
	.skeleton {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.skeleton li {
		display: grid;
		grid-template-columns: var(--col-state) minmax(0, 1fr);
		gap: var(--row-gap);
		align-items: center;
		padding: var(--space-4) var(--row-pad-x) var(--space-4) calc(var(--row-pad-x) + var(--row-nest));
		border-bottom: 1px solid var(--line);
	}

	.skeleton li:last-child {
		border-bottom: none;
	}

	.bone {
		display: block;
		height: 0.75rem;
		border-radius: 3px;
		background: var(--bg-3);
	}

	.bone.badge {
		width: 5rem;
	}

	.bone.line {
		width: 60%;
	}

	.skeleton li:nth-child(2) .bone.line {
		width: 45%;
	}

	.skeleton li:nth-child(3) .bone.line {
		width: 70%;
	}

	/* F26: empty and error states that say which case this is and what to do next. */
	.state {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-2);
		padding: var(--space-6) var(--space-5);
	}

	/* A searched link or URI is one unbreakable run; it must wrap, not scroll the page. */
	.state-title,
	.state-text {
		overflow-wrap: anywhere;
	}

	.state-title {
		font-size: var(--fs-title);
		font-weight: var(--fw-medium);
		line-height: 1.3;
	}

	.state-text {
		max-width: 60ch;
		color: var(--text-muted);
	}

	.state[role='alert'] .state-title {
		color: var(--fail);
	}

	.state-action,
	.load-more {
		background: var(--bg-2);
		border: 1px solid var(--line-control);
		border-radius: 4px;
		padding: var(--space-2) var(--space-4);
		font-size: var(--fs-detail);
		font-weight: var(--fw-medium);
		line-height: 1.25;
		color: var(--text-primary);
		cursor: pointer;
	}

	.state-action {
		margin-top: var(--space-2);
	}

	@media (hover: hover) {
		.state-action:hover,
		.load-more:hover:not([aria-disabled='true']) {
			background: var(--bg-3);
			border-color: var(--text-muted);
		}
	}

	.state-action:active,
	.load-more:active:not([aria-disabled='true']) {
		background: var(--bg-3);
	}

	/* v47: on the row grid, its edge on the rows' state column (where a job's badge starts),
	   rather than a free 16px inset. */
	.load-more {
		margin: var(--space-3) var(--row-pad-x) var(--space-3) calc(var(--row-pad-x) + var(--row-nest));
		align-self: flex-start;
		color: var(--text-muted);
	}

	.more-error {
		margin: var(--space-3) var(--row-pad-x) 0 calc(var(--row-pad-x) + var(--row-nest));
		color: var(--fail);
		font-size: var(--fs-detail);
	}

	/* aria-disabled, not disabled: disabling the focused button would drop focus to the
	   page, and this button is also how a failed page is retried (v41's JobTrackList fix).
	   v47: dimmed text and edge, not opacity (an opacity-faded control drops under 4.5:1). */
	.load-more[aria-disabled='true'] {
		border-color: var(--line);
		color: var(--text-dim);
		cursor: default;
	}

	.track-group {
		border-bottom: 1px solid var(--line);
	}

	.track-group:last-child {
		border-bottom: none;
	}

	.group-header {
		display: grid;
		grid-template-columns: var(--col-state) minmax(0, max-content) minmax(0, auto);
		column-gap: var(--row-gap);
		align-items: baseline;
		padding: var(--space-3) var(--row-pad-x) var(--space-2) calc(var(--row-pad-x) + var(--row-nest));
	}

	/* v47: two lines before it is cut, as a job row's title (JobRow.svelte). */
	.group-header .title {
		min-width: 0;
		overflow: hidden;
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		overflow-wrap: anywhere;
		font-weight: var(--fw-medium);
	}

	.group-header .source-type {
		padding-left: var(--cell-inset);
		color: var(--text-muted);
		font-size: var(--fs-label);
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}

	/* Shares the line with the title; a long owner (an email) ellipsizes rather than
	   crushing it. */
	.group-header .owner {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--text-muted);
		font-size: var(--fs-meta);
	}

	/* The same nesting as an open job's tracks (JobTrackList.svelte): one lead column in,
	   hanging off a rail where the job row's chevron would be. */
	.rows {
		position: relative;
		list-style: none;
		margin: 0;
		padding: 0 0 0 calc(var(--row-pad-x) + var(--row-nest));
	}

	.rows::before {
		content: '';
		position: absolute;
		top: 0;
		bottom: var(--space-3);
		left: calc(var(--row-pad-x) + var(--col-lead) / 2);
		width: 1px;
		background: var(--line-bright);
	}

	/* F32: finger-sized targets on touch screens, whatever the width. */
	@media (pointer: coarse) {
		.logout,
		.state-action,
		.load-more,
		.submit button,
		.submit input {
			min-height: 2.75rem;
		}

		/* v47: wide as well as tall; Sans made "fiók" a 21px-wide target. */
		.nav-link {
			display: inline-flex;
			align-items: center;
			justify-content: center;
			min-height: 2.75rem;
			min-width: 2.75rem;
		}
	}

	/* Tablet (F37): the masthead keeps ident and nav on one line and drops the status to
	   its own line under them, left-aligned under the ident, instead of squeezing three columns. */
	@media (max-width: 63.9375em) {
		.masthead {
			grid-template-columns: auto minmax(0, 1fr);
			grid-template-areas:
				'ident nav'
				'status status';
		}

		.status {
			justify-content: flex-start;
		}
	}

	/* Phone (F15): about a screen of chrome before the first job came down to the header
	   on two lines (ident + link tell, then the nav in one row), tighter page gutters, and
	   the controls' own trimmed rows. */
	@media (max-width: 40em) {
		.stage {
			padding: var(--space-4);
			gap: var(--space-4);
		}

		.main {
			gap: var(--space-4);
		}

		.masthead {
			grid-template-columns: auto minmax(0, 1fr);
			grid-template-areas:
				'ident status'
				'nav nav';
			align-items: start;
		}

		.wordmark {
			white-space: nowrap;
		}

		.ident .label {
			display: none;
		}

		.status {
			flex-direction: column;
			align-items: flex-end;
			gap: var(--space-1);
			text-align: right;
		}

		.session {
			justify-content: flex-start;
			gap: var(--space-1) var(--space-3);
		}

		.logout {
			margin-left: auto;
		}

		/* One line on a phone, where the short form fits; the desktop sentence may wrap in its
		   column rather than run under the nav. */
		.link {
			white-space: nowrap;
		}

		.lost-full {
			display: none;
		}

		.lost-short {
			display: inline;
		}

		/* The phone's rows stack with no state column: back to the row's own inset. */
		.load-more,
		.more-error {
			margin-left: var(--row-pad-x);
		}

		.submit {
			padding: var(--space-2) var(--space-3);
			gap: var(--space-2);
		}

		.submit input {
			padding: var(--space-2) var(--space-3);
		}

		.submit button {
			padding: var(--space-2) var(--space-3);
		}

		.state {
			padding: var(--space-5) var(--space-4);
		}

		/* Type and owner on the first line, the whole title on the second, as JobRow's
		   phone stack does; a long owner never takes the title's width. */
		.group-header {
			grid-template-columns: minmax(0, max-content) minmax(0, 1fr);
		}

		.group-header .source-type {
			grid-column: 1;
			grid-row: 1;
			padding-left: 0;
		}

		.group-header .owner {
			grid-column: 2;
			grid-row: 1;
		}

		.group-header .title {
			grid-column: 1 / -1;
			grid-row: 2;
		}
	}
</style>
