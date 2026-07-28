from datetime import datetime

from sqlalchemy import Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DownloadedTrack(Base):
    """Dedup ledger, independent of `tracks` so it survives job/track deletion and powers the
    startup disk-reconciliation scan (v05)."""

    __tablename__ = "downloaded_tracks"

    spotify_track_id: Mapped[str] = mapped_column(Text, primary_key=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    bitrate: Mapped[str | None] = mapped_column(Text, nullable=True)
    downloaded_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
