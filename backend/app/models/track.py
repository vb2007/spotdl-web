import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TrackState(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    WAITING = "waiting"
    LOOKUP_FAILED = "lookup_failed"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    CANCELLED = "cancelled"


class TrackErrorType(str, enum.Enum):
    AUDIO_PROVIDER = "audio_provider"
    LOOKUP = "lookup"
    OTHER = "other"


class Track(Base):
    """One row per individual song discovered while expanding a job — the unit the retry
    engine and worker operate on."""

    __tablename__ = "tracks"
    __table_args__ = (
        Index(
            "ix_tracks_scheduled_at_waiting",
            "scheduled_at",
            postgresql_where=text("state = 'waiting'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id"), nullable=False, index=True
    )
    spotify_track_id: Mapped[str] = mapped_column(Text, index=True, nullable=False)
    song_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[TrackState] = mapped_column(
        Enum(TrackState, name="track_state", values_callable=lambda cls: [e.value for e in cls]),
        nullable=False,
        default=TrackState.PENDING,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_type: Mapped[TrackErrorType | None] = mapped_column(
        Enum(
            TrackErrorType,
            name="track_error_type",
            values_callable=lambda cls: [e.value for e in cls],
        ),
        nullable=True,
    )
    used_proxy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("proxies.id"), nullable=True
    )
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
