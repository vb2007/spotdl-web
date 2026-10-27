import enum
from datetime import datetime

from sqlalchemy import Boolean, Enum, Integer, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LibrarySortState(str, enum.Enum):
    IDLE = "idle"
    RUNNING = "running"


class LibrarySortRun(Base):
    """Single-row table (v28) tracking the admin-triggered library sort & move sweep --
    same get-or-create singleton shape as WorkerState/AppSettings. Doubles as both the
    live-progress source `GET /api/library/sort/status` polls/reads and the last
    finished sweep's report (moved/skipped-present/quarantined/errors), since a sweep's
    final state *is* its own report -- no separate history table, matching the
    single-admin, on-demand nature of this feature."""

    __tablename__ = "library_sort_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    state: Mapped[LibrarySortState] = mapped_column(
        Enum(LibrarySortState, name="library_sort_state", values_callable=lambda cls: [e.value for e in cls]),
        nullable=False,
        default=LibrarySortState.IDLE,
    )
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    moved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_present: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quarantined: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # List of {"file": <original source path>, "error": <message>} -- always reassigned
    # wholesale (never appended in place), the same convention song_json already uses,
    # since SQLAlchemy's JSONB change tracking doesn't see an in-place mutation.
    errors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # v57 (L1): `POST /api/library/sort/cancel` sets cancel_requested; the sweep reads it between
    # files (never mid-file) and, when it stops on it, sets cancelled, so the report says
    # "cancelled after N of M" (processed of total). Both are reset by the next start.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
