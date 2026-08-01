import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, Integer, Text, func
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

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
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
