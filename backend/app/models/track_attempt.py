import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.track import TrackErrorType


class TrackAttemptOutcome(str, enum.Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED_DUPLICATE = "skipped_duplicate"


class NetworkPath(str, enum.Enum):
    """Which network path an attempt actually used (v29). Only the two *direct* rungs are
    forced by app code -- PROXY is recorded but never forced, since a proxy's destination is
    always a literal IPv4 host (proxies.PROXY_URL_RE) and forcing a family for it would be
    meaningless at best. NULL on rows where no real network attempt happened (breaker-active,
    dedup-skip, cancelled-before-dispatch) -- see download.py."""

    DIRECT_IPV4 = "direct-ipv4"
    DIRECT_IPV6 = "direct-ipv6"
    PROXY = "proxy"


class TrackAttempt(Base):
    """One row per `download_track` invocation (v24) -- what it tried (direct vs. which
    proxy) and what happened, so a recurring failure is diagnosable from the UI instead
    of by reading worker logs. Never pruned in this version (see CLAUDE.md's v24 entry);
    add retention only if the row count ever actually proves it necessary."""

    __tablename__ = "track_attempts"
    __table_args__ = (
        Index("ix_track_attempts_track_id_attempt_number", "track_id", "attempt_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracks.id"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime] = mapped_column(nullable=False)
    outcome: Mapped[TrackAttemptOutcome] = mapped_column(
        Enum(
            TrackAttemptOutcome,
            name="track_attempt_outcome",
            values_callable=lambda cls: [e.value for e in cls],
        ),
        nullable=False,
    )
    # Reuses tracks.last_error_type's own enum type rather than inventing a second one --
    # see the migration's create_type=False on this column for the Postgres-side half of
    # that (docs/GOTCHAS.md's enum gotchas).
    error_type: Mapped[TrackErrorType | None] = mapped_column(
        Enum(
            TrackErrorType,
            name="track_error_type",
            values_callable=lambda cls: [e.value for e in cls],
        ),
        nullable=True,
    )
    # Already redacted by the caller before this is set -- same contract as
    # tracks.last_error (docs/GOTCHAS.md v07), not re-redacted here.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    proxy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("proxies.id"), nullable=True)
    network_path: Mapped[NetworkPath | None] = mapped_column(
        Enum(
            NetworkPath,
            name="track_network_path",
            values_callable=lambda cls: [e.value for e in cls],
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
