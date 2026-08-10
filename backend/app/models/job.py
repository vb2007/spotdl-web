import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class JobSourceType(str, enum.Enum):
    TRACK = "track"
    ALBUM = "album"
    PLAYLIST = "playlist"
    ARTIST = "artist"
    SEARCH = "search"


class JobState(str, enum.Enum):
    EXPANDING = "expanding"
    EXPANDED = "expanded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(Base):
    """One row per submitted URL (album/playlist/artist/track)."""

    __tablename__ = "jobs"
    __table_args__ = (
        # The exact shape of v18's default job-list query.
        Index("ix_jobs_user_id_created_at", "user_id", text("created_at DESC")),
        # The default (non-archived) list is the hot path and deserves its own index.
        # Hand-written: autogenerate does not emit partial indexes (v02's gotcha).
        Index(
            "ix_jobs_user_id_created_at_active",
            "user_id",
            text("created_at DESC"),
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[JobSourceType] = mapped_column(
        Enum(JobSourceType, name="job_source_type", values_callable=lambda cls: [e.value for e in cls]),
        nullable=False,
    )
    state: Mapped[JobState] = mapped_column(
        Enum(JobState, name="job_state", values_callable=lambda cls: [e.value for e in cls]),
        nullable=False,
        default=JobState.EXPANDING,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
