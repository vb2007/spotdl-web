<script lang="ts">
	import { tick } from 'svelte';
	import * as api from '$lib/api';
	import { queue } from '$lib/stores/queue';
	import { link } from '$lib/stores/link';
	import { confirmAction, keepFocus } from '$lib/stores/confirm';
	import { failedRowNotices, rowNotices, showRowNotice } from '$lib/stores/rowNotices';
	import JobTrackList from '$lib/components/JobTrackList.svelte';
	import { kbRow, rowItemById } from '$lib/keyboard/lists';
	import type { Job, JobLifecycle, JobSourceType } from '$lib/api';
	import * as m from '$lib/paraglide/messages';
	import { errorText } from '$lib/i18n/errors';
	import { counted, formatDateTime, formatNumber, keepReadings } from '$lib/i18n/format';
	import { jobStatusLabel } from '$lib/i18n/labels';

	// v54: `all` and `others` both show rows that can be someone else's, so both name the owner.
	// `own` (U1): whether the job is the viewer's; only their own may read as receiving (amber).
	let {
		job,
		view,
		isAdmin,
		own = true
	}: { job: Job; view: api.View; isAdmin: boolean; own?: boolean } = $props();

	const { expanded } = queue;
	let isOpen = $derived(job.id in $expanded);

	// In-flight controls (cancel/bump/priority) only make sense while the job still has
	// somewhere to go; showing them on a settled/failed/cancelled row invites exactly the
	// backend footgun `cancel_job` has (it unconditionally sets `Job.state = CANCELLED`
	// regardless of track states) -- never calling cancel on those lifecycles from the UI
	// avoids ever hitting it, without needing a backend change out of this version's scope.
	const IN_FLIGHT_LIFECYCLES = new Set<JobLifecycle>(['expanding', 'active', 'waiting']);
	const ARCHIVABLE_LIFECYCLES = new Set<JobLifecycle>(['settled', 'failed', 'cancelled']);

	const JOB_STATUS_COND: Record<string, string> = {
		expanding: 'cond-live',
		active: 'cond-live',
		waiting: 'cond-waiting',
		'settled:complete': 'cond-settled',
		'settled:partial': 'cond-fail',
		cancelled: 'cond-idle',
		failed: 'cond-fail'
	};

	let statusToken = $derived(api.statusKey(job.status));
	let badgeLabel = $derived(jobStatusLabel(statusToken));
	// v42 (F28): red is for a real gap. A job that is partial only because its owner
	// cancelled tracks has nothing missing they didn't choose, so it reads muted.
	// v47 (F04/F05, DESIGN.md §2): amber says something is receiving right now. An active job
	// is mostly tracks queued behind the one download the worker runs at a time (or held by
	// the breaker), so it is amber only while one of its own tracks is downloading; and
	// nothing is while `/`'s link is down, since the row is a snapshot that no longer updates.
	// v54 (U1): and only on the viewer's own job; another user's reads as idle, in every view.
	let receiving = $derived(
		own &&
			$link === 'live' &&
			(statusToken === 'expanding' || (job.track_counts.downloading ?? 0) > 0)
	);
	let cond = $derived(
		statusToken === 'settled:partial' && !(job.track_counts.lookup_failed ?? 0)
			? 'cond-idle'
			: (statusToken === 'active' || statusToken === 'expanding') && !receiving
				? 'cond-idle'
				: (JOB_STATUS_COND[statusToken] ?? 'cond-idle')
	);
	// v42 (F28): with no tracks read yet the backend falls back to the link itself; show it
	// as the address it is, not as a bold title.
	let titleIsUrl = $derived(job.title === job.source_url);
	// v42 (F28): a one-track job's count line only repeats its badge when the badge names
	// the track's own bucket. Where they differ (a partial job, a job cancelled after its
	// track completed, a stale row), the line stays: colour alone mustn't say it (1.4.1).
	let badgeSaysTrack = $derived.by(() => {
		const c = job.track_counts;
		if ((c.completed ?? 0) + (c.skipped_duplicate ?? 0) === 1)
			return statusToken === 'settled:complete';
		if ((c.pending ?? 0) + (c.queued ?? 0) + (c.downloading ?? 0) === 1)
			return statusToken === 'active';
		if ((c.waiting ?? 0) === 1) return statusToken === 'waiting';
		return false;
	});
	// v46: what kind of link the job is, in words (the API's own value is a machine key).
	const SOURCE_TYPE_LABEL: Record<JobSourceType, () => string> = {
		track: m.job_source_track,
		album: m.job_source_album,
		playlist: m.job_source_playlist,
		artist: m.job_source_artist,
		search: m.job_source_search
	};

	let toggleButton: HTMLButtonElement | undefined = $state();
	let destroyed = false;
	$effect(() => () => {
		destroyed = true;
	});
	let showInFlight = $derived(IN_FLIGHT_LIFECYCLES.has(job.status.lifecycle));
	// v63: a watched job is never archived (owner's decision): stop watching it first.
	let showArchive = $derived(
		job.archived_at === null &&
			job.watch_interval_hours === null &&
			ARCHIVABLE_LIFECYCLES.has(job.status.lifecycle)
	);

	interface Segment {
		cond: string;
		n: number;
	}

	let segments = $derived.by((): Segment[] => {
		const c = job.track_counts;
		// v47: only a downloading track is the live segment; pending and queued are idle, as
		// their own rows read (DESIGN.md §2's idle condition).
		const downloading = c.downloading ?? 0;
		const lined = (c.pending ?? 0) + (c.queued ?? 0);
		const settled = (c.completed ?? 0) + (c.skipped_duplicate ?? 0);
		const waiting = c.waiting ?? 0;
		const fail = c.lookup_failed ?? 0;
		const idle = c.cancelled ?? 0;
		return [
			{ cond: $link === 'live' && own ? 'cond-live' : 'cond-idle', n: downloading },
			{ cond: 'cond-idle', n: lined },
			{ cond: 'cond-waiting', n: waiting },
			{ cond: 'cond-settled', n: settled },
			{ cond: 'cond-fail', n: fail },
			{ cond: 'cond-idle', n: idle }
		].filter((s) => s.n > 0);
	});
	let totalTracks = $derived(segments.reduce((sum, s) => sum + s.n, 0));

	let breakdown = $derived.by((): string => {
		const c = job.track_counts;
		const active = (c.pending ?? 0) + (c.queued ?? 0) + (c.downloading ?? 0);
		const settled = (c.completed ?? 0) + (c.skipped_duplicate ?? 0);
		const waiting = c.waiting ?? 0;
		const fail = c.lookup_failed ?? 0;
		const idle = c.cancelled ?? 0;
		const parts: string[] = [];
		if (settled) parts.push(m.job_count_done({ count: formatNumber(settled) }));
		if (active) parts.push(m.job_count_active({ count: formatNumber(active) }));
		if (waiting) parts.push(m.job_count_waiting({ count: formatNumber(waiting) }));
		if (fail) parts.push(m.job_count_not_found({ count: formatNumber(fail) }));
		if (idle) parts.push(m.job_count_cancelled({ count: formatNumber(idle) }));
		return parts.length ? parts.join(' · ') : '—';
	});
	// v41: the visible copy wraps only between parts ("120 done · 3 waiting"), never
	// inside one, so every count stays readable in the fixed progress column.
	let breakdownVisible = $derived(keepReadings(breakdown));

	function showNotice(text: string, failed = false) {
		showRowNotice(`job:${job.id}`, text, failed);
	}

	// v43 (F08): a cancelled track can't be retried, so cancelling asks first.
	// One question and its cancel at a time: a second press meanwhile is ignored.
	// v45: a row remounted while its question was open (a reload) is a new element: focus
	// goes to the same job's row again, by id, and only then to the list's heading.
	const remounted = () => rowItemById(job.id) ?? document.getElementById('queue-heading');

	let handleCancelRunning = false;
	async function handleCancel() {
		if (handleCancelRunning) return;
		handleCancelRunning = true;
		try {
			await handleCancelFlow();
		} finally {
			handleCancelRunning = false;
		}
	}

	async function handleCancelFlow() {
		const session = queue.getResetCount();
		const confirmed = await confirmAction({
			title: m.job_cancel_title(),
			subject: job.title,
			subjectIsAddress: titleIsUrl,
			body: m.job_cancel_body(),
			confirmLabel: m.job_cancel_confirm(),
			cancelLabel: m.job_cancel_keep()
		});
		// Kept or Esc: the cancel button may have gone meanwhile (the job finished), or the whole
		// row did (remounted by a list reload).
		if (!confirmed) return keepFocus(destroyed ? remounted() : toggleButton);
		// Another identity took over meanwhile: this answer belongs to the previous session.
		if (queue.getResetCount() !== session) return;
		// A remounted row's button is gone: focus goes to the list instead. Its notice is
		// module-level, so the remounted row shows it.
		const landing = () => (destroyed ? remounted() : toggleButton);
		// v56 (A1): the server decides. The question can stay open while the job finishes, and
		// cancel_job then answers 409 `job_not_cancellable` and leaves the finished job as it is
		// (before v56 it relabelled it "cancelled", so this row re-read the job first).
		try {
			await queue.cancelJob(job.id);
		} catch (err) {
			// A session reset meanwhile: the answer belongs to the previous identity.
			if (queue.getResetCount() === session) {
				if (err instanceof api.ApiError && err.code === 'job_not_cancellable')
					showNotice(m.job_notice_not_cancelled());
				else showNotice(errorText(err, m.job_notice_cancel_failed), true);
			}
		}
		// The cancel button is gone with the in-flight controls: land on the row itself.
		await keepFocus(landing());
	}

	// v47: each answer is shown only to the session that asked (the reset count, as cancel's):
	// a late one after a sign-out must not land on the next identity's row.
	async function handleBump() {
		const session = queue.getResetCount();
		try {
			await queue.bumpJob(job.id);
			if (queue.getResetCount() === session) showNotice(m.job_notice_bumped());
		} catch (err) {
			if (queue.getResetCount() === session)
				showNotice(errorText(err, m.job_notice_bump_failed), true);
		}
	}

	async function handlePriority(value: string) {
		const priority = Number.parseInt(value, 10);
		if (Number.isNaN(priority)) return;
		const session = queue.getResetCount();
		try {
			await queue.setJobPriority(job.id, priority);
		} catch (err) {
			if (queue.getResetCount() === session)
				showNotice(errorText(err, m.job_notice_priority_failed), true);
		}
	}

	async function handleArchive() {
		const session = queue.getResetCount();
		try {
			await queue.archiveJobs({ jobIds: [job.id] });
		} catch (err) {
			if (queue.getResetCount() === session)
				showNotice(errorText(err, m.job_notice_archive_failed), true);
		}
	}

	// ---- v63: watch, "check now" and "retry failed" (this block and the markup block below
	// are v63's; v64's export control keeps to its own). Offered while the row is open, as its
	// keyboard reach is (lists.ts), on a job whose link has been read and that isn't archived.
	let actionable = $derived(job.state === 'expanded' && job.archived_at === null);
	// Owner's decision: a search re-run would add a different song as "new"; links only.
	let checkable = $derived(actionable && job.source_type !== 'search');
	let watchable = $derived(api.WATCHABLE_SOURCE_TYPES.has(job.source_type));
	let watched = $derived(job.watch_interval_hours !== null);
	// Stopping a watch stays possible on a job that can no longer start one (archived since).
	let showWatch = $derived(watchable && (actionable || watched));
	let waitingCount = $derived(job.track_counts.waiting ?? 0);
	let notFoundCount = $derived(job.track_counts.lookup_failed ?? 0);
	let showRetryFailed = $derived(actionable && waitingCount > 0);
	// The override of not-found's terminal rule is the admin's alone; absent for anyone else.
	let showRetryNotFound = $derived(isAdmin && actionable && notFoundCount > 0);

	const WATCH_LABEL: Record<number, () => string> = {
		[api.WATCH_INTERVALS.daily]: m.job_watch_daily,
		[api.WATCH_INTERVALS.weekly]: m.job_watch_weekly,
		[api.WATCH_INTERVALS.monthly]: m.job_watch_monthly
	};
	const intervalLabel = (hours: number) =>
		WATCH_LABEL[hours]?.() ?? m.job_watch_hours({ hours: formatNumber(hours) });
	// An interval set through the API that the menu doesn't offer is still shown as chosen.
	let watchOptions = $derived.by((): number[] => {
		const offered: number[] = Object.values(api.WATCH_INTERVALS);
		const current = job.watch_interval_hours;
		return current !== null && !offered.includes(current) ? [...offered, current] : offered;
	});
	// On the browser's clock (v56, A7): the server's may be ahead or behind. Re-read every
	// half minute while watched, so "next <time>" turns into "checking soon" once it's passed.
	let clockNow = $state(Date.now());
	$effect(() => {
		if (!watched) return;
		const timer = setInterval(() => (clockNow = Date.now()), 30_000);
		return () => clearInterval(timer);
	});
	let nextCheckDue = $derived(
		job.next_expand_at !== null && Date.parse(api.serverToLocal(job.next_expand_at)) <= clockNow
	);
	// A server timestamp, placed on the browser's clock as `nextCheckDue` reads it (v56, A7).
	const shortDate = (value: string) =>
		formatDateTime(api.serverToLocal(value), {
			month: 'short',
			day: 'numeric',
			hour: 'numeric',
			minute: '2-digit'
		});

	// One save at a time, and the last choice wins (DESIGN.md's save model, v62): arrowing
	// through the closed menu fires a change per step, and only the one it stops on is saved.
	// Afterwards the menu shows what the server has, a failed save included.
	let watchSelect: HTMLSelectElement | undefined = $state();
	let watchBusy = false;
	let watchWanted: { hours: number | null } | null = null;
	// The watch as last asked for, while a save is still answering: `w` toggles from it, so two
	// quick presses cancel out instead of both asking for "daily".
	let watchRequested: { hours: number | null } | null = null;
	async function handleWatch(intervalHours: number | null) {
		watchWanted = { hours: intervalHours };
		watchRequested = { hours: intervalHours };
		if (watchBusy) return;
		watchBusy = true;
		const session = queue.getResetCount();
		try {
			while (watchWanted !== null) {
				const { hours } = watchWanted;
				watchWanted = null;
				try {
					const updated = await queue.setJobWatch(job.id, hours);
					if (queue.getResetCount() !== session) return;
					if (watchWanted !== null) continue;
					if (updated.watch_interval_hours === null) showNotice(m.job_notice_unwatched());
					else
						showNotice(
							m.job_notice_watching({
								interval: intervalLabel(updated.watch_interval_hours),
								time: updated.next_expand_at ? shortDate(updated.next_expand_at) : ''
							})
						);
				} catch (err) {
					if (queue.getResetCount() !== session) return;
					watchWanted = null;
					showNotice(errorText(err, m.job_notice_watch_failed), true);
				}
			}
		} finally {
			watchBusy = false;
			watchWanted = null;
			watchRequested = null;
			await tick();
			if (watchSelect)
				watchSelect.value =
					job.watch_interval_hours === null ? '' : String(job.watch_interval_hours);
		}
	}

	let checking = false;
	async function handleCheckNow() {
		// A second press while the first is answering would only read "already being checked".
		if (checking) return;
		checking = true;
		const session = queue.getResetCount();
		try {
			await queue.reexpandJob(job.id);
			if (queue.getResetCount() === session) showNotice(m.job_notice_checking());
		} catch (err) {
			if (queue.getResetCount() !== session) return;
			// A check already queued or running is the outcome asked for, not a failure.
			if (err instanceof api.ApiError && err.code === 'reexpand_running')
				showNotice(m.job_notice_checking());
			else showNotice(errorText(err, m.job_notice_check_failed), true);
		} finally {
			checking = false;
		}
	}

	// One request at a time, in order: a confirmed "retry not found" pressed while "retry
	// waiting" is answering runs after it, never dropped.
	let retryQueue: Promise<void> = Promise.resolve();
	function handleRetryFailed(includeNotFound = false): Promise<void> {
		retryQueue = retryQueue.then(() => retryFailedOnce(includeNotFound));
		return retryQueue;
	}

	async function retryFailedOnce(includeNotFound: boolean) {
		const session = queue.getResetCount();
		try {
			const result = await queue.retryFailedTracks(job.id, includeNotFound);
			if (queue.getResetCount() !== session) return;
			const parts: string[] = [];
			if (result.retried > 0 && result.cooldown > 0)
				parts.push(m.job_notice_retry_partly(counted(result.retried)));
			else if (result.retried > 0)
				parts.push(
					result.breaker_held
						? m.job_notice_retried_held(counted(result.retried))
						: m.job_notice_retried(counted(result.retried))
				);
			else if (result.cooldown > 0) parts.push(m.job_notice_retry_cooldown());
			if (result.overridden > 0) parts.push(m.job_notice_overridden(counted(result.overridden)));
			if (parts.length) showNotice(parts.join(' · '));
		} catch (err) {
			if (queue.getResetCount() === session)
				showNotice(errorText(err, m.job_notice_retry_failed), true);
		}
	}

	// Not found is terminal by rule: putting those tracks back asks first (v43's dialog).
	let notFoundAsking = false;
	let retryNotFoundButton: HTMLButtonElement | undefined = $state();
	async function handleRetryNotFound() {
		if (notFoundAsking) return;
		notFoundAsking = true;
		try {
			const session = queue.getResetCount();
			const confirmed = await confirmAction({
				title: m.job_retry_not_found_title(),
				subject: job.title,
				subjectIsAddress: titleIsUrl,
				// The same request makes the waiting tracks due too: the question says so.
				body: [
					m.job_retry_not_found_body(counted(notFoundCount)),
					...(waitingCount > 0 ? [m.job_retry_not_found_also_waiting(counted(waitingCount))] : [])
				].join(' '),
				confirmLabel: m.job_retry_not_found_confirm(),
				cancelLabel: m.job_retry_not_found_keep()
			});
			const landing = () => (destroyed ? remounted() : (retryNotFoundButton ?? toggleButton));
			if (!confirmed) return keepFocus(landing());
			if (queue.getResetCount() !== session) return;
			await handleRetryFailed(true);
			// The button goes once nothing is left not found: land on the row itself.
			await keepFocus(destroyed ? remounted() : toggleButton);
		} finally {
			notFoundAsking = false;
		}
	}
	// ---- end v63

	// v45: the row's keys (registry's `x`, `a`, `b`, `Shift+B`/`+`, `-`), each only where its
	// button is offered, so a key never does what the row doesn't show.
	// v63: `w` and `Shift+R` likewise, only on an open row (where their controls are).
	const keys = kbRow({
		cancel: () => showInFlight && (handleCancel(), true),
		archive: () =>
			showArchive ? (handleArchive(), true) : job.archived_at !== null && (handleUnarchive(), true),
		bump: () => isAdmin && showInFlight && (handleBump(), true),
		priorityUp: () => isAdmin && showInFlight && (stepPriority(1), true),
		priorityDown: () => isAdmin && showInFlight && (stepPriority(-1), true),
		watch: () =>
			isOpen &&
			showWatch &&
			(watched || actionable) &&
			(handleWatch(
				(watchRequested ? watchRequested.hours !== null : watched)
					? null
					: api.WATCH_INTERVALS.daily
			),
			true),
		retryFailed: () => isOpen && showRetryFailed && (handleRetryFailed(), true)
	});

	// One step at a time: the row's priority only moves once the server answers, so a quick
	// second press would otherwise send the same value again and lose a step.
	let stepping = false;
	async function stepPriority(delta: number) {
		if (stepping) return;
		stepping = true;
		try {
			await handlePriority(String(job.priority + delta));
		} finally {
			stepping = false;
		}
	}

	async function handleUnarchive() {
		const session = queue.getResetCount();
		try {
			await queue.unarchiveJobs([job.id]);
		} catch (err) {
			if (queue.getResetCount() === session)
				showNotice(errorText(err, m.job_notice_unarchive_failed), true);
		}
	}
</script>

<li class="job" aria-labelledby="job-title-{job.id}" data-kb-row={job.id} {@attach keys}>
	<!-- v63: an open row's actions take a line of their own (open, it offers watch, check now and
	     retry failed too, which would squeeze the title to a sliver). -->
	<div class="row" class:open={isOpen}>
		<!-- v41 (F16): no aria-label, so the button's name is what it shows (status, title,
		     type, owner; WCAG 2.5.3), and aria-controls ties it to the track list (F29). -->
		<button
			bind:this={toggleButton}
			type="button"
			class="toggle"
			data-kb-item
			aria-expanded={isOpen}
			aria-controls="job-tracks-{job.id}"
			onclick={() => queue.toggleExpand(job.id)}
		>
			<span class="chevron" aria-hidden="true"></span>
			<span class="badge-cell"><span class="badge {cond} mono">{badgeLabel}</span></span>
			<span class="title" class:address={titleIsUrl} id="job-title-{job.id}" title={job.title}
				>{job.title}</span
			>
			<span class="tags">
				<span class="source-type mono"
					>{SOURCE_TYPE_LABEL[job.source_type]?.() ?? job.source_type}</span
				>
				{#if view !== 'mine'}
					<span class="owner mono" title={job.owner_email}
						>{api.displayName(job.owner_username, job.owner_email)}</span
					>
				{/if}
			</span>
		</button>

		<div class="progress">
			{#if totalTracks > 0}
				<div class="bar" role="img" aria-label={m.job_progress_label({ breakdown })}>
					{#each segments as seg, i (i)}
						<span
							class="seg {seg.cond}"
							style:flex-grow={seg.n}
							style:flex-basis={`${(seg.n / totalTracks) * 100}%`}
						></span>
					{/each}
				</div>
			{/if}
			<!-- v42 (F28): see badgeSaysTrack. -->
			<!-- v47: a job with no tracks (expanding, or failed before any was read) shows no count:
			     a lone "—" took a line of its own on a phone, like the bar DESIGN.md §6 already drops. -->
			{#if totalTracks > 0 && (totalTracks !== 1 || !badgeSaysTrack)}
				<span class="breakdown mono">{breakdownVisible}</span>
			{/if}
			{#if watched}
				<!-- v63: the watch and its next check, on a line of its own (in the title's tags it was
				     cut to "watched…"). -->
				<span class="breakdown mono"
					>{nextCheckDue || job.next_expand_at === null
						? m.job_watched_soon()
						: m.job_watched_next({ time: keepReadings(shortDate(job.next_expand_at)) })}</span
				>
			{/if}
			{#if job.new_tracks > 0}
				<!-- v63: what re-expansion has added since the job was submitted. -->
				<span class="breakdown mono"
					>{m.job_new_since({
						...counted(job.new_tracks),
						date: formatDateTime(job.created_at, { month: 'short', day: 'numeric' })
					})}</span
				>
			{/if}
		</div>

		<div class="row-actions">
			<!-- v47 (owner's call): priority and bump are the admin's. The queue's order is shared,
			     operator detail (v39 outcome 3); a non-admin's in-flight job offers cancel only. -->
			{#if showInFlight && isAdmin}
				<label class="priority mono">
					{m.job_priority()}
					<input
						type="number"
						class="priority-input"
						value={job.priority}
						aria-label={m.job_priority_of({ title: job.title })}
						onchange={(e) => handlePriority(e.currentTarget.value)}
						onkeydown={(e) => {
							// v45: Esc backs out of the field (the registry then closes the row):
							// a half-typed value is put back first, so leaving doesn't save it.
							if (e.key === 'Escape') e.currentTarget.value = String(job.priority);
						}}
					/>
				</label>
				<button
					type="button"
					class="action"
					aria-label={m.job_bump_label({ title: job.title })}
					onclick={handleBump}>{m.job_bump()}</button
				>
			{/if}
			{#if showInFlight}
				<button
					type="button"
					class="action danger"
					aria-label={m.job_cancel_label({ title: job.title })}
					onclick={handleCancel}>{m.job_cancel()}</button
				>
			{/if}
			<!-- v63: watch, "check now" and "retry failed", while the row is open. -->
			{#if isOpen}
				{#if showRetryFailed}
					<button
						type="button"
						class="action"
						aria-label={m.job_retry_failed_label({ ...counted(waitingCount), title: job.title })}
						onclick={() => handleRetryFailed()}>{m.job_retry_failed(counted(waitingCount))}</button
					>
				{/if}
				{#if showRetryNotFound}
					<button
						bind:this={retryNotFoundButton}
						type="button"
						class="action"
						aria-label={m.job_retry_not_found_label({
							...counted(notFoundCount),
							title: job.title
						})}
						onclick={handleRetryNotFound}>{m.job_retry_not_found(counted(notFoundCount))}</button
					>
				{/if}
				{#if checkable}
					<button
						type="button"
						class="action"
						aria-label={m.job_check_now_label({ title: job.title })}
						onclick={handleCheckNow}>{m.job_check_now()}</button
					>
				{/if}
				{#if showWatch}
					<label class="watch mono">
						{m.job_watch()}
						<select
							bind:this={watchSelect}
							class="watch-select"
							aria-label={m.job_watch_of({ title: job.title })}
							value={job.watch_interval_hours === null ? '' : String(job.watch_interval_hours)}
							onchange={(e) => {
								const value = e.currentTarget.value;
								handleWatch(value === '' ? null : Number(value));
							}}
						>
							<option value="">{m.job_watch_off()}</option>
							{#if actionable || watched}
								{#each watchOptions as hours (hours)}
									<option
										value={String(hours)}
										disabled={!actionable && hours !== job.watch_interval_hours}
										>{intervalLabel(hours)}</option
									>
								{/each}
							{/if}
						</select>
					</label>
				{/if}
			{/if}
			<!-- end v63 -->
			{#if showArchive}
				<button
					type="button"
					class="action"
					aria-label={m.job_archive_label({ title: job.title })}
					onclick={handleArchive}>{m.job_archive()}</button
				>
			{/if}
			{#if job.archived_at !== null}
				<span class="archived-tag mono">{m.job_archived()}</span>
				<button
					type="button"
					class="action"
					aria-label={m.job_unarchive_label({ title: job.title })}
					onclick={handleUnarchive}>{m.job_unarchive()}</button
				>
			{/if}
		</div>
	</div>

	<p class="notice" class:failed={failedRowNotices.has(`job:${job.id}`)} role="status">
		{rowNotices.get(`job:${job.id}`) ?? ''}
	</p>

	{#if isOpen}
		<JobTrackList
			jobId={job.id}
			{isAdmin}
			elsewhere={!own}
			jobCancelled={job.status.lifecycle === 'cancelled'}
			total={totalTracks}
			unreadable={job.status.lifecycle === 'failed' ? (isAdmin ? (job.error ?? '') : '') : null}
		/>
	{/if}
</li>

<style>
	.job {
		border-bottom: 1px solid var(--line);
	}

	.job:last-child {
		border-bottom: none;
	}

	/* v41: the shared row grid (app.css "Row grid") -- chevron, badge, title, progress,
	   actions. The fixed-width progress column sits last, at the row's right edge, so every
	   job's bar lines up while the title takes whatever its actions don't use; a nested
	   track's state and title land under this row's badge and title (F02). */
	.row {
		display: grid;
		grid-template-columns:
			var(--col-lead) var(--col-state) minmax(0, 1fr) auto
			var(--col-progress);
		column-gap: var(--row-gap);
		row-gap: var(--space-2);
		align-items: center;
		padding: var(--space-3) var(--row-pad-x);
	}

	/* Spans the row's first three columns with the same tokens and gap, so its chevron,
	   badge and title sit exactly on them; the title and its tags share the third. */
	.toggle {
		grid-column: 1 / 4;
		display: grid;
		grid-template-columns: var(--col-lead) var(--col-state) minmax(0, max-content) minmax(0, auto);
		column-gap: var(--row-gap);
		align-items: center;
		min-width: 0;
		background: transparent;
		border: none;
		padding: 0;
		text-align: left;
		cursor: pointer;
		color: inherit;
	}
	/* v42: on the raised faceplate a fill doesn't read, so hover underlines the title, as
	   a track row does. */
	@media (hover: hover) {
		.toggle:hover .title {
			text-decoration: underline;
			text-decoration-color: var(--text-muted);
			text-underline-offset: 0.2em;
		}
	}

	.chevron {
		justify-self: center;
		width: 0.45rem;
		height: 0.45rem;
		border-right: 1.5px solid var(--text-muted);
		border-bottom: 1.5px solid var(--text-muted);
		transform: translateX(-20%) rotate(-45deg);
		transition: transform var(--dur-fast) var(--ease-signal);
	}

	.toggle[aria-expanded='true'] .chevron {
		transform: translateY(-20%) rotate(45deg);
	}

	.badge-cell {
		min-width: 0;
	}

	.badge {
		display: inline-block;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		vertical-align: middle;
		padding: 0.125rem var(--space-2);
		border: 1px solid var(--line);
		border-radius: 3px;
		/* v47: the track state word's size (it was 11px over a 12px state in the same column). */
		font-size: var(--fs-meta);
		letter-spacing: 0.04em;
	}

	/* Title and tags share whatever the toggle has left, so a long owner (an email, when
	   there's no username) ellipsizes instead of crushing the title to nothing. */
	.tags {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		min-width: 0;
		overflow: hidden;
		margin-left: calc(var(--space-2) - var(--row-gap));
	}

	/* v47: a long title takes up to two lines before it is cut (one line cut a 110-character
	   live title at "Live In L…", and the tooltip holding the rest is unreachable by touch
	   and keyboard). Opening the row shows it whole. */
	.title {
		min-width: 0;
		overflow: hidden;
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		overflow-wrap: anywhere;
		font-weight: var(--fw-medium);
	}

	/* The link's tail (the id) is what tells two untitled jobs apart: it wraps rather than
	   ellipsizing behind a tooltip touch and keyboard can't reach. */
	/* Open, the job shows its whole title. */
	.toggle[aria-expanded='true'] .title {
		display: block;
		-webkit-line-clamp: unset;
		line-clamp: none;
	}

	/* The whole link, never clamped: its tail (the id) is what tells two untitled jobs apart. */
	.title.address {
		display: block;
		-webkit-line-clamp: unset;
		line-clamp: none;
		white-space: normal;
		overflow-wrap: anywhere;
		font-family: var(--font-mono);
		font-size: var(--fs-meta);
		font-weight: var(--fw-regular);
		color: var(--text-muted);
	}

	.source-type {
		flex-shrink: 0;
		color: var(--text-muted);
		font-size: var(--fs-label);
		text-transform: uppercase;
	}

	.owner {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--text-muted);
		font-size: var(--fs-meta);
	}

	.progress {
		grid-column: 5;
		grid-row: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.bar {
		display: flex;
		height: 0.5rem;
		border-radius: 3px;
		overflow: hidden;
		background: var(--bg-0);
		border: 1px solid var(--line);
	}

	.seg.cond-live {
		background: var(--signal);
	}
	.seg.cond-waiting {
		background: var(--waiting);
	}
	.seg.cond-settled {
		background: var(--settled);
	}
	.seg.cond-fail {
		background: var(--fail);
	}
	.seg.cond-idle {
		background: var(--line-bright);
	}

	.breakdown {
		color: var(--text-muted);
		font-size: var(--fs-meta);
	}

	.row-actions {
		grid-column: 4;
		grid-row: 1;
		display: flex;
		align-items: center;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	/* v63: open, the actions drop under the title, as the tablet band's always do (the bands
	   below place them themselves, so this is the wide screen's alone). */
	@media (min-width: 60.0625em) {
		.row.open .row-actions {
			grid-column: 3 / -1;
			grid-row: 2;
			justify-content: flex-start;
		}

		.row.open .row-actions:empty {
			display: none;
		}
	}

	.priority {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--fs-label);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.priority-input {
		width: 3.5rem;
		background: var(--bg-0);
		border: 1px solid var(--line-control);
		border-radius: 4px;
		padding: var(--space-1) var(--space-2);
		color: var(--text-primary);
		font-family: var(--font-mono);
		font-size: var(--fs-detail);
	}

	.action {
		background: var(--bg-2);
		border: 1px solid var(--line-control);
		border-radius: 4px;
		padding: var(--space-1) var(--space-3);
		font-family: var(--font-sans);
		font-size: var(--fs-detail);
		font-weight: var(--fw-medium);
		line-height: 1.25;
		color: var(--text-muted);
		cursor: pointer;
		white-space: nowrap;
	}

	/* v47: the one hover of a neutral control (DESIGN.md §2): --bg-3 under a --text-muted edge,
	   and only where a pointer hovers (on touch, a tapped button used to keep it). Focus is the
	   global ring alone; pressed is the --bg-3 fill. */
	@media (hover: hover) {
		.action:hover {
			background: var(--bg-3);
			border-color: var(--text-muted);
			color: var(--text-primary);
		}
	}

	.action:active {
		background: var(--bg-3);
	}

	/* Destructive: outlined in the fail tone at rest, full red only when about to be used
	   -- the same treatment as TrackRow's "cancel track". */
	.action.danger {
		background: transparent;
		border-color: var(--fail-edge);
	}

	.action.danger:focus-visible,
	.action.danger:active {
		background: transparent;
		border-color: var(--fail);
		color: var(--fail);
	}

	@media (hover: hover) {
		.action.danger:hover {
			background: transparent;
			border-color: var(--fail);
			color: var(--fail);
		}
	}

	/* v63: the watch interval, labelled like priority (a control's word in the label face). */
	.watch {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--fs-label);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.watch-select {
		background: var(--bg-0);
		border: 1px solid var(--line-control);
		border-radius: 4px;
		padding: var(--space-1) var(--space-2);
		color: var(--text-primary);
		font-family: var(--font-sans);
		font-size: var(--fs-detail);
		text-transform: none;
		letter-spacing: normal;
	}

	.archived-tag {
		font-size: var(--fs-label);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.notice {
		margin: 0;
		padding: 0 var(--row-pad-x) var(--space-2) calc(var(--row-pad-x) + var(--row-nest));
		color: var(--waiting);
		font-size: var(--fs-detail);
	}

	/* v47: a failure reads as one ("Couldn't archive: …"), not in the scheduling blue. */
	.notice.failed {
		color: var(--fail);
	}

	/* Empty, it stays in the accessibility tree (a status region inserted together with
	   its text is often not announced) but takes no room. */
	.notice:empty {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
	}

	/* Tablet: the actions drop to a second line under the title instead of squeezing it
	   (F37, for this row; v42 owns the page breakpoint). */
	@media (max-width: 60em) {
		.row {
			grid-template-columns: var(--col-lead) var(--col-state) minmax(0, 1fr) 10rem;
		}

		.progress {
			grid-column: 4;
		}

		.row-actions {
			grid-column: 3 / -1;
			grid-row: 2;
			justify-content: flex-start;
		}

		.row-actions:empty {
			display: none;
		}
	}

	/* Phone (v39.1 F01, redesigned in v41): one line for chevron, badge and title, then
	   the bar with its breakdown, then the actions, all hanging off the same second
	   column the nested tracks indent to. No flex-basis sizes a height here any more:
	   the stack is grid rows, each as tall as its content. */
	/* v42 (F32): a finger needs a 44px target; a mouse keeps the dense row. */
	@media (pointer: coarse) {
		.toggle,
		.action,
		.priority-input,
		.watch-select {
			min-height: 2.75rem;
		}
	}

	@media (max-width: 40em) {
		.row {
			grid-template-columns: var(--col-lead) minmax(0, 1fr);
		}

		/* Badge and tags on the first line, the whole title width on the second. */
		.toggle {
			grid-column: 1 / -1;
			grid-template-columns: var(--col-lead) auto minmax(0, 1fr);
			grid-template-areas:
				'chevron badge tags'
				'. title title';
		}

		.chevron {
			grid-area: chevron;
		}

		.badge-cell {
			grid-area: badge;
		}

		.tags {
			grid-area: tags;
			margin-left: 0;
			min-width: 0;
			overflow: hidden;
		}

		.title {
			grid-area: title;
		}

		.progress,
		.row-actions {
			grid-column: 2;
			grid-row: auto;
		}
	}
	/* v47: in a forced-colors theme (Windows High Contrast) a bar's fills were dropped to empty
	   outlines; a reading keeps its own colours, as /stats' charts already do. */
	@media (forced-colors: active) {
		.bar {
			forced-color-adjust: none;
		}
	}
</style>
