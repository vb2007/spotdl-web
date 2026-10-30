from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StrictBool
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import AppSettings, User, UserSettings
from app.routers.auth import require_admin, require_admin_hidden, require_session
from app.routers.library import check_library_paths
from app.services import alerts, app_settings, downloads, user_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class UpdateOutputSettingsRequest(BaseModel):
    default_format: str | None = None
    default_bitrate: str | None = None
    output_template: str | None = None


class UpdateRetentionRequest(BaseModel):
    retention_days: int | None


# v56 (A5): one day to about a hundred years, as /account allows.
RETENTION_DAYS_MIN = 1
RETENTION_DAYS_MAX = 36500


class UpdateKeyboardRequest(BaseModel):
    keyboard_shortcuts: StrictBool


class UpdateLanguageRequest(BaseModel):
    # v46: the languages the frontend ships message files for (frontend/messages/), or `null`
    # for automatic (the browser's language decides; owner's answer on PR #68). Required (no
    # default), so an empty body is a 422, not a silent reset.
    language: Literal["hu", "en"] | None


class UpdateClockRequest(BaseModel):
    # v46: a pinned time format, or `null` for automatic (the browser's region decides).
    # Required (no default), so an empty body is a 422, not a silent reset.
    clock: Literal["12h", "24h"] | None


class UpdateLibrarySettingsRequest(BaseModel):
    library_target_dir: str | None = None
    library_folder_template: str | None = None
    library_quarantine_enabled: bool | None = None
    library_quarantine_dir: str | None = None


def _output_settings_to_dict(row: AppSettings) -> dict:
    return {
        "default_format": row.default_format,
        "default_bitrate": row.default_bitrate,
        # Informational only -- never accepted by PATCH (see UpdateOutputSettingsRequest
        # and app_settings.py's docstring for why: it's fixed by the container's volume
        # mount at deploy time, not editable at the app level).
        "output_dir": get_settings().download_output_dir,
        "output_template": row.output_template,
    }


@router.get("/output")
def get_output_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    row = app_settings.get_output_settings(db)
    db.commit()
    return _output_settings_to_dict(row)


@router.get("/output/options")
def get_output_options(
    _: User = Depends(require_admin),
) -> dict:
    """The real, live set of format/bitrate values the installed spotdl accepts --
    introspected from its own argparse definition, not a hardcoded guess that could
    drift from what actually works. Backs the settings UI's format/bitrate selectors."""
    return downloads.get_supported_output_options()


@router.patch("/output")
def update_output_settings(
    payload: UpdateOutputSettingsRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    """Takes effect on the *next* download_track call, no restart needed -- get_downloader's
    cache key includes format/bitrate/output_dir/output_template (see downloads.py), so a
    change here simply misses the cache and builds a fresh Downloader instead of reusing a
    stale one."""
    fields = payload.model_dump(exclude_unset=True)

    options = downloads.get_supported_output_options()
    if "default_format" in fields and fields["default_format"] not in options["formats"]:
        raise ApiError(
            400,
            "unsupported_format",
            f"Unsupported format: {fields['default_format']!r}",
            {"value": fields["default_format"]},
        )
    if "default_bitrate" in fields and fields["default_bitrate"] not in options["bitrates"]:
        raise ApiError(
            400,
            "unsupported_bitrate",
            f"Unsupported bitrate: {fields['default_bitrate']!r}",
            {"value": fields["default_bitrate"]},
        )

    row = app_settings.update_output_settings(db, **fields)
    db.commit()
    return _output_settings_to_dict(row)


def _library_settings_to_dict(row: AppSettings) -> dict:
    return {
        "library_target_dir": row.library_target_dir,
        "library_folder_template": row.library_folder_template,
        "library_quarantine_enabled": row.library_quarantine_enabled,
        "library_quarantine_dir": row.library_quarantine_dir,
    }


@router.get("/library")
def get_library_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    row = app_settings.get_library_settings(db)
    db.commit()
    return _library_settings_to_dict(row)


@router.patch("/library")
def update_library_settings(
    payload: UpdateLibrarySettingsRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    fields = payload.model_dump(exclude_unset=True)
    for key in ("library_target_dir", "library_folder_template", "library_quarantine_dir"):
        # An explicit null was a 500 (review round 7): it's as blank as an empty string.
        if key in fields and (fields[key] is None or not fields[key].strip()):
            raise ApiError(400, "setting_blank", f"{key} must not be blank", {"field": key})

    # v57 (L2): the directories as they'd be after this save, so a change to one is checked
    # against the others' current values.
    current = app_settings.get_library_settings(db)
    check_library_paths(
        downloads_dir=get_settings().download_output_dir,
        library_dir=fields.get("library_target_dir", current.library_target_dir),
        quarantine_dir=fields.get("library_quarantine_dir", current.library_quarantine_dir),
    )

    row = app_settings.update_library_settings(db, **fields)
    db.commit()
    return _library_settings_to_dict(row)


class UpdateAlertSettingsRequest(BaseModel):
    alerts_breaker_enabled: bool | None = None
    alerts_spike_enabled: bool | None = None
    alerts_beat_stale_enabled: bool | None = None
    alerts_library_enabled: bool | None = None
    alerts_worker_down_enabled: bool | None = None
    alert_spike_threshold: int | None = None
    alert_spike_window_minutes: int | None = None
    alert_beat_stale_seconds: int | None = None
    alert_worker_down_minutes: int | None = None
    alert_cooldown_minutes: int | None = None


# (min, max). Lower bounds keep a setting meaningful (a beat-stale threshold under two
# 30s ticks would alert on ordinary jitter); upper bounds keep it inside the Integer
# column and a sane range (a week, or 1000 attempts in a row).
_ALERT_BOUNDS = {
    "alert_spike_threshold": (2, 1000),
    "alert_spike_window_minutes": (1, 7 * 24 * 60),
    "alert_beat_stale_seconds": (90, 7 * 24 * 3600),
    # v59: two of the watchdog's 60s checks at the least.
    "alert_worker_down_minutes": (2, 7 * 24 * 60),
    "alert_cooldown_minutes": (1, 7 * 24 * 60),
}


def _alert_settings_to_dict(row: AppSettings) -> dict:
    # `configured` is all the API ever says about the Matrix credentials -- never the
    # homeserver, room or token themselves.
    return {
        "configured": alerts.is_configured(),
        **{field: getattr(row, field) for field in app_settings.ALERT_SETTING_FIELDS},
    }


@router.get("/alerts")
def get_alert_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    row = app_settings.get_alert_settings(db)
    db.commit()
    return _alert_settings_to_dict(row)


@router.patch("/alerts")
def update_alert_settings(
    payload: UpdateAlertSettingsRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    fields = payload.model_dump(exclude_unset=True)
    for key, (minimum, maximum) in _ALERT_BOUNDS.items():
        if fields.get(key) is not None and not minimum <= fields[key] <= maximum:
            raise ApiError(
                400,
                "setting_out_of_range",
                f"{key} must be between {minimum} and {maximum}",
                {"field": key, "min": minimum, "max": maximum},
            )
    row = app_settings.update_alert_settings(db, **fields)
    db.commit()
    return _alert_settings_to_dict(row)


# v64: the job export's limits. Each is an override of its env default (EXPORT_MAX_FILES,
# EXPORT_MAX_GB); `null` clears it. Upper bounds keep a value inside the Integer column
# and sane: an export is one streamed response, never a backup tool.
class UpdateExportSettingsRequest(BaseModel):
    export_max_files: int | None = None
    export_max_gb: int | None = None


_EXPORT_BOUNDS = {
    "export_max_files": (1, 100_000),
    "export_max_gb": (1, 10_000),
}


def _export_settings_to_dict(row: AppSettings) -> dict:
    env = get_settings()
    return {
        "export_max_files": row.export_max_files,
        "export_max_gb": row.export_max_gb,
        "default_max_files": env.export_max_files,
        "default_max_gb": env.export_max_gb,
    }


@router.get("/export")
def get_export_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    row = app_settings.get_export_settings(db)
    db.commit()
    return _export_settings_to_dict(row)


@router.patch("/export")
def update_export_settings(
    payload: UpdateExportSettingsRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict:
    fields = payload.model_dump(exclude_unset=True)
    for key, (minimum, maximum) in _EXPORT_BOUNDS.items():
        if fields.get(key) is not None and not minimum <= fields[key] <= maximum:
            raise ApiError(
                400,
                "setting_out_of_range",
                f"{key} must be between {minimum} and {maximum}",
                {"field": key, "min": minimum, "max": maximum},
            )
    row = app_settings.update_export_settings(db, **fields)
    db.commit()
    return _export_settings_to_dict(row)


@router.post("/alerts/test")
def send_test_alert(
    db: Session = Depends(get_db), user: User = Depends(require_admin_hidden)
) -> dict:
    """Sends one message straight to the room and reports whether it arrived, bypassing
    the category toggles and the cooldown -- the point is to check the wiring. Admin-only
    and synchronous (alerts.SEND_TIMEOUT_SECONDS per connect/read phase), never on a download
    path. v59: recorded in the alert outbox as sent or failed, for the history panel."""
    try:
        alerts.send_test(db, f"Test alert, sent from the settings page by {user.email}.")
    except alerts.AlertsNotConfigured:
        raise ApiError(
            409,
            "alerts_not_configured",
            "Matrix alerts are not configured (set MATRIX_HOMESERVER_URL, "
            "MATRIX_ACCESS_TOKEN and MATRIX_ROOM_ID)",
        ) from None
    except alerts.AlertSendError as exc:
        alerts.logger.warning("alerts: test alert not sent: %s", exc)
        raise ApiError(
            502, "alert_send_failed", f"Matrix send failed: {exc}", {"reason": str(exc)}
        ) from None
    alerts.logger.info("alerts: test alert sent")
    return {"sent": True}


def _retention_to_dict(row: UserSettings) -> dict:
    return {"retention_days": row.retention_days}


@router.get("/retention")
def get_retention_settings(
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """Per-user, open to every user (unlike `/output`'s admin gating) -- retention is
    each user's own log-hygiene preference, not a shared deployment config."""
    row = user_settings.get_user_settings(db, user.id)
    db.commit()
    return _retention_to_dict(row)


@router.patch("/retention")
def update_retention_settings(
    payload: UpdateRetentionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    # v56 (A5): the client's own bound. Unbounded, a huge value overflowed the archive
    # sweep's `timedelta(days=...)` and stopped it for every user after this one.
    days = payload.retention_days
    if days is not None and not RETENTION_DAYS_MIN <= days <= RETENTION_DAYS_MAX:
        raise ApiError(
            422,
            "retention_out_of_range",
            f"retention_days must be {RETENTION_DAYS_MIN}-{RETENTION_DAYS_MAX}, or null",
            {"min": RETENTION_DAYS_MIN, "max": RETENTION_DAYS_MAX},
        )
    row = user_settings.update_retention(db, user.id, payload.retention_days)
    db.commit()
    return _retention_to_dict(row)


def _keyboard_to_dict(row: UserSettings) -> dict:
    return {"keyboard_shortcuts": row.keyboard_shortcuts}


@router.get("/keyboard")
def get_keyboard_settings(
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """v45: per-user, open to every user, like `/retention` -- the off switch for
    single-character shortcuts (WCAG 2.1.4). Stored server-side so it follows the user
    across devices; `/api/auth/me` carries the same value for the app shell."""
    row = user_settings.get_user_settings(db, user.id)
    db.commit()
    return _keyboard_to_dict(row)


@router.patch("/keyboard")
def update_keyboard_settings(
    payload: UpdateKeyboardRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    row = user_settings.update_keyboard_shortcuts(db, user.id, payload.keyboard_shortcuts)
    db.commit()
    return _keyboard_to_dict(row)


def _language_to_dict(row: UserSettings) -> dict:
    return {"language": row.language}


@router.get("/language")
def get_language_settings(
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """v46: per-user, open to every user, like `/keyboard`. `null` is "no saved choice" (the
    browser's language decides); `/api/auth/me` carries the same value for the app shell."""
    row = user_settings.get_user_settings(db, user.id)
    db.commit()
    return _language_to_dict(row)


@router.patch("/language")
def update_language_settings(
    payload: UpdateLanguageRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    row = user_settings.update_language(db, user.id, payload.language)
    db.commit()
    return _language_to_dict(row)


def _clock_to_dict(row: UserSettings) -> dict:
    return {"clock": row.clock}


@router.get("/clock")
def get_clock_settings(
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """v46 (owner-directed): per-user, open to every user, like `/language`. `null` is
    automatic (the browser's region picks 12- or 24-hour); `/api/auth/me` carries it too."""
    row = user_settings.get_user_settings(db, user.id)
    db.commit()
    return _clock_to_dict(row)


@router.patch("/clock")
def update_clock_settings(
    payload: UpdateClockRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    row = user_settings.update_clock(db, user.id, payload.clock)
    db.commit()
    return _clock_to_dict(row)
