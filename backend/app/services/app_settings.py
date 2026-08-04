"""Output-format defaults (v13) -- editable from the settings UI without a redeploy.

DEFAULT_FORMAT/DEFAULT_BITRATE/DOWNLOAD_OUTPUT_DIR env vars only seed this singleton row
on first read; after that this table is the source of truth. Same get-or-create shape as
app/services/retry.get_worker_state.
"""

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSettings

# spotdl's own default output filename template
# (spotdl.utils.config.DEFAULT_CONFIG["output"]) -- the seed value for output_template,
# same constant app/services/downloads.py used to hardcode before this version.
DEFAULT_OUTPUT_TEMPLATE = "{artists} - {title}.{output-ext}"


def get_output_settings(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if row is None:
        env = get_settings()
        row = AppSettings(
            id=1,
            default_format=env.default_format,
            default_bitrate=env.default_bitrate,
            output_dir=env.download_output_dir,
            output_template=DEFAULT_OUTPUT_TEMPLATE,
        )
        db.add(row)
        db.flush()
    return row


def update_output_settings(
    db: Session,
    *,
    default_format: str | None = None,
    default_bitrate: str | None = None,
    output_dir: str | None = None,
    output_template: str | None = None,
) -> AppSettings:
    row = get_output_settings(db)
    if default_format is not None:
        row.default_format = default_format
    if default_bitrate is not None:
        row.default_bitrate = default_bitrate
    if output_dir is not None:
        row.output_dir = output_dir
    if output_template is not None:
        row.output_template = output_template
    return row
