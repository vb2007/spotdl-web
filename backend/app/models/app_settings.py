from sqlalchemy import Boolean, Integer, Text, true
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
    same shape as the output-format fields above.

    v36 adds the Matrix alert controls (per-category on/off plus the thresholds and the
    cooldown, see app/services/alerts.py) the same way. server_default on each, so the
    migration fills the existing row with the documented defaults."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    default_format: Mapped[str] = mapped_column(Text, nullable=False)
    default_bitrate: Mapped[str] = mapped_column(Text, nullable=False)
    output_template: Mapped[str] = mapped_column(Text, nullable=False)
    library_target_dir: Mapped[str] = mapped_column(Text, nullable=False)
    library_folder_template: Mapped[str] = mapped_column(Text, nullable=False)
    library_quarantine_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    library_quarantine_dir: Mapped[str] = mapped_column(Text, nullable=False)
    # v36: alert categories (app/services/alerts.py's CATEGORIES) and their tunables.
    alerts_breaker_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    alerts_spike_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    alerts_beat_stale_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    alerts_library_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    # Failure spike: this many consecutive real attempts, all failing with the same
    # error_type, within the window.
    alert_spike_threshold: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    alert_spike_window_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
    # Beat's heartbeat older than this is "beat stale" (it ticks every 30s).
    alert_beat_stale_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="180")
    # How long an identical alert (same category + fingerprint) stays suppressed.
    alert_cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
