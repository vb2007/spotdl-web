from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import AppSettings, User, UserSettings
from app.routers.auth import require_admin, require_session
from app.services import app_settings, downloads, user_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class UpdateOutputSettingsRequest(BaseModel):
    default_format: str | None = None
    default_bitrate: str | None = None
    output_template: str | None = None


class UpdateRetentionRequest(BaseModel):
    retention_days: int | None


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
