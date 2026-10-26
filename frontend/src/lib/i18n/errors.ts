import { ApiError } from '$lib/api';
import * as m from '$lib/paraglide/messages';
import { counted, formatNumber } from './format';
import { trackStateLabel } from './labels';
import { formatCountdown } from '$lib/attempts';

/** v46: an API error in the active language, by its stable `code` (backend/app/errors.py),
 * never by matching the English `detail`. A code this table doesn't know (a newer backend, or
 * an error with none, like a hidden admin 404) falls back to `detail` as the server sent it. */

type Params = Record<string, string | number>;

// The settings page's own field labels, so an error names a field exactly as the form does.
const FIELD_LABEL: Record<string, () => string> = {
	library_target_dir: m.settings_library_target_dir,
	library_folder_template: m.settings_library_folder_template,
	library_quarantine_dir: m.settings_library_quarantine_dir,
	alert_spike_threshold: m.settings_alert_spike_threshold,
	alert_spike_window_minutes: m.settings_alert_spike_window,
	alert_beat_stale_seconds: m.settings_alert_beat_stale_after,
	alert_cooldown_minutes: m.settings_alert_cooldown
};

const field = (params: Params) => {
	const name = String(params.field ?? '');
	return FIELD_LABEL[name]?.() ?? name;
};

// v57 (L2): one whole sentence per way two of the sweep's folders can overlap (the backend's
// field, other and relation), so each language words its own grammar.
const PATHS_OVERLAP: Record<string, () => string> = {
	library_target_dir_download_output_dir_equal: m.error_library_paths_library_downloads_equal,
	library_target_dir_download_output_dir_inside: m.error_library_paths_library_downloads_inside,
	library_target_dir_download_output_dir_contains: m.error_library_paths_library_downloads_contains,
	library_quarantine_dir_library_target_dir_equal: m.error_library_paths_quarantine_library_equal,
	library_quarantine_dir_library_target_dir_inside: m.error_library_paths_quarantine_library_inside,
	library_quarantine_dir_library_target_dir_contains:
		m.error_library_paths_quarantine_library_contains,
	library_quarantine_dir_download_output_dir_equal:
		m.error_library_paths_quarantine_downloads_equal,
	library_quarantine_dir_download_output_dir_contains:
		m.error_library_paths_quarantine_downloads_contains
};

const BY_CODE: Record<string, (params: Params) => string> = {
	invalid_credentials: () => m.error_invalid_credentials(),
	not_authenticated: () => m.error_not_authenticated(),
	admin_required: () => m.error_admin_required(),
	job_not_found: () => m.error_job_not_found(),
	// v56: a cancel of something already finished (A1, A2).
	job_not_cancellable: () => m.error_job_not_cancellable(),
	job_cancelled: () => m.error_job_cancelled(),
	archive_nothing_selected: () => m.error_archive_nothing_selected(),
	// The reason is the server's own diagnostic (a bad cursor, an unknown sort), kept as sent.
	invalid_list_params: (p) => m.error_invalid_list_params({ reason: String(p.reason ?? '') }),
	library_sort_running: () => m.error_library_sort_running(),
	library_sort_not_running: () => m.error_library_sort_not_running(),
	library_path_not_absolute: (p) => m.error_library_path_not_absolute({ field: field(p) }),
	library_paths_overlap: (p) =>
		(PATHS_OVERLAP[`${p.field}_${p.other}_${p.relation}`] ?? m.error_library_paths_overlap)(),
	track_not_found: () => m.error_track_not_found(),
	job_archived: () => m.error_job_archived(),
	track_not_retryable: (p) =>
		m.error_track_not_retryable({ state: trackStateLabel(String(p.state)) }),
	track_not_cancellable: (p) =>
		m.error_track_not_cancellable({ state: trackStateLabel(String(p.state)) }),
	// v56 (A8): a non-admin's second "retry now" in one ladder step.
	retry_cooldown: (p) => {
		if (String(p.paused) === 'true') return m.error_retry_cooldown_paused();
		const seconds = Number(p.retry_after ?? 0);
		return seconds > 0
			? m.error_retry_cooldown({ time: formatCountdown(seconds * 1000) })
			: m.error_retry_cooldown_due();
	},
	file_not_found: () => m.error_file_not_found(),
	download_failed: (p) => m.error_download_failed({ status: String(p.status ?? '') }),
	file_empty: () => m.error_file_empty(),
	proxy_target_exists: (p) =>
		p.source === 'file'
			? m.error_proxy_target_exists_file({ target: String(p.target) })
			: m.error_proxy_target_exists_manual({ target: String(p.target) }),
	proxy_not_found: () => m.error_proxy_not_found(),
	proxy_deleting: () => m.error_proxy_deleting(),
	proxy_url_required: () => m.error_proxy_url_required(),
	proxy_url_invalid: () => m.error_proxy_url_invalid(),
	proxy_url_exists: () => m.error_proxy_url_exists(),
	unsupported_format: (p) => m.error_unsupported_format({ value: String(p.value) }),
	unsupported_bitrate: (p) => m.error_unsupported_bitrate({ value: String(p.value) }),
	setting_blank: (p) => m.error_setting_blank({ field: field(p) }),
	setting_out_of_range: (p) =>
		m.error_setting_out_of_range({
			field: field(p),
			min: formatNumber(Number(p.min)),
			max: formatNumber(Number(p.max))
		}),
	alerts_not_configured: () => m.error_alerts_not_configured(),
	// The reason is the Matrix server's own (redacted) words: shown as sent, untranslated.
	alert_send_failed: (p) => m.error_alert_send_failed({ reason: String(p.reason ?? '') }),
	// v56 (A5): the server's own bound, the /account form's.
	retention_out_of_range: (p) =>
		m.error_retention_out_of_range({
			min: formatNumber(Number(p.min)),
			max: formatNumber(Number(p.max))
		}),
	// v53: keys (/account) and the limits on sign-in and submitting.
	rate_limited: (p) => m.error_rate_limited(counted(Number(p.retry_after ?? 0))),
	api_key_label_invalid: (p) =>
		p.reason === 'character'
			? m.error_api_key_label_characters()
			: m.error_api_key_label_invalid({ max: formatNumber(Number(p.max)) }),
	api_key_limit_reached: (p) => m.error_api_key_limit_reached({ max: formatNumber(Number(p.max)) }),
	api_key_not_found: () => m.error_api_key_not_found(),
	queue_unavailable: () => m.error_queue_unavailable(),
	submit_too_long: (p) => m.error_submit_too_long({ max: formatNumber(Number(p.max)) }),
	request_invalid: () => m.error_request_invalid(),
	server_error: (p) => m.error_server_error({ status: String(p.status ?? '') }),
	request_failed: (p) => m.error_request_failed({ status: String(p.status ?? '') })
};

export function apiErrorText(err: ApiError): string {
	const translate = err.code ? BY_CODE[err.code] : undefined;
	if (translate) return translate(err.params);
	// v47: a 5xx with no code we know (an unhandled exception's JSON `detail`) is still the
	// server's problem in the page's language, never its raw English.
	if (err.status >= 500) return m.error_server_error({ status: String(err.status) });
	return err.message;
}

/** The pattern every catch block uses: an API error in words, anything else (the server
 * unreachable, a thrown TypeError from fetch) as the caller's own fallback sentence. */
export function errorText(
	err: unknown,
	fallback: () => string = m.common_server_unreachable
): string {
	return err instanceof ApiError ? apiErrorText(err) : fallback();
}

/** For a unit test: whether a code has a translation. */
export function knowsCode(code: string): boolean {
	return code in BY_CODE;
}
