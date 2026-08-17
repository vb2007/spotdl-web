from sqlalchemy import Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AppSettings(Base):
    """Single-row table (v13) backing the output-format defaults editable from the
    settings UI — env vars (DEFAULT_FORMAT/DEFAULT_BITRATE) only seed this row on first
    read, same get-or-create shape as WorkerState.

    No `output_dir` column: real user testing found that editable meaningless in
    practice (the directory a running container can actually write to is fixed by its
    volume mount at deploy time, not by an app-level setting) -- it stays purely env
    (`DOWNLOAD_OUTPUT_DIR`)-sourced, read fresh wherever it's needed, never stored here.

    v28 adds the library sort & move settings to this same row rather than a second
    singleton table -- they're admin-editable config with no env-var seed of their own,
    same shape as the output-format fields above."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    default_format: Mapped[str] = mapped_column(Text, nullable=False)
    default_bitrate: Mapped[str] = mapped_column(Text, nullable=False)
    output_template: Mapped[str] = mapped_column(Text, nullable=False)
    library_target_dir: Mapped[str] = mapped_column(Text, nullable=False)
    library_folder_template: Mapped[str] = mapped_column(Text, nullable=False)
    library_quarantine_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    library_quarantine_dir: Mapped[str] = mapped_column(Text, nullable=False)
