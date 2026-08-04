from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AppSettings, UserSession
from app.routers.auth import require_session
from app.services import app_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class UpdateOutputSettingsRequest(BaseModel):
    default_format: str | None = None
    default_bitrate: str | None = None
    output_dir: str | None = None
    output_template: str | None = None


def _output_settings_to_dict(row: AppSettings) -> dict:
    return {
        "default_format": row.default_format,
        "default_bitrate": row.default_bitrate,
        "output_dir": row.output_dir,
        "output_template": row.output_template,
    }


@router.get("/output")
def get_output_settings(
    db: Session = Depends(get_db),
    _: UserSession = Depends(require_session),
) -> dict:
    row = app_settings.get_output_settings(db)
    db.commit()
    return _output_settings_to_dict(row)


@router.patch("/output")
def update_output_settings(
    payload: UpdateOutputSettingsRequest,
    db: Session = Depends(get_db),
    _: UserSession = Depends(require_session),
) -> dict:
    """Takes effect on the *next* download_track call, no restart needed -- get_downloader's
    cache key includes format/bitrate/output_dir/output_template (see downloads.py), so a
    change here simply misses the cache and builds a fresh Downloader instead of reusing a
    stale one."""
    row = app_settings.update_output_settings(db, **payload.model_dump(exclude_unset=True))
    db.commit()
    return _output_settings_to_dict(row)
