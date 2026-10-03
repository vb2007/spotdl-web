from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import AppSettings, User, UserSettings
from app.routers.auth import require_admin, require_session
from app.services import alerts, app_settings, downloads, user_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class UpdateOutputSettingsRequest(BaseModel):
    default_format: str | None = None
    default_bitrate: str | None = None
    output_template: str | None = None


class UpdateRetentionRequest(BaseModel):
    retention_days: int | None


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
        raise HTTPException(status_code=400, detail=f"Unsupported format: {fields['default_format']!r}")
    if "default_bitrate" in fields and fields["default_bitrate"] not in options["bitrates"]:
        raise HTTPException(
            status_code=400, detail=f"Unsupported bitrate: {fields['default_bitrate']!r}"
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
        if key in fields and not fields[key].strip():
            raise HTTPException(status_code=400, detail=f"{key} must not be blank")

    row = app_settings.update_library_settings(db, **fields)
    db.commit()
    return _library_settings_to_dict(row)


class UpdateAlertSettingsRequest(BaseModel):
    alerts_breaker_enabled: bool | None = None
    alerts_spike_enabled: bool | None = None
    alerts_beat_stale_enabled: bool | None = None
    alerts_library_enabled: bool | None = None
    alert_spike_threshold: int | None = None
    alert_spike_window_minutes: int | None = None
    alert_beat_stale_seconds: int | None = None
    alert_cooldown_minutes: int | None = None


# (min, max). Lower bounds keep a setting meaningful (a beat-stale threshold under two
# 30s ticks would alert on ordinary jitter); upper bounds keep it inside the Integer
# column and a sane range (a week, or 1000 attempts in a row).
_ALERT_BOUNDS = {
    "alert_spike_threshold": (2, 1000),
    "alert_spike_window_minutes": (1, 7 * 24 * 60),
    "alert_beat_stale_seconds": (90, 7 * 24 * 3600),
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
            raise HTTPException(
                status_code=400, detail=f"{key} must be between {minimum} and {maximum}"
            )
    row = app_settings.update_alert_settings(db, **fields)
    db.commit()
    return _alert_settings_to_dict(row)


def _require_admin_hidden(user: User = Depends(require_session)) -> User:
    """v36's plan: a non-admin gets 404 on the test-alert endpoint, so its existence isn't
    confirmed (the other admin-only routes here answer 403, via require_admin)."""
    if not user.is_admin:
        raise HTTPException(status_code=404, detail="Not Found")
    return user


@router.post("/alerts/test")
def send_test_alert(user: User = Depends(_require_admin_hidden)) -> dict:
    """Sends one message straight to the room and reports whether it arrived, bypassing
    the category toggles and the cooldown -- the point is to check the wiring. Admin-only
    and synchronous (alerts.SEND_TIMEOUT_SECONDS per connect/read phase), never on a download
    path."""
    try:
        alerts.send_now(f"Test alert, sent from the settings page by {user.email}.")
    except alerts.AlertsNotConfigured:
        raise HTTPException(
            status_code=409,
            detail="Matrix alerts are not configured (set MATRIX_HOMESERVER_URL, "
            "MATRIX_ACCESS_TOKEN and MATRIX_ROOM_ID)",
        ) from None
    except alerts.AlertSendError as exc:
        alerts.logger.warning("alerts: test alert not sent: %s", exc)
        raise HTTPException(status_code=502, detail=f"Matrix send failed: {exc}") from None
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
    if payload.retention_days is not None and payload.retention_days <= 0:
        raise HTTPException(
            status_code=400, detail="retention_days must be a positive integer or null"
        )
    row = user_settings.update_retention(db, user.id, payload.retention_days)
    db.commit()
    return _retention_to_dict(row)
