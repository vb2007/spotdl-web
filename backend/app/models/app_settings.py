from sqlalchemy import Boolean, Integer, Text, text, true
from sqlalchemy.dialects.postgresql import JSONB
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
    cooldown, see app/services/alerts.py) the same way, and v59 the worker-down category.
    server_default on each, so the migration fills the existing row with the documented
    defaults.

    v64 adds the job export's limits as nullable overrides: NULL means the env default
    (EXPORT_MAX_FILES/EXPORT_MAX_GB), so a deploy that changes the env still takes effect
    until an admin pins a value."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    default_format: Mapped[str] = mapped_column(Text, nullable=False)
    default_bitrate: Mapped[str] = mapped_column(Text, nullable=False)
    output_template: Mapped[str] = mapped_column(Text, nullable=False)
    library_target_dir: Mapped[str] = mapped_column(Text, nullable=False)
    library_folder_template: Mapped[str] = mapped_column(Text, nullable=False)
    library_quarantine_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    library_quarantine_dir: Mapped[str] = mapped_column(Text, nullable=False)
    # v57 (L6): every library_target_dir this install has used, the current one included, so a
    # ledger row left under an earlier root still dedups and is still served after a repoint
    # (app/services/dedup.py's known_library_roots). Only ever grows; reassigned wholesale.
    library_known_roots: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # v36: alert categories (app/services/alerts.py's CATEGORIES) and their tunables.
    alerts_breaker_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    alerts_spike_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    alerts_beat_stale_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    alerts_library_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    # v59: worker-dl consuming nothing while due tracks wait and the breaker is closed.
    alerts_worker_down_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=true()
    )
    # Failure spike: this many consecutive real attempts, all failing with the same
    # error_type, within the window.
    alert_spike_threshold: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    alert_spike_window_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
    # Beat's heartbeat older than this is "beat stale" (it ticks every 30s).
    alert_beat_stale_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="180")
    # v59: due work unconsumed for this long is "worker down" (the watchdog checks every 60s).
    alert_worker_down_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="15")
    # How long an identical alert (same category + fingerprint) stays suppressed.
    alert_cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
    # v64: the job export's limits; NULL = the env default (config.py's export_max_*).
    export_max_files: Mapped[int | None] = mapped_column(Integer, nullable=True)
    export_max_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
