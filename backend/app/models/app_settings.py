from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AppSettings(Base):
    """Single-row table (v13) backing the output-format defaults editable from the
    settings UI — env vars (DEFAULT_FORMAT/DEFAULT_BITRATE/DOWNLOAD_OUTPUT_DIR) only seed
    this row on first read, same get-or-create shape as WorkerState."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    default_format: Mapped[str] = mapped_column(Text, nullable=False)
    default_bitrate: Mapped[str] = mapped_column(Text, nullable=False)
    output_dir: Mapped[str] = mapped_column(Text, nullable=False)
    output_template: Mapped[str] = mapped_column(Text, nullable=False)
