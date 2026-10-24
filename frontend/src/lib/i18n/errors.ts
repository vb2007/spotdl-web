import { ApiError } from '$lib/api';
import * as m from '$lib/paraglide/messages';
import { counted, formatNumber } from './format';
import { trackStateLabel } from './labels';

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

const BY_CODE: Record<string, (params: Params) => string> = {
	invalid_credentials: () => m.error_invalid_credentials(),
	not_authenticated: () => m.error_not_authenticated(),
	admin_required: () => m.error_admin_required(),
	job_not_found: () => m.error_job_not_found(),
	archive_nothing_selected: () => m.error_archive_nothing_selected(),
	// The reason is the server's own diagnostic (a bad cursor, an unknown sort), kept as sent.
	invalid_list_params: (p) => m.error_invalid_list_params({ reason: String(p.reason ?? '') }),
	library_sort_running: () => m.error_library_sort_running(),
	track_not_found: () => m.error_track_not_found(),
	job_archived: () => m.error_job_archived(),
	track_not_retryable: (p) =>
		m.error_track_not_retryable({ state: trackStateLabel(String(p.state)) }),
	file_not_found: () => m.error_file_not_found(),
	download_failed: (p) => m.error_download_failed({ status: String(p.status ?? '') }),
	file_empty: () => m.error_file_empty(),
	proxy_target_exists: (p) =>
		p.source === 'file'
			? m.error_proxy_target_exists_file({ target: String(p.target) })
			: m.error_proxy_target_exists_manual({ target: String(p.target) }),
	proxy_not_found: () => m.error_proxy_not_found(),
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
	retention_days_invalid: () => m.error_retention_days_invalid(),
	// v53: keys (/account) and the limits on sign-in and submitting.
	rate_limited: (p) => m.error_rate_limited(counted(Number(p.retry_after ?? 0))),
	api_key_label_invalid: (p) => m.error_api_key_label_invalid({ max: formatNumber(Number(p.max)) }),
	api_key_limit_reached: (p) => m.error_api_key_limit_reached({ max: formatNumber(Number(p.max)) }),
	api_key_not_found: () => m.error_api_key_not_found(),
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
