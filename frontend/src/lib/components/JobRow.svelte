<script lang="ts">
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
	import { formatNumber, keepReadings } from '$lib/i18n/format';
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
	let showArchive = $derived(
		job.archived_at === null && ARCHIVABLE_LIFECYCLES.has(job.status.lifecycle)
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

	// --- v64: export ------------------------------------------------------------------
	// How many of the job's tracks have a file on disk: the export's own count, read from its
	// HEAD once the job is opened (one request per opening, never one per row), and read
	// again whenever the job's settled tracks change while it's open. A file deleted from disk
	// isn't counted, so a job with none left shows no strip.
	let settledTracks = $derived(
		(job.track_counts.completed ?? 0) + (job.track_counts.skipped_duplicate ?? 0)
	);
	let exportCounts = $state<{ files: number; tracks: number } | null>(null);
	let exportFiles = $derived(exportCounts?.files ?? 0);
	let exportRead = 0;
	$effect(() => {
		// Read on opening and on every change of the settled count; nothing while closed.
		if (!isOpen || settledTracks === 0) {
			exportCounts = null;
			return;
		}
		const read = ++exportRead;
		const session = queue.getResetCount();
		api
			.getJobExportCounts(job.id)
			.then((counts) => {
				if (read === exportRead && queue.getResetCount() === session) exportCounts = counts;
			})
			.catch(() => {
				if (read === exportRead) exportCounts = null;
			});
	});
	let exportProbing = $state<'zip' | 'playlist' | null>(null);

	// v35 (e)'s technique: probe first (a 404, or the zip's 413 over the export limits, shows
	// in the row's notice), then hand the URL to a real browser download, so a multi-gigabyte
	// zip streams straight to disk with the browser's own progress, never through tab memory.
	async function handleExport(kind: 'zip' | 'playlist') {
		if (exportProbing !== null) return;
		const url = kind === 'zip' ? api.jobExportUrl(job.id) : api.jobPlaylistUrl(job.id);
		const session = queue.getResetCount();
		exportProbing = kind;
		try {
			await api.checkJobExport(url);
		} catch (err) {
			if (queue.getResetCount() === session)
				showNotice(errorText(err, m.job_notice_export_failed), true);
			return;
		} finally {
			exportProbing = null;
		}
		if (queue.getResetCount() !== session) return;
		const anchor = document.createElement('a');
		anchor.href = url;
		anchor.download = '';
		document.body.appendChild(anchor);
		anchor.click();
		anchor.remove();
	}
	// --- end v64 ----------------------------------------------------------------------

	// v45: the row's keys (registry's `x`, `a`, `b`, `Shift+B`/`+`, `-`), each only where its
	// button is offered, so a key never does what the row doesn't show.
	const keys = kbRow({
		// v64: `d`, the zip, offered only on an open job with files (the export strip).
		download: () => isOpen && exportFiles > 0 && (handleExport('zip'), true),
		cancel: () => showInFlight && (handleCancel(), true),
		archive: () =>
			showArchive ? (handleArchive(), true) : job.archived_at !== null && (handleUnarchive(), true),
		bump: () => isAdmin && showInFlight && (handleBump(), true),
		priorityUp: () => isAdmin && showInFlight && (stepPriority(1), true),
		priorityDown: () => isAdmin && showInFlight && (stepPriority(-1), true)
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
	<div class="row">
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
		<!-- v64: export. Shown once a file of the job is on disk (see exportCounts). -->
		{#if exportFiles > 0}
			<div class="export" role="group" aria-label={m.job_export_label({ title: job.title })}>
				<span class="export-count mono"
					>{m.job_export_files({
						count: formatNumber(exportFiles),
						total: formatNumber(exportCounts?.tracks ?? totalTracks)
					})}</span
				>
				<button
					type="button"
					class="action"
					aria-label={exportProbing === 'zip'
						? m.job_export_preparing()
						: m.job_export_zip_label({ title: job.title })}
					aria-busy={exportProbing === 'zip'}
					onclick={() => handleExport('zip')}
					>{exportProbing === 'zip' ? m.job_export_preparing() : m.job_export_zip()}</button
				>
				<button
					type="button"
					class="action"
					aria-label={exportProbing === 'playlist'
						? m.job_export_preparing()
						: m.job_export_playlist_label({ title: job.title })}
					aria-busy={exportProbing === 'playlist'}
					onclick={() => handleExport('playlist')}
					>{exportProbing === 'playlist'
						? m.job_export_preparing()
						: m.job_export_playlist()}</button
				>
			</div>
		{/if}
		<!-- end v64 -->
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

	/* v64: the export strip of an open job, hanging off the title column as its tracks do: a
	   reading (how many files there are), then two plain row actions. */
	.export {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
		padding: 0 var(--row-pad-x) var(--space-3) calc(var(--row-pad-x) + var(--row-nest));
	}

	.export-count {
		color: var(--text-muted);
		font-size: var(--fs-meta);
		margin-right: var(--space-1);
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
		.priority-input {
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
		/* v64: the count on a line of its own, then the two actions side by side, sharing the
		   width (a long label, Hungarian's, wraps inside its button instead of pushing the
		   other one to a line of its own). */
		.export-count {
			flex-basis: 100%;
		}

		.export .action {
			flex: 1 1 0;
			white-space: normal;
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
