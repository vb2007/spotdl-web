from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import AppSettings, User
from app.routers.auth import require_admin
from app.services import app_settings, downloads

router = APIRouter(prefix="/api/settings", tags=["settings"])


class UpdateOutputSettingsRequest(BaseModel):
    default_format: str | None = None
    default_bitrate: str | None = None
    output_template: str | None = None


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
