"""Output-format defaults (v13) and library sort & move settings (v28) -- both editable
from the settings UI without a redeploy, both living on the same single-row table.

DEFAULT_FORMAT/DEFAULT_BITRATE env vars only seed this singleton row on first read;
after that this table is the source of truth. Same get-or-create shape as
app/services/retry.get_worker_state. The library fields have no env-var seed of their
own -- they're admin-editable config from the moment this row is first created.

output_dir is deliberately NOT stored here -- it stays purely env
(DOWNLOAD_OUTPUT_DIR)-sourced (see app/models/app_settings.py's docstring for why real
user testing walked this back).
"""

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSettings

# v28: was spotdl's own default ("{artists} - {title}.{output-ext}",
# spotdl.utils.config.DEFAULT_CONFIG["output"]) until this version changed it to match
# the existing real library's naming convention: track number first.
DEFAULT_OUTPUT_TEMPLATE = "{track-number} - {artists} - {title}.{output-ext}"

# v28: library sort & move admin settings -- see plan/master-v3/v28-library-sort-move.md.
# library_target_dir/library_quarantine_dir are container-internal paths; the compose
# files are what actually bind-mounts a real host directory there (see docker-compose*.yml).
DEFAULT_LIBRARY_TARGET_DIR = "/mnt/raid1/media/music"
DEFAULT_LIBRARY_FOLDER_TEMPLATE = "{artist} - {album} - ({year})"
DEFAULT_LIBRARY_QUARANTINE_DIR = "/downloads/quarantine"


def _get_or_create_settings_row(db: Session) -> AppSettings:
    row = db.get(AppSettings, 1)
    if row is None:
        env = get_settings()
        row = AppSettings(
            id=1,
            default_format=env.default_format,
            default_bitrate=env.default_bitrate,
            output_template=DEFAULT_OUTPUT_TEMPLATE,
            library_target_dir=DEFAULT_LIBRARY_TARGET_DIR,
            library_folder_template=DEFAULT_LIBRARY_FOLDER_TEMPLATE,
            library_quarantine_enabled=True,
            library_quarantine_dir=DEFAULT_LIBRARY_QUARANTINE_DIR,
        )
        db.add(row)
        db.flush()
    return row


def get_output_settings(db: Session) -> AppSettings:
    return _get_or_create_settings_row(db)


def update_output_settings(
    db: Session,
    *,
    default_format: str | None = None,
    default_bitrate: str | None = None,
    output_template: str | None = None,
) -> AppSettings:
    row = _get_or_create_settings_row(db)
    if default_format is not None:
        row.default_format = default_format
    if default_bitrate is not None:
        row.default_bitrate = default_bitrate
    if output_template is not None:
        row.output_template = output_template
    return row


def get_library_settings(db: Session) -> AppSettings:
    return _get_or_create_settings_row(db)


def update_library_settings(
    db: Session,
    *,
    library_target_dir: str | None = None,
    library_folder_template: str | None = None,
    library_quarantine_enabled: bool | None = None,
    library_quarantine_dir: str | None = None,
) -> AppSettings:
    row = _get_or_create_settings_row(db)
    if library_target_dir is not None:
        row.library_target_dir = library_target_dir
    if library_folder_template is not None:
        row.library_folder_template = library_folder_template
    if library_quarantine_enabled is not None:
        row.library_quarantine_enabled = library_quarantine_enabled
    if library_quarantine_dir is not None:
        row.library_quarantine_dir = library_quarantine_dir
    return row
